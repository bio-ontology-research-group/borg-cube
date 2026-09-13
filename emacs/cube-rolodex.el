;;; cube-rolodex.el --- Session ring for agent terminals  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, processes

;;; Commentary:

;; The rolodex is the ring of interactive agent sessions: Claude Code,
;; Codex, Hermes profiles, plain shells and attached `cube run' jobs.  In
;; remote mode every session is a tmux session on `cube-remote-host'
;; attached through `ssh -t' inside a terminal buffer, so a laptop
;; disconnect never kills an agent.  Buffers are named
;; *cube:<kind>:<name>*.  Ordering is attention first, then idle, then
;; running, pinned sessions first within each group, otherwise stable.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'tabulated-list)
(require 'transient)
(require 'cube-core)
(require 'cube-term)

(declare-function cube-projects "cube-project" (&optional refresh))
(declare-function cube-menu--context-items "cube-menu" (type))

(cl-defstruct (cube-session (:constructor cube-session-create)
                            (:copier nil))
  "One interactive session known to the cockpit."
  name kind role student bead buffer cwd command started last-activity
  (state 'running) reason run-id resume-id project adopted pinned remote
  agent-kind title topics tags)

(defvar cube-rolodex--sessions nil
  "All registered `cube-session' structs, in creation order.")

(defvar cube-rolodex--previous-buffer nil
  "Buffer to return to with `cube-rolodex-toggle'.")

(defvar cube-rolodex--last-session nil
  "Last session buffer that was shown, used by `cube-rolodex-toggle'.")

(defvar cube-rolodex--idle-timer nil
  "Timer that demotes silent running sessions to idle.")

(defvar cube-rolodex-state-change-hook nil
  "Hook run with the session after its state changed.")

(defconst cube-rolodex-kinds '(claude codex hermes shell run attach agent)
  "Session kinds the rolodex knows how to start.")

(defconst cube-rolodex-roles-fallback
  '("group-leader" "senior" "programmer" "auditor" "editor" "lecturer"
    "scribe" "advisor" "sysadmin" "secretary" "sentinel" "marshal" "concierge"
    "liaison" "student-researcher" "student-reviewer" "grant-writer")
  "Role names shipped in roles/*.yaml, used until `cube roles' has answered.")

