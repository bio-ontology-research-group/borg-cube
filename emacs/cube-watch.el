;;; cube-watch.el --- Watch one task being solved  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf
;; Author: Robert Hoehndorf
;; Keywords: tools, processes

;;; Commentary:

;; One buffer per task: the bead (title, labels, acceptance, provenance),
;; its current run (runner, model, state, elapsed), the live trail of
;; events the run emits (start, every tool call, stop, finished, review,
;; attention), and the result (summary, run directory, artifacts, next
;; step).  `cube-watch' opens it for an existing bead; `cube-watch-new'
;; creates the bead first (dry-run, confirm, apply) and then opens it.
;; From the buffer: `p' shows the assembled prompt, `s' starts the run
;; attached in tmux, `a' jumps to that session, `o' opens the run
;; directory, `r' previews the review gate, `A' opens approvals.
;;
;; The trail comes from `cube tail --bead ID --json' (backlog) and from
;; `cube-notify-hook' (live).  Tool calls are the `tool' events a Claude
;; run reports through its hooks (ADR-0036).  Hermes runs report start,
;; stop and finished only.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'magit-section)
(require 'cube-core)
(require 'cube-server)
(require 'cube-rolodex)
(require 'cube-beads)

(declare-function cube-review "cube-review")

(defgroup cube-watch nil
  "Watch one task being solved from the cockpit."
  :group 'borg-cube)

(defcustom cube-watch-trail-limit 200
  "How many past events `cube tail' loads when a watch buffer opens."
  :type 'integer
  :group 'cube-watch)

(defcustom cube-watch-refresh-delay 2
  "Seconds between a state-changing event and the buffer refetch."
  :type 'number
  :group 'cube-watch)

(defvar-local cube-watch--bead nil "Bead id shown in this buffer.")
(defvar-local cube-watch--bead-json nil "The bead alist, from `cube bead-show'.")
(defvar-local cube-watch--run nil "Run id being watched, or nil.")
(defvar-local cube-watch--run-json nil "The run alist, from `cube run-show'.")
(defvar-local cube-watch--trail nil "Trail entries, oldest first.")
(defvar-local cube-watch--refresh-timer nil "Pending debounced refresh.")
(defvar-local cube-watch--loading nil "Non-nil while the first fetch runs.")

;;;; Pure helpers

(defun cube-watch--buffer-name (bead)
  "Return the watch buffer name for BEAD."
  (format "*cube:watch:%s*" bead))

(defun cube-watch--labels (bead)
  "Return the label strings of the BEAD alist."
  (seq-filter #'stringp (append (cube-get bead 'labels) nil)))

(defun cube-watch--role (bead)
  "Return the role that works BEAD: its role: label, else nil."
  (cube-beads--label-value (cube-watch--labels bead) "role"))

(defun cube-watch--label-values (bead prefix)
  "Return every value of PREFIX: labels on BEAD."
  (let ((pre (concat prefix ":")))
    (delq nil (mapcar (lambda (l) (and (string-prefix-p pre l) (substring l (length pre))))
                      (cube-watch--labels bead)))))

(defun cube-watch--session-name (role bead)
  "Return the rolodex name of the attached run session for ROLE on BEAD."
  (format "%s-%s" role bead))

(defun cube-watch--event-relevant-p (bead run session plist)
  "Return non-nil when an event for SESSION with PLIST concerns BEAD or RUN."
  (let ((event-bead (plist-get plist :bead))
        (event-run (plist-get plist :run-id)))
    (or (and bead event-bead (string= event-bead bead))
        (and run event-run (string= event-run run))
        (and run session (string= session (concat "run-" run))))))

(defun cube-watch--entry (session event title plist)
  "Return a trail entry plist for EVENT TITLE of SESSION with PLIST."
  (list :ts (plist-get plist :ts)
        :seq (plist-get plist :seq)
        :event (if (symbolp event) (symbol-name event) (downcase (or event "")))
        :title (or title "")
        :session session
        :run-id (plist-get plist :run-id)
        :bead (plist-get plist :bead)
        :severity (plist-get plist :severity)
        :tool (cube-get (plist-get plist :data) 'tool)
        :phase (cube-get (plist-get plist :data) 'phase)))

(defun cube-watch--entry-from-line (event)
  "Return a trail entry for the parsed events.jsonl object EVENT."
  (cube-watch--entry (or (cube-get event 'session) (cube-get event 'run_id) "cube")
                     (or (cube-get event 'event) "notification")
                     (cube-get event 'title)
                     (cube-server--event-plist event)))

(defconst cube-watch--glyphs
  '(("start" . "▶") ("prompt" . "›") ("tool" . "·") ("stop" . "■")
    ("finished" . "✓") ("checkpoint" . "◐") ("error" . "✖") ("attention" . "⚠")
    ("approval" . "⚑") ("queued" . "…") ("notification" . "!") ("end" . "†"))
  "One glyph per event kind for the trail.")

(defun cube-watch--clock (ts)
  "Return HH:MM:SS of the ISO timestamp TS, or blanks."
  (if (and (stringp ts) (>= (length ts) 19))
      (substring ts 11 19)
    "        "))

(defun cube-watch--trail-line (entry)
  "Return one trail line for ENTRY."
  (let* ((event (plist-get entry :event))
         (glyph (or (cdr (assoc event cube-watch--glyphs)) "?"))
         (title (plist-get entry :title))
         (face (pcase event
                 ("error" 'error) ("attention" 'warning) ("approval" 'warning)
                 ("finished" 'success) ("tool" 'shadow) (_ 'default))))
    (propertize (format "%s %s %-10s %s" (cube-watch--clock (plist-get entry :ts))
                        glyph event
                        (if (and (string= event "tool") (equal (plist-get entry :phase) "post"))
                            (concat "done: " title)
                          title))
                'face face)))

(defun cube-watch--append-entry (trail entry)
  "Return TRAIL with ENTRY appended unless its seq is already present."
  (let ((seq (plist-get entry :seq)))
    (if (and seq (seq-some (lambda (e) (equal (plist-get e :seq) seq)) trail))
        trail
      (append trail (list entry)))))

(defun cube-watch--state-changing-p (event)
  "Return non-nil when EVENT means the bead or run record changed."
  (member event '("start" "stop" "finished" "checkpoint" "error" "attention"
                  "approval" "queued" "end")))

(defun cube-watch--runs-for-bead (bead status)
  "Return the runs in STATUS (`cube status') that work BEAD, newest first."
  (sort (seq-filter (lambda (run) (equal (cube-get run 'bead) bead))
                    (append (cube-get status 'runs) nil))
        (lambda (a b) (string> (cube--string (cube-get a 'started))
                               (cube--string (cube-get b 'started))))))

(defun cube-watch--latest-run-id (bead status trail)
  "Return the newest run id for BEAD from STATUS, else from the TRAIL."
  (or (cube-get (car (cube-watch--runs-for-bead bead status)) 'run_id)
      (let ((with-run (seq-filter (lambda (e) (plist-get e :run-id)) trail)))
        (plist-get (car (last with-run)) :run-id))))

(defun cube-watch--elapsed (run &optional now)
  "Return the elapsed time of RUN as a string, relative to NOW."
  (let ((started (cube-get run 'started))
        (finished (cube-get run 'finished)))
    (cond ((not started) "-")
          (finished (cube--age-string
                     (- (float-time (date-to-time finished))
                        (float-time (date-to-time started)))))
          (t (cube--age-string started now)))))

(defun cube-watch--create-args (plist)
  "Return `cube create' ARGS (dry-run) for PLIST plus its :labels."
  (let ((args (cube-beads--cube-create-args plist)))
    (dolist (label (plist-get plist :labels))
      (when (and (stringp label) (not (string-empty-p label)))
        (setq args (append args (list "--label" label)))))
    args))

(defun cube-watch--acceptance-lines (bead)
  "Return the acceptance lines recorded on BEAD."
  (let ((acceptance (or (cube-get bead 'acceptance_criteria) (cube-get bead 'acceptance))))
    (cond ((stringp acceptance) (split-string acceptance "\n" t))
          ((listp acceptance) (mapcar #'cube--string acceptance))
          (t nil))))

(defun cube-watch--header-lines (bead)
  "Return the description lines between the YAML markers of BEAD."
  (let* ((text (cube--string (cube-get bead 'description)))
         (lines (split-string text "\n"))
         (in nil) (out nil))
    (dolist (line lines)
      (cond ((string= (string-trim line) "---") (if in (setq in 'done) (unless (eq in 'done) (setq in t))))
            ((eq in t) (push line out))))
    (nreverse out)))

(defun cube-watch--render-text (bead run trail &optional now)
  "Return the plain text of the watch view for BEAD, RUN and TRAIL.
Pure: the buffer rendering wraps these lines in sections."
  (with-temp-buffer
    (insert (format "Task %s: %s\n" (cube--string (cube-get bead 'id))
                    (cube--string (cube-get bead 'title))))
    (insert (format "  status %s  labels %s\n"
                    (cube--string (cube-get bead 'status))
                    (string-join (cube-watch--labels bead) " ")))
    (dolist (line (cube-watch--header-lines bead))
      (insert "  " line "\n"))
    (let ((acceptance (cube-watch--acceptance-lines bead)))
      (insert "  acceptance:\n")
      (if acceptance
          (dolist (line acceptance) (insert "   - " line "\n"))
        (insert "   - none recorded\n")))
    (insert "\nRun\n")
    (if run
        (insert (format "  %s  %s/%s  %s  %s\n" (cube--string (cube-get run 'run_id))
                        (cube--string (cube-get run 'runner)) (cube--string (cube-get run 'model))
                        (cube--string (cube-get run 'state)) (cube-watch--elapsed run now)))
      (insert "  no run yet: press s to start the role on this bead\n"))
    (insert (format "\nTrail (%d)\n" (length trail)))
    (dolist (entry trail) (insert "  " (cube-watch--trail-line entry) "\n"))
    (insert "\nResult\n")
    (if-let* ((summary (cube-get run 'summary)))
        (insert "  " summary "\n")
      (insert "  none yet\n"))
    (buffer-string)))

;;;; Buffer

(defvar cube-watch-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "g") #'cube-watch-refresh)
    (define-key map (kbd "p") #'cube-watch-show-prompt)
    (define-key map (kbd "s") #'cube-watch-start)
    (define-key map (kbd "S") #'cube-watch-resume)
    (define-key map (kbd "a") #'cube-watch-attach)
    (define-key map (kbd "o") #'cube-watch-open-run)
    (define-key map (kbd "O") #'cube-watch-open-artifact)
    (define-key map (kbd "l") #'cube-watch-open-bead)
    (define-key map (kbd "r") #'cube-watch-review)
    (define-key map (kbd "A") #'cube-watch-approvals)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap for `cube-watch-mode'.")

(defconst cube-watch-mode-key-help
  '(("g" . "refresh") ("p" . "prompt") ("s" . "start run") ("S" . "resume")
    ("a" . "attach session") ("o" . "run dir") ("O" . "artifact") ("l" . "bead")
    ("r" . "review gate") ("A" . "approvals"))
  "Key legend of `cube-watch-mode', proved against its keymap by the tests.")

(cube-key-legend-register 'cube-watch-mode)

(define-derived-mode cube-watch-mode magit-section-mode "cube-watch"
  "Watch one task: bead, run, live trail and result."
  (setq-local revert-buffer-function (lambda (&rest _) (cube-watch-refresh))))

(defun cube-watch--buffers ()
  "Return the live watch buffers."
  (seq-filter (lambda (b) (with-current-buffer b (derived-mode-p 'cube-watch-mode)))
              (buffer-list)))

(defun cube-watch--insert-section (type heading lines)
  "Insert a section of TYPE with HEADING and LINES."
  (magit-insert-section (cube-watch-section type)
    (magit-insert-heading heading)
    (dolist (line lines) (insert "  " line "\n"))
    (insert "\n")))

(defun cube-watch--render ()
  "Render the current watch buffer from its local state."
  (let ((inhibit-read-only t)
        (bead cube-watch--bead-json)
        (run cube-watch--run-json)
        (trail cube-watch--trail)
        (point (point)))
    (erase-buffer)
    (magit-insert-section (cube-watch-root)
      (cube-watch--insert-section
       'task
       (format "Task %s: %s" (cube--string (or (cube-get bead 'id) cube-watch--bead))
               (cube--string (cube-get bead 'title)))
       (append
        (list (format "status %s   labels %s" (cube--string (cube-get bead 'status))
                      (string-join (cube-watch--labels bead) " ")))
        (cube-watch--header-lines bead)
        (list "acceptance:")
        (or (mapcar (lambda (l) (concat " - " l)) (cube-watch--acceptance-lines bead))
            (list " - none recorded"))))
      (cube-watch--insert-section
       'run
       (if run
           (format "Run %s: %s/%s  %s  %s" (cube--string (cube-get run 'run_id))
                   (cube--string (cube-get run 'runner)) (cube--string (cube-get run 'model))
                   (cube--string (cube-get run 'state)) (cube-watch--elapsed run))
         (if cube-watch--run (format "Run %s: loading" cube-watch--run)
           "Run: none yet"))
       (cond (run (list (format "log %s" (cube--string (cube-get run 'log)))
                        (format "session cube/run-%s-%s"
                                (or (cube-watch--role bead) (cube-get run 'role) "?")
                                cube-watch--bead)))
             (t (list "s starts the role on this bead attached in tmux; p shows the prompt first"))))
      (cube-watch--insert-section
       'trail (format "Trail (%d events)" (length trail))
       (or (mapcar #'cube-watch--trail-line trail)
           (list (if cube-watch--loading "loading" "nothing yet"))))
      (cube-watch--insert-section
       'result "Result"
       (let ((summary (cube-get run 'summary))
             (notes (cube-get run 'notes)))
         (append (if summary (split-string summary "\n" t) (list "none yet"))
                 (when notes (cons "" (seq-take (split-string notes "\n") 12)))
                 (when (and run (member (cube-get run 'state) '("finished" "checkpoint")))
                   (list "" "o opens the run directory, O the audit report, r previews the review gate")))))
      (cube-watch--insert-section
       'keys "Keys"
       (list "g refresh  p prompt  s start  S resume  a attach  o run dir  O artifact"
             "l bead  r review  A approvals  q quit")))
    (goto-char (min point (point-max)))))

(defun cube-watch--set-run (run-id)
  "Fetch RUN-ID and render when it arrives."
  (setq cube-watch--run run-id)
  (when run-id
    (let ((buffer (current-buffer)))
      (cube--call-json-async
       (list "run-show" run-id)
       (lambda (json)
         (when (buffer-live-p buffer)
           (with-current-buffer buffer
             (setq cube-watch--run-json json)
             (cube-watch--render))))
       (lambda (_code err) (cube-log "watch: run-show %s: %s" run-id err))))))

(defun cube-watch--load-trail (bead)
  "Load the event backlog for BEAD and render."
  (let ((buffer (current-buffer)))
    (cube--call-async
     (cube--command (list "tail" "--bead" bead "--limit" (number-to-string cube-watch-trail-limit)))
     (lambda (out)
       (when (buffer-live-p buffer)
         (with-current-buffer buffer
           (dolist (line (split-string out "\n" t))
             (condition-case nil
                 (setq cube-watch--trail
                       (cube-watch--append-entry
                        cube-watch--trail
                        (cube-watch--entry-from-line (cube--parse-json-string line))))
               (error nil)))
           (setq cube-watch--loading nil)
           (unless cube-watch--run
             (cube-watch--set-run (cube-watch--latest-run-id bead cube--status-json cube-watch--trail)))
           (cube-watch--render))))
     (lambda (_code err) (cube-log "watch: tail %s: %s" bead err)))))

(defun cube-watch-refresh ()
  "Refetch the bead, its newest run and the event backlog."
  (interactive)
  (unless cube-watch--bead (user-error "cube: not a watch buffer"))
  (let ((buffer (current-buffer)) (bead cube-watch--bead))
    (setq cube-watch--loading t)
    (cube-beads--fetch-bead
     bead
     (lambda (json)
       (when (buffer-live-p buffer)
         (with-current-buffer buffer
           (setq cube-watch--bead-json json)
           (cube-watch--render))))
     (lambda (_code err) (message "cube: bead %s: %s" bead err)))
    (cube--call-json-async
     (list "status")
     (lambda (json)
       (when (buffer-live-p buffer)
         (with-current-buffer buffer
           (cube-status-set-json json)
           (when-let* ((run-id (cube-watch--latest-run-id bead json cube-watch--trail)))
             (cube-watch--set-run run-id)))))
     (lambda (_code err) (cube-log "watch: status: %s" err)))
    (cube-watch--load-trail bead)))

;;;###autoload
(defun cube-watch (bead)
  "Open the watch buffer for BEAD and follow its events."
  (interactive (list (cube-beads--read-id "Watch bead: ")))
  (let ((buffer (get-buffer-create (cube-watch--buffer-name bead))))
    (with-current-buffer buffer
      (unless (derived-mode-p 'cube-watch-mode) (cube-watch-mode))
      (setq cube-watch--bead bead)
      (cube-watch--render)
      (cube-server-watch-events)
      (cube-watch-refresh))
    (pop-to-buffer buffer)))

;;;; Live events

(defun cube-watch--schedule-refresh ()
  "Refetch this buffer once `cube-watch-refresh-delay' has passed."
  (when (timerp cube-watch--refresh-timer) (cancel-timer cube-watch--refresh-timer))
  (let ((buffer (current-buffer)))
    (setq cube-watch--refresh-timer
          (run-with-timer cube-watch-refresh-delay nil
                          (lambda ()
                            (when (buffer-live-p buffer)
                              (with-current-buffer buffer (cube-watch-refresh))))))))

(defun cube-watch--on-notify (session event title _body-file plist)
  "Route a `cube-notify' EVENT for SESSION with TITLE and PLIST to watch buffers."
  (dolist (buffer (cube-watch--buffers))
    (with-current-buffer buffer
      (when (cube-watch--event-relevant-p cube-watch--bead cube-watch--run session plist)
        (let ((entry (cube-watch--entry session event title plist)))
          (setq cube-watch--trail (cube-watch--append-entry cube-watch--trail entry))
          (when (and (not cube-watch--run) (plist-get entry :run-id))
            (setq cube-watch--run (plist-get entry :run-id)))
          (cube-watch--render)
          (when (cube-watch--state-changing-p (plist-get entry :event))
            (cube-watch--schedule-refresh)))))))

(add-hook 'cube-notify-hook #'cube-watch--on-notify)

;;;; Actions

(defun cube-watch--require-role ()
  "Return the role for this buffer's bead, asking when the bead has none."
  (or (cube-watch--role cube-watch--bead-json)
      (completing-read "Role: " (cube-rolodex-roles-now) nil t)))

(defun cube-watch-show-prompt ()
  "Show the assembled prompt, runner and model of a dry run on this bead."
  (interactive)
  (let* ((bead cube-watch--bead)
         (role (cube-watch--require-role))
         (args (list "run" role "--bead" bead "--dry-run" "--show-prompt")))
    (message "cube: assembling the %s prompt for %s..." role bead)
    (cube--call-json-async
     args
     (lambda (json)
       (with-current-buffer (get-buffer-create (format "*cube:prompt:%s*" bead))
         (let ((inhibit-read-only t))
           (erase-buffer)
           (insert (format "cube %s --json\n\n" (string-join args " ")))
           (insert (format "runner %s   model %s   tools %s\n"
                           (cube--string (cube-get json 'runner))
                           (cube--string (cube-get json 'model))
                           (if (cube-true-p (cube-get json 'needs_tools)) "yes" "no")))
           (insert (format "route %s\n\n" (cube--string (cube-get json 'message))))
           (insert "Command\n  " (string-join (mapcar #'cube--string (cube-get json 'command)) " ")
                   "\n\n--- prompt ---\n" (cube--string (cube-get json 'prompt)) "\n")
           (goto-char (point-min)))
         (special-mode)
         (pop-to-buffer (current-buffer))))
     (lambda (code err) (message "cube: dry-run failed (%s): %s" code err)))))

(defun cube-watch-start ()
  "Dry-run, confirm and start the role on this bead, attached in tmux."
  (interactive)
  (cube-run-bead (cube-watch--require-role) cube-watch--bead))

(defun cube-watch-resume ()
  "Like `cube-watch-start' with `--resume' for the bead's stored session."
  (interactive)
  (cube-run-bead (cube-watch--require-role) cube-watch--bead t))

(defun cube-watch-attach ()
  "Jump to the attached run session of this bead, attaching it if needed."
  (interactive)
  (let* ((name (cube-watch--session-name (cube-watch--require-role) cube-watch--bead))
         (session (cube-rolodex-find name)))
    (if session
        (cube-rolodex-jump session)
      (cube-rolodex-attach (concat "run-" name)))))

(defun cube-watch--run-directory ()
  "Return the run directory of the watched run on the host, or signal."
  (let ((log (cube-get cube-watch--run-json 'log)))
    (unless log (user-error "cube: no run to open yet"))
    (cube-host-file-name (file-name-directory (if (file-name-absolute-p log) log
                                                (cube-root-file log))))))

(defun cube-watch-open-run ()
  "Open the run directory of the watched run."
  (interactive)
  (dired (cube-watch--run-directory)))

(defun cube-watch-open-artifact ()
  "Open the audit report or notes of the watched run."
  (interactive)
  (let* ((dir (cube-watch--run-directory))
         (candidates (list (expand-file-name "audit.md" dir)
                           (expand-file-name "notes.md" dir)
                           (expand-file-name "result.json" dir)))
         (file (seq-find #'file-exists-p candidates)))
    (if file (find-file file) (dired dir))))

(defun cube-watch-open-bead ()
  "Open the bead of this buffer in the bead view."
  (interactive)
  (cube-beads-show cube-watch--bead))

(defun cube-watch-review ()
  "Preview the review gate for this bead (`cube review ID --dry-run')."
  (interactive)
  (let ((bead cube-watch--bead))
    (cube--call-json-async
     (list "review" bead "--dry-run")
     (lambda (json)
       (with-current-buffer (get-buffer-create (format "*cube:review:%s*" bead))
         (let ((inhibit-read-only t))
           (erase-buffer)
           (insert (format "cube review %s --dry-run --json\n\n" bead) (pp-to-string json))
           (goto-char (point-min)))
         (special-mode)
         (pop-to-buffer (current-buffer))))
     (lambda (code err) (message "cube: review dry-run failed (%s): %s" code err)))))

(defun cube-watch-approvals ()
  "Open the approval queue (empty when nothing outbound was requested)."
  (interactive)
  (if (fboundp 'cube-review)
      (cube-review)
    (cube--call-json-async
     (list "approvals")
     (lambda (json) (message "cube: approvals %s" (pp-to-string json))))))

;;;; Create and watch

(defun cube-watch--read-new-plist ()
  "Ask for the fields of a new task and return them as a plist."
  (let* ((title (read-string "Title: "))
         (kind (read-string "Kind (audit): " nil nil "audit"))
         (role (completing-read "Role: " (cube-rolodex-roles-now) nil nil
                                (if (string= kind "audit") "auditor" nil)))
         (project (read-string "Project slug (optional): "))
         (privacy (completing-read "Privacy: " '("public" "internal" "local-only") nil t nil nil
                                   "internal"))
         (acceptance (read-string "Acceptance: "))
         (provenance (read-string "Provenance: "))
         (labels (split-string (read-string "Extra labels key:value (optional, comma separated): ")
                               "," t "[ \t]+")))
    (when (string-empty-p title) (user-error "cube: a task needs a title"))
    (list :title title :kind kind :role role
          :project (unless (string-empty-p project) project)
          :privacy privacy :acceptance acceptance :provenance (list provenance)
          :labels labels)))

;;;###autoload
(defun cube-watch-new (plist)
  "Create a task from PLIST (dry-run, confirm, apply) and open its watch buffer."
  (interactive (list (cube-watch--read-new-plist)))
  (let* ((base (seq-remove (lambda (a) (member a '("--dry-run" "--apply")))
                           (cube-watch--create-args plist)))
         (dry (append base '("--dry-run"))))
    (cube--call-json-async
     dry
     (lambda (json)
       (cube-beads--show-write-plan "create" dry json)
       (when (cube-beads--confirm "Apply cube create? ")
         (cube--call-json-async
          (append base '("--apply"))
          (lambda (result)
            (let ((id (cube--string (cube-get result 'bead))))
              (message "cube: created %s; press s in the watch buffer to start" id)
              (cube-watch id)))
          (lambda (code err) (message "cube: create apply failed (%s): %s" code err)))))
     (lambda (code err) (message "cube: create dry-run failed (%s): %s" code err)))))

(provide 'cube-watch)
;;; cube-watch.el ends here
