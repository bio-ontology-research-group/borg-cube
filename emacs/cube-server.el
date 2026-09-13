;;; cube-server.el --- Emacs server, notifications and event tail  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, processes

;;; Commentary:

;; The agent-facing side of the cockpit.  `cube-notify' is the single
;; entry point for events: hooks on the host append to state/events.jsonl
;; through `cube notify', this file tails that log over ssh (or watches
;; it with inotify in local mode) and turns each line into a
;; `cube-notify' call.  Local agents can also call `cube-notify' directly
;; through `emacsclient -s cube' (see bin/cube-emacs-hook).

;;; Code:

(require 'cl-lib)
(require 'subr-x)
(require 'filenotify)
(require 'cube-core)
(require 'cube-rolodex)

(declare-function server-running-p "server" (&optional name))
(declare-function server-start "server" (&optional leave-dead inhibit-prompt))
(declare-function markdown-mode "markdown-mode")
(defvar server-name)
(defvar server-process)

(defvar cube-notify-hook nil
  "Hook run with (SESSION EVENT TITLE BODY-FILE PLIST) after `cube-notify'.")

(defconst cube-server-event-states
  '(("start" . running) ("prompt" . running) ("running" . running)
    ("stop" . idle) ("idle" . idle) ("finished" . idle)
    ("notification" . attention) ("attention" . attention)
    ("approval" . attention) ("permission" . attention)
    ("error" . error) ("failed" . error)
    ("queued" . idle) ("goal" . idle)
    ("end" . exited) ("exited" . exited))
  "Map of event names to session states.")

