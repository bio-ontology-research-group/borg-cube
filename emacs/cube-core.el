;;; cube-core.el --- Settings and helpers shared by the borg-cube cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, processes
;; Package-Requires: ((emacs "29.1"))

;;; Commentary:

;; Shared layer of the borg-cube Emacs cockpit: the customization group,
;; user options, logging, the ssh wrapper, shell quoting, the JSON call
;; helpers and small formatting utilities.  Every other cube-*.el file
;; requires this one; `borg-cube' is the user-facing entry point that
;; requires all modules and defines the keymap.
;;
;; The cockpit is a thin client.  With `cube-remote-host' set (default
;; "ws") every backend call becomes `ssh HOST -- cube ... --json' and
;; interactive sessions run inside tmux on the host.  With the option set
;; to nil everything runs locally, which is what the tests use.

;;; Code:

(require 'cl-lib)
(require 'subr-x)
(require 'seq)
(require 'iso8601)

(declare-function cube-menu--item "cube-menu" (entry &optional prefix))
(declare-function cube-menu--global-menu "cube-menu" ())
(declare-function cube-mode-line-string "borg-cube" ())
(defvar cube-menu-bar)
(defvar cube-mode-map)

(defgroup borg-cube nil
  "Emacs cockpit for the borg-cube agent orchestration suite."
  :group 'tools
  :prefix "cube-")

(defcustom cube-remote-host "ws"
  "Host that runs the cube backend, or nil to run everything locally.
When non-nil every backend call is wrapped in ssh and interactive
sessions are tmux sessions on that host."
  :type '(choice (const :tag "Local" nil) (string :tag "ssh host"))
  :group 'borg-cube)

(defcustom cube-root "~/Public/software/borg-cube"
  "Path of the borg-cube checkout on the host that runs the backend.
In remote mode this is a path on `cube-remote-host' (tilde allowed and
expanded there); in local mode it is expanded locally."
  :type 'string
  :group 'borg-cube)