(defvar cube-rolodex-roles cube-rolodex-roles-fallback
  "Role names accepted by `cube run'.
Refreshed from `cube roles --json' by `cube-rolodex-roles-refresh' so the
completion list matches the backend's role catalog.")

(defun cube-rolodex--roles-from-json (json)
  "Return the role name list in JSON from `cube roles --json'."
  (let ((roles (cond ((and (consp json) (assq 'roles json)) (cube-get json 'roles))
                     ((listp json) json)
                     (t nil))))
    (delq nil (mapcar (lambda (role)
                        (cond ((stringp role) role)
                              ((and (consp role) (cube-get role 'name))
                               (cube--string (cube-get role 'name)))
                              (t nil)))
                      roles))))

(defun cube-rolodex-roles-now ()
  "Return the role names, asking the backend synchronously when possible."
  (when-let* ((json (ignore-errors (cube--call-json '("roles"))))
              (names (cube-rolodex--roles-from-json json)))
    (setq cube-rolodex-roles names))
  cube-rolodex-roles)

(defun cube-rolodex-roles-refresh (&optional callback)
  "Refresh `cube-rolodex-roles' from the backend, then call CALLBACK."
  (cube--call-json-async
   '("roles")
   (lambda (json)
     (let ((names (cube-rolodex--roles-from-json json)))
       (when names (setq cube-rolodex-roles names)))
     (when callback (funcall callback cube-rolodex-roles)))
   (lambda (code err)
     (message "cube: roles list failed (%s): %s" code err)
     (when callback (funcall callback cube-rolodex-roles)))))

;;;; Naming and lookup

(defun cube-rolodex-buffer-name (kind name)
  "Return the buffer name for a session of KIND called NAME."
  (format "*cube:%s:%s*" (if (symbolp kind) (symbol-name kind) kind) name))

(defun cube-rolodex--tmux-name (name)
  "Return the tmux session name on the host for session NAME."
  (concat cube-tmux-session-prefix name))

(defun cube-rolodex--kind-string (kind)
  "Return KIND as a string."
  (if (symbolp kind) (symbol-name kind) kind))

(defun cube-rolodex--agent-coordinator-p (session)
  "Return non-nil when SESSION represents the coordinator agent."
  (and (eq (cube-session-kind session) 'agent)
       (or (equal (cube-rolodex--kind-string (cube-session-agent-kind session))
                  "coordinator")
           (equal (cube-session-name session) "coordinator"))))

(defun cube-rolodex-find (name)
  "Return the registered session called NAME, or nil."
  (seq-find (lambda (s) (string= (cube-session-name s) name))
            cube-rolodex--sessions))

(defun cube-rolodex-session-for-buffer (&optional buffer)
  "Return the session whose buffer is BUFFER (default current), or nil."
  (let ((buffer (or buffer (current-buffer))))
    (seq-find (lambda (s) (eq (cube-session-buffer s) buffer))
              cube-rolodex--sessions)))

(defun cube-rolodex-live-sessions ()
  "Return sessions whose buffer still exists."
  (seq-filter (lambda (s) (buffer-live-p (cube-session-buffer s)))
              cube-rolodex--sessions))

(defun cube-rolodex--register (session)
  "Add SESSION to the registry, replacing one with the same name."
  (setq cube-rolodex--sessions
        (append (seq-remove (lambda (s) (string= (cube-session-name s)
                                                 (cube-session-name session)))
                            cube-rolodex--sessions)
                (list session)))
  (cube-rolodex--ensure-idle-timer)
  session)

(defun cube-rolodex--unregister (session)
  "Remove SESSION from the registry."
  (setq cube-rolodex--sessions (delq session cube-rolodex--sessions)))

;;;; Command construction (pure)

(defun cube-rolodex--claude-command (props)
  "Return the claude argv for PROPS."
  (append (list "claude" "--settings" (cube-root-file "emacs/claude-hooks.json"))
          (pcase cube-claude-tui
            ('inline '("--settings" "{\"tui\":\"inline\"}"))
            ('fullscreen '("--settings" "{\"tui\":\"fullscreen\"}"))
            (_ nil))
          (when-let* ((id (plist-get props :resume))) (list "--resume" id))))

(defun cube-rolodex--inner-command (kind props)
  "Return the program argv for a session of KIND described by PROPS.
PROPS is a plist with :name, :role, :bead, :resume, :profile.  The
result runs on the backend host (inside tmux in remote mode)."
  (pcase kind
    ('claude (cube-rolodex--claude-command props))
    ('codex (if-let* ((id (plist-get props :resume)))
                (list "codex" "resume" id)
              (list "codex")))
    ('hermes (list "hermes" "-p" (or (plist-get props :profile) "advisor") "chat"))
    ('shell (if cube-remote-host
                (list "sh" "-c" "exec \"${SHELL:-/bin/sh}\" -l")
              (list (or (getenv "SHELL") "/bin/sh") "-l")))
    ('run (append (cube--program-args)
                  (list "run" (or (plist-get props :role)
                                  (error "cube: run needs a :role")))
                  (when-let* ((bead (plist-get props :bead))) (list "--bead" bead))
                  (when (plist-get props :resume) '("--resume"))
                  '("--attach")))
    ('agent (append (cube--program-args)
                    ;; --apply starts the tmux session (talk is a dry run
                    ;; otherwise); --attach turns this terminal into its client.
                    (list "agent" "talk"
                          (or (plist-get props :agent-name)
                              (plist-get props :name))
                          "--apply" "--attach")))
    ('attach nil)
    (_ (error "cube: unknown session kind %s" kind))))

(defun cube-rolodex--command-for (kind props)
  "Return the local argv that starts a session of KIND with PROPS.
Remote mode: (\"ssh\" \"-t\" HOST \"--\" \"tmux new-session -A -s
cube/NAME <quoted CMD>\"); local mode: CMD itself.  CMD is prefixed with
env CUBE_SESSION=NAME so hooks can name the session."
  (let* ((name (or (plist-get props :name) (error "cube: session needs a :name")))
         (inner (cube-rolodex--inner-command kind props))
         (inner (and inner (append (list "env" (concat "CUBE_SESSION=" name)) inner))))
    (cond
     (cube-remote-host
      (cube--ssh-args
       (append (list "tmux" "new-session" "-A" "-s"
                     (if (eq kind 'agent)
                         (concat cube-tmux-session-prefix "agent-" name)
                       (cube-rolodex--tmux-name name)))
               (and inner (list (cube--shell-join inner))))
       t))
     ((null inner) (error "cube: kind %s needs a remote host" kind))
     (t inner))))

;;;; Ordering and header line (pure)

(defun cube-rolodex--state-rank (state)
  "Return the sort rank of STATE: attention and error first, exited last."
  (pcase state
    ((or 'attention 'error) 0)
    ('idle 1)
    ('running 2)
    (_ 3)))

(defun cube-rolodex--ordered (sessions)
  "Return SESSIONS with standing agents first, then the normal ring order.
The coordinator is first among standing agents.  Pinned sessions still come
first inside an otherwise equal state group, and equal sessions are stable."
  (sort (copy-sequence sessions)
        (lambda (a b)
          (let* ((aa (eq (cube-session-kind a) 'agent))
                 (ab (eq (cube-session-kind b) 'agent))
                 (ca (and aa (cube-rolodex--agent-coordinator-p a)))
                 (cb (and ab (cube-rolodex--agent-coordinator-p b)))
                 (ra (cube-rolodex--state-rank (cube-session-state a)))
                 (rb (cube-rolodex--state-rank (cube-session-state b))))
            (cond ((not (eq aa ab)) aa)
                  ((and ca (not cb)) t)
                  ((and cb (not ca)) nil)
                  ((/= ra rb) (< ra rb))
                  (t (and (cube-session-pinned a)
                          (not (cube-session-pinned b)))))))))

(defun cube-rolodex--state-glyph (state)
  "Return a one character glyph for STATE."
  (pcase state
    ('attention "⚠") ('error "✖") ('idle "○") ('running "●") ('exited "†") (_ "?")))

(defun cube-rolodex--label (session)
  "Return KIND:NAME for SESSION."
  (if (eq (cube-session-kind session) 'agent)
      (format "%s %s" (if (cube-rolodex--agent-coordinator-p session)
                            "◎" "●")
              (cube-session-name session))
    (format "%s:%s" (cube-rolodex--kind-string (cube-session-kind session))
            (cube-session-name session))))

(defun cube-rolodex--header-line (session ordered &optional now)
  "Return the header line string for SESSION given the ORDERED ring.
Shows position, state and age, then up to `cube-attention-count' other
sessions that need attention.  NOW is for tests."
  (let* ((pos (1+ (or (seq-position ordered session) 0)))
         (others (seq-take
                  (seq-filter (lambda (s)
                                (and (not (eq s session))
                                     (memq (cube-session-state s) '(attention error))))
                              ordered)
                  cube-attention-count))
         (age (cube--age-string (cube-session-last-activity session) now)))
    (concat
     (format "[%d/%d] %s %s%s%s" pos (length ordered)
             (cube-rolodex--label session)
             (cube-rolodex--state-glyph (cube-session-state session))
             (symbol-name (cube-session-state session))
             (if (string-empty-p age) "" (concat " " age)))
     (when (cube-session-reason session)
       (format "  (%s)" (cube-session-reason session)))
     (when others
       (concat "  |  "
               (mapconcat (lambda (s) (concat "⚠ " (cube-rolodex--label s)))
                          others "  ")))
     (when-let* ((project (cube-session-project session)))
       (format " [%s]" project))
     (when (eq (cube-session-kind session) 'agent)
       (concat
        (when (cube-session-title session)
          (format "  %s" (cube-session-title session)))
        (when (cube-session-topics session)
          (format "  topics: %s"
                  (string-join (mapcar #'cube--string (cube-session-topics session))
                               ", "))))))))

(defun cube-rolodex-header-line ()
  "Header line for the current session buffer."
  (when-let* ((session (cube-rolodex-session-for-buffer)))
    (cube-rolodex--header-line session
                               (cube-rolodex--ordered (cube-rolodex-live-sessions)))))

;;;; State

(defun cube-rolodex-set-state (session state &optional reason)
  "Set SESSION's STATE and REASON, refresh displays and run hooks."
  (unless (and (eq (cube-session-state session) state)
               (equal (cube-session-reason session) reason))
    (setf (cube-session-state session) state)
    (setf (cube-session-reason session) reason)
    (force-mode-line-update t)
    (run-hook-with-args 'cube-rolodex-state-change-hook session)))

(defun cube-rolodex--note-activity (buffer _string)
  "Record output activity in BUFFER; idle sessions become running."
  (when-let* ((session (cube-rolodex-session-for-buffer buffer)))
    (setf (cube-session-last-activity session) (current-time))
    (when (eq (cube-session-state session) 'idle)
      (cube-rolodex-set-state session 'running))))

(defun cube-rolodex--check-idle ()
  "Demote silent running sessions to idle and dead ones to exited."
  (dolist (session (cube-rolodex-live-sessions))
    (let ((buffer (cube-session-buffer session)))
      (cond
       ((not (cube-term-live-p buffer))
        (unless (memq (cube-session-state session) '(exited error))
          (cube-rolodex-set-state session 'exited "process ended")))
       ((and (eq (cube-session-state session) 'running)
             (cube-session-last-activity session)
             (> (float-time (time-since (cube-session-last-activity session)))
                cube-idle-seconds))
        (cube-rolodex-set-state session 'idle))))))

(defun cube-rolodex--ensure-idle-timer ()
  "Start the idle detection timer if it is not running."
  (unless cube-rolodex--idle-timer
    (setq cube-rolodex--idle-timer
          (run-with-timer 5 5 #'cube-rolodex--check-idle))))

(defun cube-rolodex-attention-sessions ()
  "Return live sessions in attention or error state, loudest first."
  (seq-filter (lambda (s) (memq (cube-session-state s) '(attention error)))
              (cube-rolodex--ordered (cube-rolodex-live-sessions))))

;;;; Session buffer minor mode

(defun cube-session-send-escape ()
  "Send ESC to the terminal (interrupts Claude Code and Codex)."
  (interactive)
  (cube-term-send-string (current-buffer) "\e"))

(defun cube-session-send-backtab ()
  "Send S-TAB (CSI Z) to the terminal, cycling the agent's mode."
  (interactive)
  (cube-term-send-string (current-buffer) "\e[Z"))

(defun cube-session-open-context ()
  "Open the bead, run log or working directory behind this session."
  (interactive)
  (let ((session (cube-rolodex-session-for-buffer)))
    (cond ((null session) (user-error "cube: not a session buffer"))
          ((cube-session-bead session)
           (if (fboundp 'cube-beads-show)
               (funcall 'cube-beads-show (cube-session-bead session))
             (message "cube: bead %s" (cube-session-bead session))))
          ((cube-session-cwd session)
           (dired (cube-session-cwd session)))
          (t (message "cube: no context recorded for %s" (cube-session-name session))))))

(defun cube-session-adopt ()
  "Adopt the existing tmux session behind the current terminal buffer."
  (interactive)
  (if-let* ((session (cube-rolodex-session-for-buffer)))
      (cube-rolodex-adopt session)
    (user-error "cube: not a session buffer")))

(defvar cube-session-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map [escape] #'cube-session-send-escape)
    (define-key map [backtab] #'cube-session-send-backtab)
    (define-key map (kbd "C-c C-o") #'cube-session-open-context)
    (define-key map (kbd "A") #'cube-session-adopt)
    map)
  "Keymap of `cube-session-mode'.  Leaves `C-c b' to `cube-mode'.")

(define-minor-mode cube-session-mode
  "Buffer-local tweaks for agent session buffers.
ESC interrupts the agent, S-TAB cycles its mode, `C-c C-o' opens the
session's context."
  :lighter " cube"
  :keymap cube-session-mode-map
  (if cube-session-mode
      (setq header-line-format '(:eval (cube-rolodex-header-line)))
    (setq header-line-format nil)))

;;;; Starting and switching

(defun cube-rolodex--show (buffer)
  "Display BUFFER, remembering where we came from."
  (let ((from (current-buffer)))
    (unless (cube-rolodex-session-for-buffer from)
      (setq cube-rolodex--previous-buffer from))
    (setq cube-rolodex--last-session buffer)
    (switch-to-buffer buffer)
    (when-let* ((session (cube-rolodex-session-for-buffer buffer)))
      (when (eq (cube-session-state session) 'attention)
        (cube-rolodex-set-state session 'running)))))

(defun cube-rolodex--local-cwd (props)
  "Return the local working directory for a session with PROPS."
  (if cube-remote-host
      (expand-file-name "~/")
    (or (plist-get props :cwd) (cube--local-directory))))

(defun cube-rolodex-start (kind name &rest props)
  "Start a session of KIND called NAME with PROPS and show its buffer.
PROPS: :role :bead :resume :profile :cwd :student :pinned.  Reuses
the buffer when a session of that name exists but its process died."
  (let* ((kind (if (stringp kind) (intern kind) kind))
         (props (plist-put (copy-sequence props) :name name))
         (command (cube-rolodex--command-for kind props))
         (bufname (cube-rolodex-buffer-name kind name))
         (existing (get-buffer bufname)))
    (when (and existing (cube-term-live-p existing))
      (cube-rolodex--show existing)
      (user-error "cube: session %s is already running" name))
    (let* ((buffer (cube-term-make bufname (car command) (cdr command)
                                   :cwd (cube-rolodex--local-cwd props)
                                   :env (list (concat "CUBE_SESSION=" name))))
           (session (or (cube-rolodex-find name)
                        (cube-session-create :name name))))
      (setf (cube-session-kind session) kind
            (cube-session-role session) (plist-get props :role)
            (cube-session-student session) (plist-get props :student)
            (cube-session-bead session) (plist-get props :bead)
            (cube-session-buffer session) buffer
            (cube-session-cwd session) (plist-get props :cwd)
            (cube-session-command session) command
            (cube-session-started session) (current-time)
            (cube-session-last-activity session) (current-time)
            (cube-session-state session) 'running
            (cube-session-reason session) nil
            (cube-session-resume-id session) (plist-get props :resume)
            (cube-session-project session) (plist-get props :project)
            (cube-session-adopted session) (plist-get props :adopted)
            (cube-session-pinned session) (plist-get props :pinned)
            (cube-session-agent-kind session) (plist-get props :agent-kind)
            (cube-session-title session) (plist-get props :title)
            (cube-session-topics session) (plist-get props :topics)
            (cube-session-tags session) (plist-get props :tags)
            (cube-session-remote session) cube-remote-host)
      (cube-rolodex--register session)
      (with-current-buffer buffer (cube-session-mode 1))
      (cube-term-add-output-hook buffer #'cube-rolodex--note-activity)
      (cube-log "started %s (%s)" (cube-rolodex--label session)
                (string-join command " "))
      (cube-rolodex--show buffer)
      session)))

(defun cube-rolodex--read-name (kind)
  "Read a session name for KIND, defaulting to KIND-N."
  (let* ((base (cube-rolodex--kind-string kind))
         (n (1+ (seq-count (lambda (s) (eq (cube-session-kind s) kind))
                           cube-rolodex--sessions)))
         (default (format "%s-%d" base n)))
    (read-string (format "%s session name (%s): " base default)
                 nil nil default)))

(defun cube-rolodex-new-claude (name)
  "Start a Claude Code session called NAME."
  (interactive (list (cube-rolodex--read-name 'claude)))
  (cube-rolodex-start 'claude name))

(defun cube-rolodex-new-codex (name)
  "Start a Codex session called NAME."
  (interactive (list (cube-rolodex--read-name 'codex)))
  (cube-rolodex-start 'codex name))

(defun cube-rolodex-new-hermes (name profile)
  "Start a Hermes chat session called NAME with PROFILE."
  (interactive (list (cube-rolodex--read-name 'hermes)
                     (read-string "Hermes profile (advisor): " nil nil "advisor")))
  (cube-rolodex-start 'hermes name :profile profile))

(defun cube-rolodex-new-shell (name)
  "Start a shell session called NAME (on the host in remote mode)."
  (interactive (list (cube-rolodex--read-name 'shell)))
  (cube-rolodex-start 'shell name))

(defun cube-run-role (role &optional bead)
  "Prepare a guarded run of ROLE, optionally on BEAD, in a session."
  (interactive (list (completing-read "Role: " (cube-rolodex-roles-now) nil nil)
                     (let ((b (read-string "Bead id (optional): ")))
                       (unless (string-empty-p b) b))))
  (if bead
      (cube-run-bead role bead)
    (cube-run-bead role nil)))

;;;; Guarded runner starts

(defun cube-run--args (role bead &optional resume-id dry-run attach)
  "Return `cube run' arguments for ROLE and BEAD.
RESUME-ID controls whether the backend receives `--resume'; its value stays
local because `cube run' resolves the stored id from BEAD.  DRY-RUN and
ATTACH add their respective flags."
  (append (list "run" role)
          (when bead (list "--bead" bead))
          (when resume-id (list "--resume"))
          (when attach (list "--attach"))
          (when dry-run (list "--dry-run"))))

(defun cube-run--profile-text (json)
  "Return the effective runner profile in a readable form from run JSON."
  (let* ((profile (cube-get json 'runner_profile))
         (sandbox (or (cube-get profile 'sandbox) "-"))
         (cwd (or (cube-get profile 'effective_cwd) (cube-get json 'cwd)
                  (cube-get profile 'cwd) "-"))
         (pre (or (cube-get json 'pre_steps) (cube-get profile 'pre) nil)))
    (concat "Effective runner profile\n"
            (format "  Sandbox: %s\n  Cwd: %s\n" sandbox cwd)
            "  Pre-steps: "
            (if pre (string-join (mapcar #'cube--string pre) "; ") "none")
            "\n")))

(defun cube-run--show-plan (args json)
  "Show dry-run ARGS and effective profile from JSON before a runner starts."
  (with-current-buffer (get-buffer-create "*cube-run-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert "cube run dry-run\n\nCommand\n  cube " (string-join args " ")
              " --json\n\n" (cube-run--profile-text json) "\nResult\n"
              (pp-to-string json))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-run-bead (role &optional bead resume-id)
  "Dry-run and confirm ROLE on BEAD, then attach it to the rolodex.
When RESUME-ID is non-nil the resulting runner command has `--resume'."
  (interactive
   (list (completing-read "Role: " (cube-rolodex-roles-now) nil t)
         (let ((id (read-string "Bead id (optional): ")))
           (unless (string-empty-p id) id))))
  (let ((dry (cube-run--args role bead resume-id t nil)))
    (cube--call-json-async
     dry
     (lambda (json)
       (cube-run--show-plan dry json)
       (when (y-or-n-p (format "Start %s%s? " role
                               (if bead (format " on %s" bead) "")))
         (cube-rolodex-start 'run (if bead (format "%s-%s" role bead) role)
                              :role role :bead bead :resume resume-id
                              :project (cube-get json 'project))))
     (lambda (code err)
       (message "cube: run dry-run failed (%s): %s" code err)))))

(defun cube-student-session (slug)
  "Open the advisor session for the student SLUG.
V0 stub: a Claude Code session named advisor/SLUG; later versions load
the dossier and the advisor skill."
  (interactive (list (read-string "Student slug: ")))
  (cube-rolodex-start 'claude (concat "advisor/" slug) :student slug))

(defun cube-rolodex--ring ()
  "Return the ordered ring of live sessions."
  (cube-rolodex--ordered (cube-rolodex-live-sessions)))

(defun cube-rolodex--step (delta)
  "Show the session DELTA positions away from the current one."
  (let* ((ring (cube-rolodex--ring))
         (current (cube-rolodex-session-for-buffer)))
    (cond
     ((null ring) (user-error "cube: no sessions; start one with C-c b c"))
     ((null current) (cube-rolodex--show (cube-session-buffer (car ring))))
     (t (let* ((i (or (seq-position ring current) 0))
               (next (nth (mod (+ i delta) (length ring)) ring)))
          (cube-rolodex--show (cube-session-buffer next)))))))

(defun cube-rolodex-next ()
  "Flip to the next session in the ring."
  (interactive)
  (cube-rolodex--step 1))

(defun cube-rolodex-prev ()
  "Flip to the previous session in the ring."
  (interactive)
  (cube-rolodex--step -1))

(defun cube-rolodex--completion-table ()
  "Return an alist of annotated labels to sessions for `completing-read'."
  (mapcar (lambda (s)
            (cons (format "%s %s" (cube-rolodex--state-glyph (cube-session-state s))
                          (cube-rolodex--label s))
                  s))
          (cube-rolodex--ring)))

(defun cube-rolodex-jump (session)
  "Jump to SESSION chosen by name."
  (interactive
   (let ((table (cube-rolodex--completion-table)))
     (unless table (user-error "cube: no sessions"))
     (list (cdr (assoc (completing-read "Session: " table nil t) table)))))
  (cube-rolodex--show (cube-session-buffer session)))

(defun cube-rolodex-toggle ()
  "Toggle between the last session buffer and the buffer before it."
  (interactive)
  (let ((target (if (cube-rolodex-session-for-buffer)
                    cube-rolodex--previous-buffer
                  cube-rolodex--last-session)))
    (if (buffer-live-p target)
        (cube-rolodex--show target)
      (user-error "cube: nothing to toggle to"))))

(defun cube-rolodex-attention (&optional n)
  "Jump to the Nth loudest session (1-based, default the loudest)."
  (interactive "p")
  (let ((session (nth (1- (or n 1)) (cube-rolodex-attention-sessions))))
    (if session
        (cube-rolodex--show (cube-session-buffer session))
      (message "cube: nothing needs attention"))))

(defun cube-rolodex-attention-1 () "Jump to the loudest session." (interactive)
       (cube-rolodex-attention 1))
(defun cube-rolodex-attention-2 () "Jump to the second loudest session." (interactive)
       (cube-rolodex-attention 2))
(defun cube-rolodex-attention-3 () "Jump to the third loudest session." (interactive)
       (cube-rolodex-attention 3))

(defun cube-rolodex--current-or-choose ()
  "Return the current session, or ask for one."
  (or (cube-rolodex-session-for-buffer)
      (let ((table (cube-rolodex--completion-table)))
        (unless table (user-error "cube: no sessions"))
        (cdr (assoc (completing-read "Session: " table nil t) table)))))

(defun cube-rolodex-kill (session)
  "Kill SESSION's terminal buffer.  The tmux session on the host survives."
  (interactive (list (cube-rolodex--current-or-choose)))
  (let ((buffer (cube-session-buffer session)))
    (when (buffer-live-p buffer)
      (cube-term-kill buffer)
      (kill-buffer buffer))
    (cube-rolodex--unregister session)
    (message "cube: closed %s%s" (cube-rolodex--label session)
             (if (cube-session-remote session)
                 (format " (tmux %s keeps running on %s)"
                         (if (eq (cube-session-kind session) 'agent)
                             (concat cube-tmux-session-prefix "agent-"
                                     (cube-session-name session))
                           (cube-rolodex--tmux-name (cube-session-name session)))
                         (cube-session-remote session))
               ""))))

(defun cube-rolodex-restart (session &optional resume-id)
  "Restart SESSION in its buffer, passing RESUME-ID to the agent if given.
With a prefix argument prompt for the resume id."
  (interactive (let ((s (cube-rolodex--current-or-choose)))
                 (list s (when current-prefix-arg
                           (read-string "Resume id: " (cube-session-resume-id s))))))
  (let ((buffer (cube-session-buffer session)))
    (when (buffer-live-p buffer) (cube-term-kill buffer))
    (cube-rolodex--unregister session)
    (cube-rolodex-start (cube-session-kind session) (cube-session-name session)
                        :role (cube-session-role session)
                        :bead (cube-session-bead session)
                        :student (cube-session-student session)
                        :cwd (cube-session-cwd session)
                        :pinned (cube-session-pinned session)
                        :resume (or resume-id (cube-session-resume-id session))
                        :agent-kind (cube-session-agent-kind session)
                        :title (cube-session-title session)
                        :topics (cube-session-topics session)
                        :tags (cube-session-tags session))))

(defun cube-rolodex-toggle-pin (session)
  "Toggle the pinned flag of SESSION."
  (interactive (list (cube-rolodex--current-or-choose)))
  (setf (cube-session-pinned session) (not (cube-session-pinned session)))
  (force-mode-line-update t)
  (message "cube: %s %s" (cube-rolodex--label session)
           (if (cube-session-pinned session) "pinned" "unpinned")))

;;;; Remote tmux sessions

(defun cube-rolodex--parse-tmux-list (text)
  "Return the cube session names in tmux `ls' output TEXT."
  (let ((prefix cube-tmux-session-prefix))
    (delq nil
          (mapcar (lambda (line)
                    (let ((line (string-trim line)))
                      (when (string-prefix-p prefix line)
                        (substring line (length prefix)))))
                  (split-string text "\n" t)))))

(defun cube-rolodex--short-tmux-name (name)
  "Return NAME without the cockpit tmux prefix."
  (string-remove-prefix cube-tmux-session-prefix (cube--string name)))

(defun cube-rolodex-attach (name &optional metadata)
  "Attach to existing tmux session NAME on the host.
METADATA is a `cube fleet' or `cube adopt' record used to retain its project
and resume information in the local rolodex entry."
  (interactive (list (read-string "tmux session name (without prefix): ")))
  (unless cube-remote-host (user-error "cube: attach needs `cube-remote-host'"))
  (let* ((name (cube-rolodex--short-tmux-name name))
         (kind (or (cube-rolodex--guess-kind name) 'attach))
         (logical-name (if (eq kind 'agent)
                           (string-remove-prefix "agent-" name)
                         name)))
    (cube-rolodex-start kind logical-name
                         :role (cube-get metadata 'role)
                         :bead (cube-get metadata 'bead)
                         :resume (cube-get metadata 'resume_id)
                         :project (cube-get metadata 'project)
                         :cwd (cube-get metadata 'cwd)
                         :adopted (cube-true-p (cube-get metadata 'adopted))
                         :agent-kind (cube-get metadata 'kind)
                         :title (cube-get metadata 'title)
                         :topics (cube-get metadata 'topics)
                         :tags (list (concat "agent:" logical-name)))))

;;;; Adoption

(defvar cube-rolodex--adopt-name nil
  "Tmux session currently being collected by the adoption transient.")

(defvar cube-rolodex--adopt-plist nil
  "Project, optional bead, and role collected by the adoption transient.")

(defun cube-rolodex--adopt-project-completion ()
  "Return annotated project completion entries from `cube projects'."
  (mapcar (lambda (project)
            (cons (format "%s (%s)" (cube-get project 'name) (cube-get project 'slug))
                  (cube--string (cube-get project 'slug))))
          (condition-case nil (cube-projects) (error nil))))

(defun cube-rolodex--adopt-bead-completion ()
  "Return ready bead ids for the optional adoption bead field."
  (condition-case nil
      (mapcar (lambda (bead) (cube--string (cube-get bead 'id)))
              (cube-get (cube--call-json '("ready")) 'beads))
    (error nil)))

(defun cube-rolodex-adopt-set-project ()
  "Choose the project to associate with the pending adopted session."
  (interactive)
  (let* ((choices (cube-rolodex--adopt-project-completion))
         (choice (completing-read "Project: " choices nil t)))
    (setq cube-rolodex--adopt-plist
          (plist-put cube-rolodex--adopt-plist :project
                     (or (cdr (assoc choice choices)) choice)))))

(defun cube-rolodex-adopt-set-bead ()
  "Choose or clear the optional bead for the pending adopted session."
  (interactive)
  (let ((bead (completing-read "Bead (empty for none): "
                               (cube-rolodex--adopt-bead-completion) nil nil)))
    (setq cube-rolodex--adopt-plist
          (plist-put cube-rolodex--adopt-plist :bead
                     (unless (string-empty-p bead) bead)))))

(defun cube-rolodex-adopt-set-role ()
  "Choose the role recorded for the pending adopted session."
  (interactive)
  (setq cube-rolodex--adopt-plist
        (plist-put cube-rolodex--adopt-plist :role
                   (completing-read "Role: " cube-rolodex-roles nil t nil nil
                                    (or (plist-get cube-rolodex--adopt-plist :role)
                                        "programmer")))))

(defun cube-rolodex--adopt-args (name plist &optional flag)
  "Construct `cube adopt' arguments for tmux NAME and PLIST.
PLIST needs :project and may provide :bead and :role.  FLAG defaults to
`--dry-run' and can be `--apply'."
  (let ((project (cube--string (plist-get plist :project))))
    (when (string-empty-p project) (user-error "cube: adoption needs a project"))
    (append (list "adopt" (cube-rolodex--short-tmux-name name) "--project" project)
            (when-let* ((bead (plist-get plist :bead))) (list "--bead" bead))
            (when-let* ((role (plist-get plist :role))) (list "--role" role))
            (list (or flag "--dry-run")))))

(defun cube-rolodex--show-adopt-plan (args json)
  "Show adoption dry-run ARGS and JSON result before asking to apply it."
  (with-current-buffer (get-buffer-create "*cube-adopt-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert "cube adopt dry-run\n\nCommand\n  cube " (string-join args " ")
              " --json\n\nResult\n" (pp-to-string json))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-rolodex--finish-adopt (requested-name result)
  "Record applied adoption RESULT, refresh the fleet, and attach it."
  (when (fboundp 'cube-fleet--merge-session)
    (cube-fleet--merge-session result))
  (let* ((name (cube-rolodex--short-tmux-name
                (or (cube-get result 'session) requested-name)))
         (existing (cube-rolodex-find name)))
    (if (and existing (buffer-live-p (cube-session-buffer existing)))
        (progn
          (setf (cube-session-role existing) (cube-get result 'role)
                (cube-session-bead existing) (cube-get result 'bead)
                (cube-session-resume-id existing) (cube-get result 'resume_id)
                (cube-session-project existing) (cube-get result 'project)
                (cube-session-cwd existing) (cube-get result 'cwd)
                (cube-session-adopted existing) t)
          (cube-rolodex--show (cube-session-buffer existing)))
      (cube-rolodex-attach name result))
    (message "cube: adopted %s" name)))

(defun cube-rolodex-adopt-execute ()
  "Dry-run, show, confirm, and apply the adoption collected in the transient."
  (interactive)
  (let* ((base (cube-rolodex--adopt-args cube-rolodex--adopt-name
                                          cube-rolodex--adopt-plist nil))
         (dry (append (butlast base) '("--dry-run"))))
    (cube--call-json-async
     dry
     (lambda (json)
       (cube-rolodex--show-adopt-plan dry json)
       (when (y-or-n-p (format "Adopt tmux session %s? " cube-rolodex--adopt-name))
         (cube--call-json-async
          (append (butlast base) '("--apply"))
          (lambda (result) (cube-rolodex--finish-adopt cube-rolodex--adopt-name result))
          (lambda (code err) (message "cube: adopt apply failed (%s): %s" code err)))))
     (lambda (code err) (message "cube: adopt dry-run failed (%s): %s" code err)))))

(transient-define-prefix cube-rolodex-adopt-menu ()
  "Associate an existing tmux session with a project and optional bead."
  ["Adopt"
   ("p" "Project" cube-rolodex-adopt-set-project)
   ("b" "Optional bead" cube-rolodex-adopt-set-bead)
   ("r" "Role" cube-rolodex-adopt-set-role)]
  ["Execute"
   ("RET" "Preview and adopt" cube-rolodex-adopt-execute)
   ("q" "Quit" transient-quit-one)])

(defun cube-rolodex-adopt (session-or-name)
  "Start the guarded adoption flow for SESSION-OR-NAME.
The argument can be a local `cube-session', a fleet JSON record, or a tmux
session name.  No tmux or state change happens until confirmation."
  (interactive (list (read-string "Existing tmux session name: ")))
  (setq cube-rolodex--adopt-name
        (cube-rolodex--short-tmux-name
         (cond ((cube-session-p session-or-name) (cube-session-name session-or-name))
               ((listp session-or-name) (or (cube-get session-or-name 'session)
                                             (cube-get session-or-name 'name)
                                             (cube-get session-or-name 'tmux)))
               (t session-or-name))))
  (setq cube-rolodex--adopt-plist
        (list :project (and (listp session-or-name) (cube-get session-or-name 'project))
              :bead (and (listp session-or-name) (cube-get session-or-name 'bead))
              :role (or (and (listp session-or-name) (cube-get session-or-name 'role))
                        "programmer")))
  (transient-setup 'cube-rolodex-adopt-menu))

(defun cube-rolodex--guess-kind (name)
  "Guess the session kind from NAME, or nil."
  (cond ((string-prefix-p "advisor/" name) 'claude)
        ((string-prefix-p "agent-" name) 'agent)
        ((string-match "\\`\\(claude\\|codex\\|hermes\\|shell\\|run\\)-" name)
         (intern (match-string 1 name)))
        (t nil)))

(defun cube-rolodex-list-remote ()
  "List cube tmux sessions on the host and offer to attach to one."
  (interactive)
  (unless cube-remote-host (user-error "cube: no remote host configured"))
  (message "cube: listing tmux sessions on %s..." cube-remote-host)
  (cube--call-text-async
   '("tmux" "ls" "-F" "#{session_name}")
   (lambda (out)
     (let ((names (cube-rolodex--parse-tmux-list out)))
       (if (null names)
           (message "cube: no cube/* tmux sessions on %s" cube-remote-host)
         (let ((choice (completing-read "Attach to: " names nil t)))
           (unless (string-empty-p choice) (cube-rolodex-attach choice))))))
   (lambda (code err)
     (message "cube: tmux ls failed (%d): %s" code
              (if (string-empty-p err) "no sessions or ssh error" err)))))

;;;; Fleet list

(defvar cube-fleet--cache nil
  "Sessions returned by the latest successful `cube fleet --json' call.")

(defun cube-fleet--session-name (session)
  "Return the short tmux name represented by fleet SESSION."
  (cube-rolodex--short-tmux-name
   (or (cube-get session 'name) (cube-get session 'session) (cube-get session 'tmux))))

(defun cube-fleet--local-item-p (item)
  "Return non-nil when ITEM is a local `cube-session' struct."
  (cube-session-p item))

(defun cube-fleet--local-record (session)
  "Return a fleet-shaped record derived from local SESSION."
  (list (cons 'name (cube-session-name session))
        (cons 'kind (cube-rolodex--kind-string (cube-session-kind session)))
        (cons 'role (cube-session-role session))
        (cons 'bead (cube-session-bead session))
        (cons 'project (cube-session-project session))
        (cons 'resume_id (cube-session-resume-id session))
        (cons 'cwd (cube-session-cwd session))
        (cons 'adopted (and (cube-session-adopted session) t))
        (cons 'state (symbol-name (cube-session-state session)))
        (cons 'started (cube-session-started session))
        (cons 'last_event_ts (cube-session-last-activity session))
        (cons 'reason (cube-session-reason session))))

(defun cube-fleet--items ()
  "Return cached host sessions plus local entries not yet in that cache."
  (let* ((host (copy-sequence cube-fleet--cache))
         (names (mapcar #'cube-fleet--session-name host))
         (locals (seq-filter (lambda (session)
                               (not (member (cube-session-name session) names)))
                             cube-rolodex--sessions)))
    (append host locals)))

(defun cube-fleet--state (item)
  "Return the display state for a fleet ITEM."
  (if (cube-fleet--local-item-p item)
      (cube-session-state item)
    (intern (or (cube-get item 'state)
                (if (equal (cube-get item 'last_event) "stop") "idle" "running")))) )

(defun cube-fleet--value (item key)
  "Return KEY from fleet ITEM, including a local session struct."
  (if (cube-fleet--local-item-p item)
      (pcase key
        ('name (cube-session-name item))
        ('kind (cube-rolodex--kind-string (cube-session-kind item)))
        ('role (cube-session-role item))
        ('bead (cube-session-bead item))
        ('project (cube-session-project item))
        ('resume_id (cube-session-resume-id item))
        ('reason (cube-session-reason item))
        ('last_event_ts (cube-session-last-activity item))
        (_ nil))
    (pcase key
      ('name (cube-fleet--session-name item))
      (_ (cube-get item key)))))

(defun cube-fleet--resume-glyph (item)
  "Return the resume glyph for ITEM, or the empty string."
  (if (cube-fleet--value item 'resume_id) "↻" ""))

(defvar cube-fleet--row-map
  (let ((map (make-sparse-keymap)))
    (define-key map [mouse-1] #'cube-fleet-mouse-visit)
    (define-key map [mouse-3] #'cube-fleet-mouse-context)
    map)
  "Mouse map applied to fleet rows.")

(defvar cube-fleet-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'cube-fleet-visit)
    (define-key map (kbd "A") #'cube-fleet-adopt)
    (define-key map (kbd "k") #'cube-fleet-kill)
    (define-key map (kbd "r") #'cube-rolodex-list-remote)
    map)
  "Keymap of `cube-fleet-mode'.")

(defconst cube-fleet-mode-key-help
  '(("RET" . "open") ("A" . "adopt") ("k" . "kill") ("r" . "remote sessions"))
  "Key legend of `cube-fleet-mode', proved against its keymap by the tests.")

(cube-key-legend-register 'cube-fleet-mode)

(define-derived-mode cube-fleet-mode tabulated-list-mode "cube-fleet"
  "List of cockpit sessions."
  ;; The header line carries the key legend, so the column names are printed
  ;; into the buffer instead.
  (setq-local tabulated-list-use-header-line nil)
  (setq tabulated-list-format
        [("St" 3 t) ("Kind" 7 t) ("Name" 24 t) ("Role" 10 t) ("Bead" 10 t)
         ("Project" 18 t) ("↻" 2 nil) ("Age" 5 nil) ("Reason" 0 nil)])
  (setq tabulated-list-padding 1)
  (add-hook 'tabulated-list-revert-hook #'cube-fleet--refresh nil t)
  (tabulated-list-init-header)
  (setq-local header-line-format (cube-key-legend-header-line 'cube-fleet-mode)))

(defun cube-fleet--entry (item)
  "Return the tabulated-list entry for host or local fleet ITEM."
  (list item
        (vector (cube-rolodex--state-glyph (cube-fleet--state item))
                (cube--string (cube-fleet--value item 'kind))
                (cube--string (cube-fleet--value item 'name))
                (cube--string (cube-fleet--value item 'role))
                (cube--string (cube-fleet--value item 'bead))
                (cube--string (cube-fleet--value item 'project))
                (cube-fleet--resume-glyph item)
                (cube--age-string (cube-fleet--value item 'last_event_ts))
                (cube--string (cube-fleet--value item 'reason)))))

(defun cube-fleet--install-mouse-actions ()
  "Attach visit and context mouse actions to the rendered fleet rows."
  (let ((inhibit-read-only t))
    (save-excursion
      (goto-char (point-min))
      (while (not (eobp))
        (when (tabulated-list-get-id)
          (add-text-properties (line-beginning-position) (line-end-position)
                               (list 'mouse-face 'highlight 'keymap cube-fleet--row-map
                                     'help-echo "RET attaches; A adopts; mouse-3 shows actions")))
        (forward-line 1)))))

(defun cube-fleet--render ()
  "Render the local and cached remote fleet entries in the current buffer."
  (setq tabulated-list-entries (mapcar #'cube-fleet--entry (cube-fleet--items)))
  (tabulated-list-print nil)
  (cube-fleet--install-mouse-actions))

(defun cube-fleet--merge-session (record)
  "Merge adopted RECORD into the fleet cache and repaint any live fleet list."
  (let ((name (cube-fleet--session-name record)))
    (setq cube-fleet--cache
          (append (seq-remove (lambda (old)
                                (equal (cube-fleet--session-name old) name))
                              cube-fleet--cache)
                  (list record))))
  (when-let* ((buffer (get-buffer "*cube-fleet*")))
    (with-current-buffer buffer
      (when (derived-mode-p 'cube-fleet-mode) (cube-fleet--render)))))

(defun cube-fleet--fetch ()
  "Refresh `cube-fleet--cache' from `cube fleet --json'."
  (cube--call-json-async
   '("fleet")
   (lambda (json)
     (setq cube-fleet--cache (cube-get json 'sessions))
     (when-let* ((buffer (get-buffer "*cube-fleet*")))
       (with-current-buffer buffer
         (when (derived-mode-p 'cube-fleet-mode) (cube-fleet--render))))))
   (lambda (code err) (message "cube: fleet failed (%s): %s" code err)))

(defun cube-fleet--refresh ()
  "Recompute fleet entries and refresh the backend cache asynchronously."
  (cube-fleet--render)
  (cube-fleet--fetch))

(defun cube-fleet-visit ()
  "Visit the session at point."
  (interactive)
  (let ((session (tabulated-list-get-id)))
    (cond ((null session) (user-error "cube: no session at point"))
          ((and (cube-fleet--local-item-p session)
                (buffer-live-p (cube-session-buffer session)))
           (cube-rolodex--show (cube-session-buffer session)))
          (t (cube-rolodex-attach (cube-fleet--value session 'name) session)))))

(defun cube-fleet-adopt ()
  "Start the guarded adoption flow for the fleet session at point."
  (interactive)
  (let ((session
         (cond ((derived-mode-p 'cube-fleet-mode) (tabulated-list-get-id))
               ((cube-rolodex-session-for-buffer) (cube-rolodex-session-for-buffer))
               ((and (fboundp 'cube-dashboard--current-item)
                     (let ((item (cube-dashboard--current-item)))
                       (and (eq (plist-get item :type) 'session)
                            (plist-get item :data))))))))
    (if session
        (cube-rolodex-adopt session)
      (user-error "cube: no session at point"))))

(defun cube-fleet-kill ()
  "Kill the session at point."
  (interactive)
  (when-let* ((session (tabulated-list-get-id)))
    (unless (cube-fleet--local-item-p session)
      (user-error "cube: attach this remote session before closing its buffer"))
    (cube-rolodex-kill session)
    (revert-buffer)))

(defun cube-fleet--mouse-position (event)
  "Return (BUFFER POINT) described by mouse EVENT, or nil."
  (let* ((posn (event-end event)) (window (posn-window posn)) (point (posn-point posn)))
    (when (and (windowp window) (integer-or-marker-p point))
      (list (window-buffer window) point))))

(defun cube-fleet-mouse-visit (event)
  "Visit the fleet row clicked by mouse-1 EVENT."
  (interactive "e")
  (when-let* ((position (cube-fleet--mouse-position event)))
    (with-current-buffer (nth 0 position)
      (goto-char (nth 1 position))
      (cube-fleet-visit))))

(defun cube-fleet-mouse-context (event)
  "Show command-table session actions for the fleet row in EVENT."
  (interactive "e")
  (when-let* ((position (cube-fleet--mouse-position event)))
    (with-current-buffer (nth 0 position)
      (goto-char (nth 1 position))
      (when-let* ((items (cube-menu--context-items 'session))
                  (choice (popup-menu (cons "Session" items))))
        (call-interactively choice)))))

(defun cube-fleet-list ()
  "Show all sessions in the *cube-fleet* buffer."
  (interactive)
  (with-current-buffer (get-buffer-create "*cube-fleet*")
    (unless (derived-mode-p 'cube-fleet-mode) (cube-fleet-mode))
    (cube-fleet--render)
    (pop-to-buffer (current-buffer)))
  (cube-fleet--fetch))

(provide 'cube-rolodex)
;;; cube-rolodex.el ends here