(defcustom cube-server-notify-events
  '("goal" "error")
  "Events that produce a desktop notification.
Robert, 2026-09-07: only a completed goal and an error.  Attention,
approval and permission events stay in the cockpit (header line, `!' key,
`cube attention'); a P0 incident always notifies.  Add \"approval\" here to
be told when an approval bead is waiting, \"attention\" for everything the
patrols flag."
  :type '(repeat string)
  :group 'borg-cube)

(defcustom cube-server-notify-repeat-seconds 86400
  "Seconds during which the same session and title do not notify twice.
The backend also marks a repeated loud event `muted' inside this window
(`cube notify'); a muted event never notifies here."
  :type 'integer
  :group 'borg-cube)

(defvar cube-server--notified (make-hash-table :test #'equal)
  "Recent desktop notifications: (name . title) to the time they were shown.")

(defun cube-server--notify-repeat-p (name title)
  "Return non-nil when NAME and TITLE were notified within the repeat window.
Otherwise record them and return nil."
  (let* ((key (cons name title))
         (last (gethash key cube-server--notified))
         (now (float-time)))
    (if (and last (< (- now last) cube-server-notify-repeat-seconds))
        t
      (puthash key now cube-server--notified)
      nil)))

;;;; Emacs server

(defun cube-server-ensure ()
  "Start the Emacs server named \"cube\" unless another instance holds it."
  (interactive)
  (require 'server)
  (cond
   ((and (bound-and-true-p server-process) (equal server-name "cube"))
    t)
   ((server-running-p "cube")
    (cube-log "server: another Emacs already serves \"cube\"; not starting")
    nil)
   (t
    (setq server-name "cube")
    (server-start)
    (cube-log "server: started as \"cube\"")
    t)))

;;;; Notifications

(defun cube-server--event-state (event)
  "Return the session state for EVENT, or nil to leave it unchanged."
  (alist-get event cube-server-event-states nil nil #'string=))

(defun cube-server--muted-p (plist)
  "Return non-nil when the event PLIST is a muted repeat (`muted': true)."
  (let ((muted (plist-get plist :muted)))
    (and muted (not (eq muted :false)))))

(defun cube-server--buffer-visible-p (buffer)
  "Return non-nil when BUFFER is shown in the selected window."
  (and (buffer-live-p buffer) (eq buffer (window-buffer (selected-window)))))

(defun cube-server--p0-event-p (plist)
  "Return non-nil when PLIST describes a P0 incident event.
The event contract leaves DATA open-ended, so accept the common direct,
incident and banner forms while retaining the ordinary event severity."
  (let ((data (plist-get plist :data)))
    (or (equal (plist-get plist :severity) "p0")
        (equal (cube-get data 'severity) "p0")
        (equal (cube-get data 'incident_severity) "p0")
        (equal (cube-get data 'incident 'severity) "p0")
        (equal (cube-get data 'banner 'severity) "p0"))))

(defun cube-session-register (name kind &optional plist)
  "Register or update a session NAME of KIND from PLIST.
Used for sessions started outside the cockpit and for remote events
about sessions without a local buffer.  Return the session."
  (let* ((session (or (cube-rolodex-find name)
                      (cube-rolodex--register
                       (cube-session-create :name name :started (current-time)))))
         (buffer (plist-get plist :buffer)))
    (setf (cube-session-kind session)
          (or (and kind (if (stringp kind) (intern kind) kind))
              (cube-session-kind session) 'remote))
    (when buffer (setf (cube-session-buffer session) (get-buffer buffer)))
    (dolist (key '(:role :student :bead :cwd :run-id :resume-id))
      (when-let* ((v (plist-get plist key)))
        (pcase key
          (:role (setf (cube-session-role session) v))
          (:student (setf (cube-session-student session) v))
          (:bead (setf (cube-session-bead session) v))
          (:cwd (setf (cube-session-cwd session) v))
          (:run-id (setf (cube-session-run-id session) v))
          (:resume-id (setf (cube-session-resume-id session) v)))))
    (setf (cube-session-remote session) (plist-get plist :remote))
    session))

(defun cube-notify (session event &optional title body-file plist)
  "Record EVENT for SESSION and alert Robert when it matters.
SESSION is a session name, EVENT a string like \"stop\" or
\"notification\", TITLE a short text, BODY-FILE a file with details.
PLIST may carry :source :severity :run-id :bead :resume-id :cwd :kind.
Updates the rolodex state, shows a desktop notification unless the
session buffer is in the selected window, logs, and runs
`cube-notify-hook'."
  (let* ((event (if (symbolp event) (symbol-name event) (downcase event)))
         (name (or session "unknown"))
         (s (or (cube-rolodex-find name)
                (cube-session-register name (plist-get plist :kind)
                                       (list :remote cube-remote-host))))
         (state (cube-server--event-state event)))
    (when-let* ((id (plist-get plist :resume-id)))
      (setf (cube-session-resume-id s) id))
    (when-let* ((id (plist-get plist :run-id)))
      (setf (cube-session-run-id s) id))
    (when-let* ((bead (plist-get plist :bead)))
      (setf (cube-session-bead s) bead))
    (setf (cube-session-last-activity s) (current-time))
    (when state
      (cube-rolodex-set-state s state (and (memq state '(attention error idle)) title)))
    (cube-log "notify %s %s%s" name event (if title (concat ": " title) ""))
    (when (and (or (cube-server--p0-event-p plist)
                   (and (member event cube-server-notify-events)
                        (not (cube-server--muted-p plist))
                        (not (cube-server--buffer-visible-p (cube-session-buffer s)))))
               (or (cube-server--p0-event-p plist)
                   (not (cube-server--notify-repeat-p name (or title event)))))
      (cube--notify-desktop (format "%s: %s" name (or title event))
                            (cube-server--body-excerpt body-file)
                            (if (or (cube-server--p0-event-p plist)
                                    (memq state '(attention error)))
                                'critical 'normal)))
    (run-hook-with-args 'cube-notify-hook name event title body-file plist)
    s))

(defun cube-server--body-excerpt (body-file)
  "Return the first lines of BODY-FILE as a notification body, or \"\"."
  (if (and body-file (file-readable-p body-file))
      (with-temp-buffer
        (insert-file-contents body-file nil 0 400)
        (string-trim (buffer-string)))
    ""))

;;;; Hook payload mapping (pure)

(defconst cube-hooks-claude-events
  '(("SessionStart" . "start") ("UserPromptSubmit" . "prompt")
    ("Notification" . "notification") ("Stop" . "stop")
    ("SubagentStop" . "running") ("SessionEnd" . "end")
    ("PreToolUse" . "running") ("PostToolUse" . "running"))
  "Claude Code hook_event_name to cube event names.")

(defun cube-hooks-event-name (hook-event-name)
  "Return the cube event for the Claude Code HOOK-EVENT-NAME."
  (or (alist-get hook-event-name cube-hooks-claude-events nil nil #'string=)
      (downcase (or hook-event-name "unknown"))))

(defun cube-hooks-claude->notify (payload &optional session)
  "Map a Claude Code hook PAYLOAD (parsed alist) to `cube-notify' arguments.
SESSION overrides the session name (normally $CUBE_SESSION); otherwise
the Claude session id is used.  Return (SESSION EVENT TITLE BODY PLIST)
where BODY is text, not a file."
  (let* ((hook (cube-get payload 'hook_event_name))
         (event (cube-hooks-event-name hook))
         (sid (cube-get payload 'session_id))
         (title (pcase event
                  ("notification" (or (cube-get payload 'message) "Claude needs you"))
                  ("stop" "Claude finished its turn")
                  ("prompt" (let ((p (cube-get payload 'prompt)))
                              (and p (truncate-string-to-width p 60 nil nil "..."))))
                  ("start" (format "session %s" (or (cube-get payload 'source) "started")))
                  ("end" (format "session ended (%s)" (or (cube-get payload 'reason) "exit")))
                  (_ nil)))
         (body (or (cube-get payload 'last_assistant_message)
                   (and (string= event "notification") (cube-get payload 'message)))))
    (list (or session sid "claude") event title body
          (list :source "claude" :hook hook :session-id sid
                :resume-id sid
                :cwd (cube-get payload 'cwd)
                :notification-type (cube-get payload 'notification_type)))))

(defun cube-hooks-codex->notify (payload &optional session)
  "Map a Codex notify PAYLOAD (parsed alist) to `cube-notify' arguments.
Codex uses hyphenated keys (thread-id, last-assistant-message); older
builds used underscores, both are accepted.  SESSION as in
`cube-hooks-claude->notify'."
  (let* ((get (lambda (&rest names)
                (seq-some (lambda (n) (cube-get payload n)) names)))
         (type (or (funcall get 'type) "agent-turn-complete"))
         (thread (funcall get 'thread-id 'thread_id))
         (last (funcall get 'last-assistant-message 'last_assistant_message))
         (event (if (string= type "agent-turn-complete") "stop" (downcase type))))
    (list (or session thread "codex") event
          (if (string= event "stop") "Codex finished its turn" type)
          last
          (list :source "codex" :hook type :session-id thread :resume-id thread
                :cwd (funcall get 'cwd)
                :turn-id (funcall get 'turn-id 'turn_id)))))

;;;; Event log lines

(defun cube-server--event-plist (event)
  "Return the `cube-notify' plist for the parsed events.jsonl line EVENT."
  (list :source (cube-get event 'source)
        :severity (cube-get event 'severity)
        :run-id (cube-get event 'run_id)
        :bead (cube-get event 'bead)
        :resume-id (cube-get event 'resume_id)
        :kind (cube-get event 'kind)
        :muted (cube-get event 'muted)
        :ts (cube-get event 'ts)
        :seq (cube-get event 'seq)
        :data (cube-get event 'data)))

(defun cube-server-dispatch-event (event)
  "Route one parsed events.jsonl line EVENT through `cube-notify'."
  (let ((name (or (cube-get event 'session) (cube-get event 'run_id) "cube"))
        (kind (or (cube-get event 'event) "notification"))
        (body (cube-get event 'body_file)))
    (cube-notify name kind (cube-get event 'title)
                 (and body (if cube-remote-host
                               (cube-remote-file-name
                                (if (file-name-absolute-p body) body
                                  (cube-root-file body)))
                             (cube-root-file body)))
                 (cube-server--event-plist event))))

(defun cube-server--dispatch-lines (text)
  "Parse each complete JSON line in TEXT and dispatch it.
Return the trailing partial line (possibly empty)."
  (let* ((lines (split-string text "\n"))
         (rest (car (last lines))))
    (dolist (line (butlast lines))
      (let ((line (string-trim line)))
        (unless (string-empty-p line)
          (condition-case err
              (cube-server-dispatch-event (cube--parse-json-string line))
            (error (cube-log "events: bad line %S: %s" line
                             (error-message-string err)))))))
    rest))

;;;; Event tail (remote) and inotify (local)

(defvar cube-server--events-process nil
  "The ssh tail process in remote mode.")
(defvar cube-server--events-pending ""
  "Partial line carried over between filter calls.")
(defvar cube-server--events-backoff 5
  "Seconds to wait before restarting the tail; doubles on each failure.")
(defvar cube-server--events-timer nil
  "Timer for the pending tail restart.")
(defvar cube-server--events-watch nil
  "The `file-notify' descriptor in local mode.")
(defvar cube-server--events-offset 0
  "How much of the local events file has been consumed.")
(defvar cube-server--events-enabled nil
  "Non-nil while the watcher should keep itself alive.")

(defun cube-server--events-filter (_proc text)
  "Feed TEXT from the tail process into the dispatcher."
  (setq cube-server--events-backoff 5)
  (setq cube-server--events-pending
        (cube-server--dispatch-lines (concat cube-server--events-pending text))))

(defun cube-server--events-sentinel (proc event)
  "Restart the tail after PROC ends with EVENT, with backoff."
  (when (memq (process-status proc) '(exit signal))
    (cube-log "events: tail ended (%s)" (string-trim event))
    (setq cube-server--events-process nil)
    (when cube-server--events-enabled
      (cube-log "events: restarting in %ds" cube-server--events-backoff)
      (setq cube-server--events-timer
            (run-with-timer cube-server--events-backoff nil
                            #'cube-server--start-tail))
      (setq cube-server--events-backoff (min 300 (* 2 cube-server--events-backoff))))))

(defun cube-server--start-tail ()
  "Start the remote tail process."
  (setq cube-server--events-timer nil)
  (when (and cube-server--events-enabled cube-remote-host
             (not (process-live-p cube-server--events-process)))
    (let ((default-directory (expand-file-name "~/"))
          (command (cube--ssh-args
                    (list "tail" "-n0" "-F" (cube-root-file cube-events-file)))))
      (setq cube-server--events-pending "")
      (setq cube-server--events-process
            (make-process :name "cube-events" :command command :noquery t
                          :connection-type 'pipe
                          :filter #'cube-server--events-filter
                          :sentinel #'cube-server--events-sentinel))
      (cube-log "events: tailing %s on %s" cube-events-file cube-remote-host))))

(defun cube-server--read-local-events ()
  "Dispatch new lines appended to the local events file."
  (let ((file (cube-root-file cube-events-file)))
    (when (file-readable-p file)
      (let ((size (file-attribute-size (file-attributes file))))
        (when (< size cube-server--events-offset)
          (setq cube-server--events-offset 0))
        (when (> size cube-server--events-offset)
          (with-temp-buffer
            (insert-file-contents file nil cube-server--events-offset size)
            (let ((rest (cube-server--dispatch-lines
                         (concat cube-server--events-pending (buffer-string)))))
              (setq cube-server--events-pending rest)
              (setq cube-server--events-offset size))))))))

(defun cube-server--local-change (event)
  "Handle the `file-notify' EVENT for the events directory."
  (let ((file (cube-root-file cube-events-file))
        (changed (nth 2 event)))
    (when (and (memq (nth 1 event) '(changed created attribute-changed))
               (or (null changed)
                   (string= (file-truename changed) (file-truename file))))
      (cube-server--read-local-events))))

(defun cube-server--start-local-watch ()
  "Watch the local events file with inotify."
  (let* ((file (cube-root-file cube-events-file))
         (dir (file-name-directory file)))
    (unless (file-directory-p dir) (make-directory dir t))
    (setq cube-server--events-offset
          (if (file-exists-p file)
              (file-attribute-size (file-attributes file))
            0))
    (setq cube-server--events-pending "")
    (setq cube-server--events-watch
          (file-notify-add-watch dir '(change) #'cube-server--local-change))
    (cube-log "events: watching %s" file)))

(defun cube-server-watch-events ()
  "Start receiving events: ssh tail in remote mode, inotify locally."
  (interactive)
  (setq cube-server--events-enabled t)
  (if cube-remote-host
      (cube-server--start-tail)
    (unless cube-server--events-watch
      (cube-server--start-local-watch))))

(defun cube-server-unwatch-events ()
  "Stop receiving events."
  (interactive)
  (setq cube-server--events-enabled nil)
  (when cube-server--events-timer
    (cancel-timer cube-server--events-timer)
    (setq cube-server--events-timer nil))
  (when (process-live-p cube-server--events-process)
    (delete-process cube-server--events-process))
  (setq cube-server--events-process nil)
  (when cube-server--events-watch
    (ignore-errors (file-notify-rm-watch cube-server--events-watch))
    (setq cube-server--events-watch nil)))

;;;; Agent-callable helpers

(defun cube-open-file (file &optional line)
  "Open FILE (a path on the backend host) and go to LINE.
In remote mode FILE is opened through TRAMP."
  (find-file (if (and cube-remote-host (not (file-remote-p file)))
                 (cube-remote-file-name file)
               (expand-file-name file)))
  (when line
    (goto-char (point-min))
    (forward-line (1- line)))
  (current-buffer))

(defun cube-show-markdown (file-or-string &optional title)
  "Show markdown from FILE-OR-STRING in a buffer named after TITLE.
FILE-OR-STRING is a readable file name or literal markdown text."
  (let* ((title (or title "note"))
         (buffer (get-buffer-create (format "*cube:markdown:%s*" title))))
    (with-current-buffer buffer
      (let ((inhibit-read-only t))
        (erase-buffer)
        (if (and (not (string-match-p "\n" file-or-string))
                 (file-readable-p file-or-string))
            (insert-file-contents file-or-string)
          (insert file-or-string)))
      (if (require 'markdown-mode nil t)
          (markdown-mode)
        (text-mode))
      (view-mode 1)
      (goto-char (point-min)))
    (pop-to-buffer buffer)
    buffer))

(provide 'cube-server)
;;; cube-server.el ends here