(defcustom cube-program "cube"
  "Name of the cube command line program."
  :type 'string
  :group 'borg-cube)

(defcustom cube-program-fallback '("uv" "run" "cube")
  "Command used in local mode when `cube-program' is not on `exec-path'.
It runs with `cube-root' as the working directory."
  :type '(repeat string)
  :group 'borg-cube)

(defcustom cube-call-timeout 30
  "Maximum seconds a non-interactive backend call may run.
The watchdog covers a wedged local process as well as ssh.  Remote ssh
also gets a shorter connection timeout from `cube--ssh-args'."
  :type 'number
  :group 'borg-cube)

(defcustom cube-terminal-backend 'auto
  "Terminal emulator used for agent sessions.
`auto' prefers eat and falls back to vterm."
  :type '(choice (const auto) (const eat) (const vterm))
  :group 'borg-cube)

(defcustom cube-prefix-key "C-c b"
  "Prefix key for `cube-command-map' in `cube-mode'.
Changing it takes effect the next time `cube-mode' is enabled."
  :type 'key-sequence
  :group 'borg-cube)

(defcustom cube-attention-count 3
  "How many attention items the header line and the dashboard show."
  :type 'natnum
  :group 'borg-cube)

(defcustom cube-refresh-interval 60
  "Seconds between polls of the backend attention list, or nil to disable."
  :type '(choice (const :tag "Never" nil) (natnum :tag "Seconds"))
  :group 'borg-cube)

(defcustom cube-notify-method 'auto
  "How desktop notifications are delivered.
`auto' uses notify-send when it exists and `message' otherwise."
  :type '(choice (const auto) (const notify-send) (const message)
                 (const :tag "Silent" nil))
  :group 'borg-cube)

(defcustom cube-idle-seconds 30
  "Seconds without terminal output after which a session counts as idle."
  :type 'natnum
  :group 'borg-cube)

(defcustom cube-claude-tui 'inherit
  "Claude Code TUI mode passed via --settings.
`inherit' leaves the user's own ~/.claude/settings.json in charge."
  :type '(choice (const inherit) (const inline) (const fullscreen))
  :group 'borg-cube)

(defcustom cube-tmux-session-prefix "cube/"
  "Prefix of tmux session names created on `cube-remote-host'."
  :type 'string
  :group 'borg-cube)

(defcustom cube-events-file "state/events.jsonl"
  "Event log written by `cube notify', relative to `cube-root'."
  :type 'string
  :group 'borg-cube)

(defcustom cube-log-buffer-name "*cube-log*"
  "Buffer that receives `cube-log' lines."
  :type 'string
  :group 'borg-cube)

(defcustom cube-debug nil
  "When non-nil, log every backend command line."
  :type 'boolean
  :group 'borg-cube)

(defcustom cube-kill-switch-active nil
  "Whether the backend kill switch is currently active.
The menu changes this value only after the backend confirms the change."
  :type 'boolean
  :group 'borg-cube)

(defcustom cube-show-key-legend t
  "When non-nil every cube buffer renders its key legend under its heading."
  :type 'boolean
  :group 'borg-cube)

(defcustom cube-key-legend-width 100
  "Column at which the key legend wraps onto its second line."
  :type 'integer
  :group 'borg-cube)

(define-error 'cube-error "borg-cube error")

;;;; Key legend

;; Every cockpit buffer shows its own keys.  The legend is generated from a
;; per-mode alist named `<major-mode>-key-help' of (KEY . LABEL) pairs, and the
;; contract test proves that alist against the mode keymap, so the printed
;; legend cannot drift away from the bindings.

(defvar cube-key-legend-modes nil
  "Cockpit major modes that render a key legend and answer `?'.")

(defconst cube-key-legend-navigation-commands
  '(quit-window cube-cockpit-restore cube-mode-keys cube-mode-help
    cube-attention-1 cube-attention-2 cube-attention-3
    magit-section-toggle magit-section-forward magit-section-backward
    magit-section-up magit-section-forward-sibling magit-section-backward-sibling
    magit-section-show-level-1 magit-section-show-level-2 magit-section-show-level-3
    magit-section-show-level-4 magit-section-cycle magit-section-cycle-global
    magit-section-cycle-diffs tabulated-list-sort tabulated-list-next-column
    tabulated-list-previous-column)
  "Commands a legend need not name: window, section and cursor navigation.")

(defun cube-key-legend-alist (&optional mode)
  "Return the (KEY . LABEL) legend alist of MODE, or nil when it has none."
  (let ((symbol (intern-soft (format "%s-key-help" (or mode major-mode)))))
    (and symbol (boundp symbol) (symbol-value symbol))))

(defun cube-key-legend-register (mode)
  "Record MODE as a cockpit mode with a key legend."
  (unless (memq mode cube-key-legend-modes)
    (setq cube-key-legend-modes (append cube-key-legend-modes (list mode))))
  mode)

(defconst cube--keymap-pseudo-events
  '(follow-link remap menu-bar tool-bar tab-bar header-line mode-line vertical-line
    switch-frame)
  "Keymap entries that are not keys a person can press.")

(defun cube--keymap-own-bindings (map)
  "Return (KEY-STRING . COMMAND) for bindings defined directly in MAP.
Bindings inherited from the parent keymap, mouse events and the pseudo
events in `cube--keymap-pseudo-events' are skipped."
  (let ((own nil)
        (parent (keymap-parent map))
        (tail (cdr map)))
    ;; A keymap with a parent is (keymap OWN... . PARENT): walk the own
    ;; bindings and stop the moment the tail becomes the parent keymap.
    (while (and (consp tail) (not (eq tail parent)))
      (let ((element (car tail)))
        (when (and (consp element) (not (eq (car-safe element) 'keymap)))
          (let ((event (car element))
                (command (cdr element)))
            (when (and (symbolp command)
                       (not (memq event cube--keymap-pseudo-events))
                       (not (and (symbolp event)
                                 (string-match-p "mouse\\|wheel\\|drag"
                                                 (symbol-name event)))))
              (push (cons (key-description (vector event)) command) own)))))
      (setq tail (cdr tail)))
    (nreverse own)))

(defun cube-key-legend-string (&optional mode)
  "Return the wrapped key legend text of MODE, or nil when it has none."
  (when-let* ((alist (cube-key-legend-alist mode)))
    (let ((lines nil)
          (current ""))
      (dolist (pair (append alist (list (cons "?" "all keys"))))
        (let ((cell (format "%s %s" (car pair) (cdr pair))))
          (cond ((string-empty-p current) (setq current cell))
                ((<= (+ (length current) 2 (length cell)) cube-key-legend-width)
                 (setq current (concat current "  " cell)))
                (t (push current lines) (setq current cell)))))
      (unless (string-empty-p current) (push current lines))
      (string-join (nreverse lines) "\n"))))

(defun cube-key-legend-insert (&optional mode)
  "Insert MODE's key legend at point when `cube-show-key-legend' is on."
  (when cube-show-key-legend
    (when-let* ((text (cube-key-legend-string mode)))
      (insert (propertize (concat text "\n") 'font-lock-face 'shadow)))))

(defun cube-key-legend-header-line (&optional mode)
  "Return MODE's legend as a header line, for the tabulated-list buffers."
  (when cube-show-key-legend
    (when-let* ((text (cube-key-legend-string mode)))
      (propertize (car (split-string text "\n")) 'face 'shadow))))


;;;; Logging

(defun cube-log (format-string &rest args)
  "Append a timestamped line built from FORMAT-STRING and ARGS to the log."
  (let ((line (apply #'format format-string args)))
    (with-current-buffer (get-buffer-create cube-log-buffer-name)
      (goto-char (point-max))
      (let ((inhibit-read-only t))
        (insert (format-time-string "%F %T ") line "\n")))
    line))

;;;; Paths

(defun cube-root-file (relative)
  "Return RELATIVE joined onto `cube-root' for the backend host.
In local mode the result is expanded; in remote mode a leading tilde is
kept so the remote shell expands it."
  (if cube-remote-host
      (concat (directory-file-name cube-root) "/" relative)
    (expand-file-name relative cube-root)))

(defun cube--local-directory ()
  "Return a local directory to run helper processes in.
Never a TRAMP path, so `make-process' always runs on this machine."
  (let ((root (expand-file-name cube-root)))
    (if (and (null cube-remote-host) (file-directory-p root))
        root
      (expand-file-name "~/"))))

(defun cube-remote-file-name (path)
  "Return PATH as a TRAMP file name on `cube-remote-host', or PATH locally."
  (if cube-remote-host
      (concat "/ssh:" cube-remote-host ":" path)
    (expand-file-name path)))

;;;; Shell quoting and ssh

(defun cube--shell-quote (arg)
  "Quote ARG for a POSIX shell like `shell-quote-argument'.
A leading \"~/\" (or \"~user/\") is left unquoted so the shell that
finally runs the command still expands it."
  (cond
   ((string-match "\\`\\(~[^/]*/\\)\\(.*\\)\\'" arg)
    (let ((prefix (match-string 1 arg))
          (rest (match-string 2 arg)))
      (if (string-empty-p rest)
          prefix
        (concat prefix (shell-quote-argument rest)))))
   ((string= arg "~") arg)
   (t (shell-quote-argument arg))))

(defun cube--shell-join (cmd-list)
  "Join CMD-LIST into one shell command string, quoting each word."
  (mapconcat #'cube--shell-quote cmd-list " "))

(defun cube--ssh-args (cmd-list &optional tty)
  "Wrap CMD-LIST for execution on `cube-remote-host'.
Return CMD-LIST unchanged in local mode.  In remote mode the result is
\(\"ssh\" ... HOST \"--\" COMMAND) where COMMAND is CMD-LIST joined with
`cube--shell-join' so the remote login shell parses it back into the
same words.  Every ssh invocation is non-interactive and has a five second
connection timeout.  With TTY non-nil request a pseudo terminal after the
host is known reachable; otherwise no pseudo terminal is allocated."
  (if (null cube-remote-host)
      cmd-list
    (when (and tty (cube--remote-unreachable-p))
      (user-error "cube: %s" (cube--remote-unreachable-message)))
    (append (list "ssh")
            (append (when tty '("-t"))
                    '("-o" "ConnectTimeout=5" "-o" "BatchMode=yes")
                    (cube--ssh-multiplex-options))
            (list cube-remote-host "--" (cube--shell-join cmd-list)))))

(defcustom cube-ssh-multiplex t
  "When non-nil every backend ssh call shares one master connection.
The dashboard refreshes a dozen sections at once; without multiplexing
each is a new TCP connection and sshd on the backend drops the ones above
its MaxStartups limit (`kex_exchange_identification: read: Connection
reset by peer').  With it, one authenticated connection carries them all
and stays open for `cube-ssh-control-persist'."
  :type 'boolean
  :group 'borg-cube)

(defcustom cube-ssh-control-persist "10m"
  "How long the shared ssh master connection stays open when idle."
  :type 'string
  :group 'borg-cube)

(defun cube--ssh-control-path ()
  "Return the control socket path for the shared ssh connection."
  (expand-file-name "cube-%C" (or (getenv "XDG_RUNTIME_DIR") temporary-file-directory)))

(defun cube--ssh-multiplex-options ()
  "Return the ssh options that share one master connection, or nil."
  (when cube-ssh-multiplex
    (list "-o" "ControlMaster=auto"
          "-o" (concat "ControlPath=" (cube--ssh-control-path))
          "-o" (concat "ControlPersist=" cube-ssh-control-persist))))

(defun cube--program-args ()
  "Return the argv prefix that invokes the cube program."
  (cond (cube-remote-host (list cube-program))
        ((executable-find cube-program) (list cube-program))
        (t cube-program-fallback)))

(defun cube--command (args &optional no-json)
  "Return the full local argv for backend call ARGS.
Appends --json unless NO-JSON or ARGS already contains it."
  ;; A cockpit doctor run must compare this checkout with the selected host,
  ;; so it deliberately runs the local CLI and lets its `--cockpit' check use
  ;; its own bounded ssh probe.  All ordinary backend calls stay on the
  ;; selected backend host.
  (if (and cube-remote-host (equal args '("doctor")))
      (let ((host cube-remote-host)
            (cube-remote-host nil))
        (append (cube--program-args) args
                (list "--cockpit" "--host" host)
                (unless no-json '("--json"))))
    (cube--ssh-args
     (append (cube--program-args) args
             (unless (or no-json (member "--json" args)) '("--json"))))))

;;;; JSON

(defun cube--parse-json-buffer ()
  "Parse the JSON document after point in the current buffer.
Objects become alists with symbol keys, arrays lists, null nil and
false the keyword `:false'."
  (json-parse-buffer :object-type 'alist :array-type 'list
                     :null-object nil :false-object :false))

(defun cube--parse-json-string (string)
  "Parse STRING as JSON with the same conventions as `cube--parse-json-buffer'."
  (with-temp-buffer
    (insert string)
    (goto-char (point-min))
    (cube--parse-json-buffer)))

(defun cube-get (object &rest keys)
  "Return the value under the path KEYS in the parsed JSON OBJECT.
KEYS are symbols for alist members or integers for list positions.
Missing keys yield nil; the cockpit must tolerate missing data."
  (let ((value object))
    (while (and keys value)
      (let ((key (pop keys)))
        (setq value (cond ((integerp key) (nth key value))
                          ((consp value) (alist-get key value))
                          (t nil)))))
    value))

(defun cube-true-p (value)
  "Return non-nil if VALUE is a JSON true-ish value (not nil, not :false)."
  (and value (not (eq value :false))))

;;;; Process helpers

(defun cube--process-output (proc)
  "Return the accumulated stdout of PROC as a string."
  (let ((buf (process-buffer proc)))
    (if (buffer-live-p buf)
        (with-current-buffer buf (buffer-string))
      "")))

(defun cube--stderr-string (proc)
  "Return what PROC wrote to its stderr buffer, if any."
  (let ((buf (process-get proc 'cube-stderr)))
    (if (buffer-live-p buf)
        (with-current-buffer buf (string-trim (buffer-string)))
      "")))

(defun cube--cleanup-process (proc)
  "Kill the stdout and stderr buffers of the finished PROC."
  (when-let* ((timer (process-get proc 'cube-timeout-timer)))
    (cancel-timer timer))
  (let ((out (process-buffer proc))
        (err (process-get proc 'cube-stderr)))
    (when (buffer-live-p err)
      (let ((errproc (get-buffer-process err)))
        (when errproc (delete-process errproc)))
      (kill-buffer err))
    (when (buffer-live-p out) (kill-buffer out))))

(defun cube--ssh-timeout-p (message)
  "Return non-nil if ssh MESSAGE is a connection failure."
  (string-match-p
   "\\(?:connection timed out\\|operation timed out\\|connection refused\\|no route to host\\|could not resolve hostname\\)"
   (downcase (or message ""))))

(defun cube--unknown-command-p (message)
  "Return non-nil if MESSAGE is argparse-style unknown-command output."
  (string-match-p
   "invalid choice\\|unknown command\\|unknown subcommand\\|unrecognized command"
   (downcase (or message ""))))

(defun cube--failure-message (args code stderr timed-out)
  "Return a stable human failure message for ARGS, CODE and STDERR.
TIMED-OUT is non-nil when the process watchdog terminated the call."
  (cond
   ((and cube-remote-host (or timed-out (cube--ssh-timeout-p stderr)))
    (cube--mark-remote-unreachable)
    "ssh: connection timed out")
   ((and args (cube--unknown-command-p stderr))
    (format "cube: unknown command %s" (or (car args) "?")))
   (timed-out (format "cube: timed out after %ss" cube-call-timeout))
   ((string-empty-p (string-trim (or stderr "")))
    (format "cube: exited %s" code))
   (t (string-trim stderr))))

(defun cube--timeout-process (proc)
  "Terminate PROC after `cube-call-timeout' seconds.
The sentinel owns callbacks and cleanup, so the timeout path cannot leave a
dashboard section in its pending state."
  (when (process-live-p proc)
    (process-put proc 'cube-timed-out t)
    (delete-process proc)))

(defun cube--call-async (command callback &optional error-callback)
  "Run local argv COMMAND and call CALLBACK with its stdout string.
On a non-zero exit call ERROR-CALLBACK with the exit code and stderr
text, or log the failure when ERROR-CALLBACK is nil.  Return the
process."
  (let* ((default-directory (cube--local-directory))
         (stdout (generate-new-buffer " *cube-out*" t))
         (stderr (generate-new-buffer " *cube-err*" t))
         (proc nil))
    (when cube-debug (cube-log "run: %s" (string-join command " ")))
    (cl-labels
        ((finish
          (process)
          (let* ((code (process-exit-status process))
                 (out (cube--process-output process))
                 (err (cube--stderr-string process))
                 (timed-out (process-get process 'cube-timed-out)))
            (cube--cleanup-process process)
            (if (and (zerop code) (not timed-out))
                (progn
                  (cube--mark-remote-reachable)
                  (funcall callback out))
              (let ((message (cube--failure-message nil code err timed-out)))
                (if error-callback
                    (funcall error-callback code message)
                  (progn
                    (cube-log "%s failed (%d): %s"
                              (string-join command " ") code message)
                    (message "cube: %s" message))))))))
      (condition-case err
          (progn
            (setq proc
                  (make-process
                   :name "cube" :buffer stdout :stderr stderr :command command
                   :noquery t :connection-type 'pipe
                   :sentinel
                   (lambda (process _event)
                     (when (memq (process-status process) '(exit signal))
                       (finish process)))))
            (process-put proc 'cube-stderr stderr)
            (process-put proc 'cube-timeout-timer
                         (run-at-time cube-call-timeout nil #'cube--timeout-process proc))
            proc)
        (error
         (let ((message (cube--failure-message nil -1 (error-message-string err) nil)))
           (if error-callback
               (funcall error-callback -1 message)
             (cube-log "%s could not start: %s" (string-join command " ") message))
           (when (buffer-live-p stdout) (kill-buffer stdout))
           (when (buffer-live-p stderr) (kill-buffer stderr))
           nil))))))

(defun cube--call-json-async (args callback &optional error-callback)
  "Run `cube ARGS --json' asynchronously and pass the parsed JSON to CALLBACK.
The command is wrapped for `cube-remote-host' when set.  ERROR-CALLBACK
receives the exit code and a message on failure, including a parse
failure; without it the failure is logged.  Return the process."
  (cube--call-async
   (cube--command args)
   (lambda (out)
     (condition-case err
         (funcall callback (cube--parse-json-string out))
       (error
        (let ((msg (format "bad JSON from cube %s: %s"
                           (string-join args " ") (error-message-string err))))
          (if error-callback (funcall error-callback -1 msg) (cube-log "%s" msg))))))
   (lambda (code message)
     (let ((failure (cube--failure-message args code message nil)))
       (if error-callback
           (funcall error-callback code failure)
         (progn
           (cube-log "%s" failure)
           (message "cube: %s" failure)))))))

(defun cube--call-json-async-on (host args callback &optional error-callback)
  "Run `cube ARGS --json' on explicit HOST, passing JSON to CALLBACK.
HOST is an ssh host name, or nil for this machine.  This is intentionally
separate from `cube-remote-host': a standing agent may live on the laptop
while the dashboard's ordinary backend remains on ws."
  (let ((cube-remote-host host))
    (cube--call-json-async args callback error-callback)))

(defun cube--call-text-async (args callback &optional error-callback)
  "Run ARGS (a full argv on the backend host) and pass stdout to CALLBACK.
Unlike `cube--call-json-async' ARGS is not prefixed with the cube
program and no --json is appended.  ERROR-CALLBACK as in `cube--call-async'."
  (cube--call-async (cube--ssh-args args) callback error-callback))

(defun cube--call-sync (command &optional args)
  "Run COMMAND through the bounded async transport and return its stdout.
ARGS names the cube command for stable error rendering.  Synchronous callers
are limited to completion helpers, but they must not bypass the watchdog."
  (let ((result 'cube--pending)
        (failure nil))
    (cube--call-async
     command
     (lambda (out) (setq result out))
     (lambda (code message)
       (setq failure (list code (cube--failure-message args code message nil)))))
    (while (and (eq result 'cube--pending) (null failure))
      (accept-process-output nil 0.05))
    (if failure
        (signal 'cube-error
                (list (format "%s exited %s" (string-join (or args command) " ")
                              (car failure))
                      (cadr failure)))
      result)))

(defun cube--call-text (args)
  "Run ARGS (a full argv on the backend host) synchronously, return stdout.
ARGS is wrapped in ssh in remote mode.  Signal `cube-error' with the
exit code and stderr text on failure."
  (cube--call-sync (cube--ssh-args args) args))

(defun cube--call-json (args)
  "Run `cube ARGS --json' synchronously and return the parsed JSON.
Signal `cube-error' on a non-zero exit.  Meant for tests and one-off
interactive use; everything in the UI should use the async variant."
  (cube--parse-json-string (cube--call-sync (cube--command args) args)))

;;;; Host files

(defun cube-host-file-name (path)
  "Return PATH on the backend host as a file name Emacs can open.
Relative paths are joined onto `cube-root'; in remote mode the result
is a TRAMP name on `cube-remote-host'."
  (let ((full (if (or (file-name-absolute-p path) (string-prefix-p "~" path))
                  path
                (cube-root-file path))))
    (if cube-remote-host
        (if (file-remote-p full) full (cube-remote-file-name full))
      (expand-file-name full))))

(defun cube-host-file-contents (path)
  "Return the contents of PATH on the backend host, or nil when unreadable."
  (let ((file (cube-host-file-name path)))
    (when (ignore-errors (file-readable-p file))
      (with-temp-buffer
        (insert-file-contents file)
        (buffer-string)))))

(defun cube-host-write-file (path text)
  "Write TEXT to PATH on the backend host and return the file name used."
  (let ((file (cube-host-file-name path)))
    (make-directory (file-name-directory file) t)
    (with-temp-file file (insert text))
    file))

;;;; Attention cache

(defvar cube--attention-items nil
  "Attention items from the last `cube attention' poll, loudest first.")

(defvar cube--attention-generated nil
  "Timestamp string of the last successful attention poll.")

(defvar cube-attention-update-hook nil
  "Hook run after the cached attention items changed.")

(defvar cube--status-json nil
  "The most recent parsed `cube status' payload.")

(defvar cube--doctor-json nil
  "The most recent parsed `cube doctor' payload.")

(defvar cube--remote-unreachable-since nil
  "Time at which the current remote host first became unreachable.")

(defvar cube--remote-unreachable-host nil
  "Host associated with `cube--remote-unreachable-since'.")

(defvar cube--host-commands nil
  "Top-level command names advertised by the most recent host status.
Nil means that the host has not advertised command capabilities, as older
backends did not include them in the status payload.")

(defvar cube--toggle-remote-host nil
  "Remote host restored by `cube-toggle-remote' after local mode.")

(defconst cube--backend-command-specs
  `(("adopt" cube-rolodex-adopt cube-session-adopt cube-fleet-adopt)
    ("agent" cube-agent-talk cube-agent-tell cube-agent-new cube-agent-workday
     cube-agent-report cube-agent-pause-resume cube-agent-revert cube-agent-visit
     cube-agent-approve cube-agent-inbox)
    ("work" cube-dashboard cube-dashboard-agent-inbox cube-dashboard-workday)
    ("approvals" cube-review-queue cube-review-refresh cube-review-show-body)
    (,(concat "appro" "ve") cube-review-approve cube-dashboard-approve cube-agent-approve)
    ("assign" cube-beads-assign cube-dashboard-assign cube-project-assign)
    ("beads" cube-beads-show cube-beads-list-show)
    ("brief" cube-brief)
    ("budget" cube-budget)
    ("create" cube-beads-create cube-beads-from-heading)
    ("doctor" cube-doctor)
    ("fleet" cube-fleet-list cube-fleet-visit)
    ("goal" cube-goal-new cube-goal-decompose cube-goal-spin-agent cube-goal-revert
     cube-goal-edit cube-goal-visit cube-goal-run-agent cube-goal-add-to-agenda)
    ("goals" cube-goals)
    ("incidents" cube-dashboard)
    ("org" cube-org-edit cube-org-meeting-note cube-org-pull-notes cube-papers
     cube-org-papers-sync cube-student-dossier cube-dashboard-meeting-note
     cube-dashboard-student-dossier)
    ("papers" cube-papers)
    ("people" cube-people cube-people-refresh cube-people-visit cube-people-open-org)
    ("pipeline" cube-pipeline-new cube-pipeline-list cube-pipeline-show cube-pipeline-advance
     cube-pipeline-advance-dry-run cube-pipeline-rehearse)
    ("projects" cube-project-list cube-project-revert)
    ("ready" cube-beads-ready cube-beads-list cube-beads--refresh cube-run-role)
    ("reject" cube-review-reject cube-dashboard-reject)
    ("repos" cube-dashboard)
    ("roster" cube-roster cube-roster-refresh cube-roster-sync-dry-run
     cube-roster-sync-apply)
    ("run" cube-run-role cube-beads-list-run cube-goal-run-agent)
    ("runs" cube-dashboard)
    ("status" cube-dashboard cube-fleet-list)
    ("student" cube-student-session cube-student-dossier cube-dashboard-student-session
     cube-dashboard-student-dossier)
    ("tier" cube-tier-menu))
  "Backend command to cockpit command-table symbols.
This is the one source for command-capability checks.  It is filtered through
`cube-command-table' once that table is available, so experimental UI commands
do not make an older host appear incompatible.")

(defvar cube--required-commands nil
  "Backend command names used by the loaded cockpit command table.")

(defun cube--refresh-required-commands ()
  "Generate `cube--required-commands' from `cube-command-table' when loaded."
  (let ((ui (and (boundp 'cube-command-table)
                 (mapcar (lambda (entry) (plist-get entry :command)) cube-command-table))))
    (setq cube--required-commands
          (mapcar #'car
                  (seq-filter
                   (lambda (spec)
                     (or (null ui)
                         (seq-some (lambda (command) (memq command (cdr spec))) ui)))
                   cube--backend-command-specs))))
  cube--required-commands)

(cube--refresh-required-commands)

(defun cube--remote-unreachable-p ()
  "Return non-nil while the configured remote host is known unreachable."
  (and cube-remote-host cube--remote-unreachable-since
       (equal cube-remote-host cube--remote-unreachable-host)))

(defun cube--remote-unreachable-message ()
  "Return the actionable current remote failure message, or nil."
  (when (cube--remote-unreachable-p)
    (format "%s unreachable since %s (ssh timeout). M-x cube-toggle-remote for local mode"
            cube-remote-host
            (format-time-string "%H:%M" cube--remote-unreachable-since))))

(defun cube--mark-remote-unreachable ()
  "Remember that the selected remote host did not answer ssh."
  (when cube-remote-host
    (unless (and cube--remote-unreachable-since
                 (equal cube--remote-unreachable-host cube-remote-host))
      (setq cube--remote-unreachable-since (current-time)
            cube--remote-unreachable-host cube-remote-host))
    (force-mode-line-update t)))

(defun cube--mark-remote-reachable ()
  "Clear stale remote failure state after a successful remote call."
  (when (and cube-remote-host
             (equal cube-remote-host cube--remote-unreachable-host))
    (setq cube--remote-unreachable-since nil
          cube--remote-unreachable-host nil)
    (force-mode-line-update t)))

(defun cube--host-lacks (commands)
  "Return COMMANDS not advertised by the current remote host.
An old host that omits capability information is treated as unknown rather
than incompatible, preserving compatibility until a concrete command failure."
  (when (and cube-remote-host cube--host-commands)
    (seq-filter (lambda (command) (not (member command cube--host-commands))) commands)))

(defun cube--missing-commands-for-ui (command)
  "Return backend commands missing for cockpit UI COMMAND."
  (cube--host-lacks
   (delq nil
         (mapcar (lambda (spec)
                   (and (memq command (cdr spec)) (car spec)))
                 cube--backend-command-specs))))

(defun cube--status-missing-commands (json)
  "Return required commands absent from status JSON's advertised capabilities."
  (let ((commands (cube-get json 'version 'commands)))
    (when commands
      (seq-filter (lambda (command) (not (member command commands)))
                  cube--required-commands))))

(defun cube-toggle-remote ()
  "Toggle the backend host for this session and refresh the cockpit.
The configured remote is remembered when changing to local mode.  This never
writes Custom settings, so a recovery choice is confined to the session."
  (interactive)
  (if cube-remote-host
      (setq cube--toggle-remote-host cube-remote-host
            cube-remote-host nil)
    (setq cube-remote-host
          (or cube--toggle-remote-host (default-value 'cube-remote-host) "ws")))
  (setq cube--remote-unreachable-since nil
        cube--remote-unreachable-host nil
        cube--host-commands nil)
  (force-mode-line-update t)
  (message "cube: backend mode is %s" (or cube-remote-host "local"))
  (if (and (get-buffer "*cube*") (fboundp 'cube-dashboard-refresh))
      (cube-dashboard-refresh)
    (when (fboundp 'cube-refresh) (cube-refresh))))

(defun cube-status-set-json (json)
  "Cache parsed STATUS JSON and refresh the mode line.
The dashboard owns fetching status, but the mode line also needs the
incident banner when the dashboard is not the selected buffer."
  (setq cube--status-json json
        cube--host-commands (and cube-remote-host (cube-get json 'version 'commands)))
  (cube--refresh-capability-menu)
  (force-mode-line-update t)
  json)

(defun cube-status-banner ()
  "Return the current incident banner, or nil."
  (cube-get cube--status-json 'incidents 'banner))

(defun cube-doctor-set-json (json)
  "Cache parsed doctor JSON so menus can show local service state."
  (setq cube--doctor-json json)
  json)

(defun cube-laptop-worker-timer-installed-p (&optional doctor)
  "Return non-nil when DOCTOR reports the laptop worker timer installed."
  (seq-some
   (lambda (check)
     (and (member (cube--string (cube-get check 'name))
                  '("cube-worker-laptop.timer" "laptop-worker-timer"))
          (cube-true-p (cube-get check 'ok))))
   (cube-get (or doctor cube--doctor-json) 'checks)))

(defun cube-attention-set-items (json)
  "Cache the items of the parsed `cube attention' payload JSON."
  (setq cube--attention-items (cube-get json 'items)
        cube--attention-generated (or (cube-get json 'generated)
                                      (format-time-string "%FT%T%z")))
  (force-mode-line-update t)
  (run-hooks 'cube-attention-update-hook)
  cube--attention-items)

;;;; Formatting

(defun cube--string (value)
  "Return VALUE as a string; nil and :false become the empty string."
  (cond ((null value) "")
        ((eq value :false) "")
        ((stringp value) value)
        ((symbolp value) (symbol-name value))
        (t (format "%s" value))))

(defun cube--age-string (iso-or-seconds &optional now)
  "Return a compact age like \"5m\" or \"2d\" for ISO-OR-SECONDS.
The argument is an ISO 8601 timestamp string, a number of seconds, a
Lisp time value (as from `current-time'), or nil (returns \"\").  NOW
defaults to the current time."
  (let ((seconds
         (cond ((null iso-or-seconds) nil)
               ((numberp iso-or-seconds) iso-or-seconds)
               ((consp iso-or-seconds)
                (float-time (time-subtract (or now (current-time)) iso-or-seconds)))
               ((and (stringp iso-or-seconds)
                     (not (string-empty-p iso-or-seconds)))
                (condition-case nil
                    (float-time
                     (time-subtract (or now (current-time))
                                    (encode-time
                                     (iso8601-parse iso-or-seconds))))
                  (error nil)))
               (t nil))))
    (cond ((null seconds) "")
          ((< seconds 60) (format "%ds" (max 0 (truncate seconds))))
          ((< seconds 3600) (format "%dm" (truncate (/ seconds 60))))
          ((< seconds 86400) (format "%dh" (truncate (/ seconds 3600))))
          ((< seconds (* 14 86400)) (format "%dd" (truncate (/ seconds 86400))))
          (t (format "%dw" (truncate (/ seconds (* 7 86400))))))))

(defun cube--notify-desktop (title body &optional urgency)
  "Show a desktop notification with TITLE and BODY.
URGENCY is one of `low', `normal' or `critical' (default `normal').
Honours `cube-notify-method'."
  (let ((method (if (eq cube-notify-method 'auto)
                    (if (executable-find "notify-send") 'notify-send 'message)
                  cube-notify-method))
        (body (or body "")))
    (pcase method
      ('notify-send
       (let ((default-directory (expand-file-name "~/")))
         (ignore-errors
           (start-process "cube-notify-send" nil "notify-send"
                          "-a" "borg-cube"
                          "-u" (symbol-name (or urgency 'normal))
                          title body))))
      ('message (message "cube: %s%s" title
                         (if (string-empty-p body) "" (concat " - " body))))
      (_ nil))))

;;;; UI integration loaded after the entry point and menu

(defun cube--mode-line-host-state (original &rest args)
  "Prefix ORIGINAL mode-line text with the remote outage indicator when needed."
  (let ((text (apply original args)))
    (if (cube--remote-unreachable-p)
        (concat (propertize (format "⊘%s" cube-remote-host) 'face 'error)
                (if (string-empty-p text) "" " ") text)
      text)))

(defun cube--menu-item-host-capability (original entry &optional prefix)
  "Disable menu ENTRY when its remote backend command is unavailable."
  (let* ((item (funcall original entry prefix))
         (missing (cube--missing-commands-for-ui (plist-get entry :command))))
    (if (null missing)
        item
      (let ((at (cl-position :enable (append item nil))))
        (if at
            (aset item (1+ at) nil)
          (setq item (vconcat item (list :enable nil))))
        (aset item 0 (format "%s [host lacks: %s]"
                             (aref item 0) (string-join missing ", ")))
        item))))

(defun cube--refresh-capability-menu ()
  "Rebuild the static menu bar after host capabilities change.
`cube-menu-bar' is materialised when cube-menu loads, so the advice on
`cube-menu--item' must be applied again once status has advertised the host's
command set.  Easy-menu renders items with a nil `:enable' in its disabled
face."
  (when (and (fboundp 'cube-menu--global-menu) (boundp 'cube-mode-map))
    (easy-menu-define cube-menu-bar cube-mode-map
      "The top-level Cube menu for the global cockpit mode."
      (cube-menu--global-menu))))

(with-eval-after-load 'cube-menu
  (cube--refresh-required-commands)
  (unless (advice-member-p #'cube--menu-item-host-capability #'cube-menu--item)
    (advice-add #'cube-menu--item :around #'cube--menu-item-host-capability)))

(with-eval-after-load 'borg-cube
  (unless (advice-member-p #'cube--mode-line-host-state #'cube-mode-line-string)
    (advice-add #'cube-mode-line-string :around #'cube--mode-line-host-state)))

(provide 'cube-core)
;;; cube-core.el ends here
