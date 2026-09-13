;;; cube-agents.el --- Standing agents in the borg-cube cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;;; Commentary:

;; The standing-agent view is the thin Emacs side of `cube agent'.  The
;; backend remains authoritative for charters, inboxes, proposals, journals,
;; resources and session state.  This module caches list results for the
;; dashboard and menus, and renders the detailed show result in a Magit
;; section buffer.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'magit-section)
(require 'transient)
(require 'cube-core)
(require 'cube-rolodex)
(require 'cube-beads)
(require 'cube-review)

(declare-function cube-dashboard--current-item "cube-dashboard" ())
(declare-function cube-dashboard--render "cube-dashboard" ())
(declare-function cube-menu--context-items "cube-menu" (type))

(defcustom cube-agents-confirm-writes t
  "When non-nil ask before applying a standing-agent write plan."
  :type 'boolean
  :group 'borg-cube)

(defvaralias 'cube-agents--cache 'cube-agent--cache)

(defvar cube-agent--cache nil
  "Standing agents returned by the latest successful agent list call.")

(defvar cube-agent--work-cache nil
  "Agent rows of the latest `cube work' payload, keyed by name in `cube-get'.")

(defvar cube-agent--viewed-request-ids (make-hash-table :test #'equal)
  "Request bead ids whose returned answers Robert has viewed in this Emacs session.")

(defvar cube-agent-update-hook nil
  "Hook run after the standing-agent cache changes.")

(defvar cube-agent--new-plist nil
  "Fields collected by the new-agent transient.")

(defvar-local cube-agent--agent nil
  "Full agent object shown in the current agent buffer.")

;;;; Pure list and display helpers

(defun cube-agents--list (json)
  "Return the standing-agent list in JSON, accepting wrapped payloads."
  (cond ((and (consp json) (assq 'agents json)) (cube-get json 'agents))
        ((and (listp json) (or (null json) (consp (car json)))) json)
        (t nil)))

(defun cube-agent--object (json)
  "Return the agent object in JSON, accepting a wrapped show payload."
  (if (and (consp json) (consp (cube-get json 'agent)))
      (cube-get json 'agent)
    json))

(defun cube-agent--name (agent)
  "Return AGENT's name as a string."
  (cube--string (or (cube-get agent 'name) (cube-get agent 'id))))

(defun cube-agent--kind (agent)
  "Return AGENT's kind as a string."
  (cube--string (or (cube-get agent 'kind) "expert")))

(defun cube-agent--host (agent)
  "Return AGENT's execution host, defaulting to the orchestration host."
  (cube--string (or (cube-get agent 'host) "ws")))

(defun cube-agent--transport-host (agent)
  "Return the explicit transport host for AGENT.
The laptop is the machine running Emacs, so it deliberately maps to nil.
All other host labels are ssh destinations."
  (let ((host (cube-agent--host agent)))
    (unless (equal host "laptop") host)))

(defun cube-agent--kind-glyph (agent-or-kind)
  "Return the standing-agent glyph for AGENT-OR-KIND."
  (let ((kind (if (listp agent-or-kind)
                  (cube-agent--kind agent-or-kind)
                (cube--string agent-or-kind))))
    (if (equal kind "coordinator") "◎" "●")))

(defun cube-agent--unread-p (message)
  "Return non-nil when MESSAGE is unread."
  (not (cube-true-p (cube-get message 'read))))

(defun cube-agent--used (agent key)
  "Return today's resource KEY from AGENT, or zero when absent."
  (let ((resources (or (cube-get agent 'resources_used_today)
                       (cube-get agent 'resources 'used_today))))
    (or (cube-get resources key) 0)))

(defun cube-agent--resource-summary (agent)
  "Return a compact today-used resource summary for AGENT."
  (format "gpu %.1fh  runs %s  spend $%.2f"
          (cube-agent--used agent 'gpu_hours)
          (cube--string (cube-agent--used agent 'runs))
          (cube-agent--used agent 'spend_usd)))

(defun cube-agent--row-text (agent &optional now)
  "Return the dashboard row for AGENT, using NOW for age tests."
  (concat
   (format "%s %-16s %-28s %-8s proposals %d  inbox %d  journal %-4s  %s"
           (cube-agent--kind-glyph agent)
           (cube-agent--name agent)
           (truncate-string-to-width (cube--string (cube-get agent 'title)) 28)
           (cube--string (or (cube-get agent 'state) "unknown"))
           (or (cube-get agent 'pending_proposals) 0)
           (or (cube-get agent 'inbox_unread) 0)
           (let ((age (cube--age-string (cube-get agent 'last_journal) now)))
             (if (string-empty-p age) "-" age))
           (cube-agent--resource-summary agent))
   (cube-agent--work-summary agent)
   (if (cube-agent--has-unviewed-return-p agent) "  ↩" "")))

(defun cube-agent--row-item (agent &optional now)
  "Return a dashboard item for AGENT."
  (list :type 'agent :id (cube-agent--name agent)
        :label (cube-agent--row-text agent now) :detail nil :data agent))

(defun cube-agent--set-work-cache (json)
  "Store the agent rows of the `cube work' payload JSON."
  (setq cube-agent--work-cache (cube-get json 'agents))
  cube-agent--work-cache)

(defun cube-agent--work (agent)
  "Return the cached `cube work' row for AGENT, or nil."
  (let ((name (cube-agent--name agent)))
    (seq-find (lambda (row) (equal (cube--string (cube-get row 'name)) name))
              cube-agent--work-cache)))

(defun cube-agent--work-summary (agent)
  "Return the work fragment of AGENT's row: current bead, assigned, tick.
Empty when no `cube work' payload has been cached yet."
  (if-let* ((work (cube-agent--work agent)))
      (let ((bead (cube--string (cube-get work 'current 'bead)))
            (assigned (length (cube-get work 'assigned)))
            (tick (cube--string (or (cube-get work 'next_tick) "-")))
            (last (cube--string (or (cube-get work 'last_workday) "never"))))
        (format "  %s  assigned %d  tick %s  last %s"
                (if (string-empty-p bead) "-" bead) assigned tick last))
    ""))

(defun cube-agents--set-cache (json)
  "Store the agent list from JSON and run the update hook."
  (setq cube-agent--cache (cube-agents--list json))
  (run-hooks 'cube-agent-update-hook)
  cube-agent--cache)

(defun cube-agent--find (name)
  "Return cached standing agent NAME, or nil."
  (seq-find (lambda (agent) (equal (cube-agent--name agent) (cube--string name)))
            cube-agent--cache))

(defun cube-agent--completion-table ()
  "Return annotated completion pairs for cached standing agents."
  (mapcar (lambda (agent)
            (cons (format "%s %s  %s"
                          (cube-agent--kind-glyph agent)
                          (cube-agent--name agent)
                          (cube--string (cube-get agent 'title)))
                  (cube-agent--name agent)))
          cube-agent--cache))

(defun cube-agent--read-name (&optional default)
  "Read a standing-agent name, preferring DEFAULT."
  (let* ((default (or default "coordinator"))
         (choices (cube-agent--completion-table))
         (choice (completing-read (format "Agent (%s): " default)
                                  choices nil t nil nil default)))
    (if (string-empty-p choice) default
      (or (cdr (assoc choice choices)) choice))))

(defun cube-agent--context-item ()
  "Return the current dashboard or agent item, when it is one."
  (cond
   ((and (derived-mode-p 'cube-agent-mode)
         (fboundp 'magit-current-section))
    (let ((section (magit-current-section)))
      (when section
        (let ((value (oref section value)))
          (when (and (listp value) (plist-get value :type))
            value)))))
   ((fboundp 'cube-dashboard--current-item)
    (let ((item (cube-dashboard--current-item)))
      (when (and (listp item) (eq (plist-get item :type) 'agent))
        item)))))

(defun cube-agent--context-name ()
  "Return the name at the current standing-agent item, or nil."
  (or (and (derived-mode-p 'cube-agent-mode) cube-agent--agent
           (cube-agent--name cube-agent--agent))
      (when-let* ((item (cube-agent--context-item)))
        (or (plist-get item :id)
            (cube-agent--name (plist-get item :data))))))

(defun cube-agent--target-name (&optional prompt)
  "Return the current agent name, prompting when PROMPT is non-nil.
Without a current agent, the coordinator is the default."
  (or (cube-agent--context-name)
      (and (derived-mode-p 'cube-agent-mode) cube-agent--agent
           (cube-agent--name cube-agent--agent))
      (and prompt (cube-agent--read-name "coordinator"))
      "coordinator"))

;;;; Backend access and guarded writes

(defun cube-agents-refresh ()
  "Fetch and cache the standing-agent list asynchronously."
  (interactive)
  (cube--call-json-async
   '("agent" "list")
   (lambda (json)
     (cube-agents--set-cache json)
     (message "cube: %d standing agent(s) cached" (length cube-agent--cache)))
   (lambda (code err) (message "cube: agent list failed (%s): %s" code err))))

(defun cube-agent--talk-args (name)
  "Return the backend arguments for talking to NAME."
  (list "agent" "talk" (cube--string name) "--apply" "--attach"))

(defun cube-agent--tell-args (name text)
  "Return the backend arguments for telling NAME TEXT."
  ;; a tell is a message into the agent's own inbox, not an outbound action: apply directly
  (list "agent" "tell" (cube--string name) (cube--string text) "--from" "robert" "--apply"))

(defun cube-agent--tell-delivered-p (json)
  "Non-nil when the tell in JSON reached a live agent session."
  (let ((raw (cube-get (cube-get json 'delivery) 'delivered)))
    (and raw (not (memq raw '(:json-false :false))))))

(defcustom cube-agent-tell-wakes t
  "When non-nil, telling an agent with no live session starts one.
The new session reads the unread inbox in its context, so the agent
answers without Robert pressing T."
  :type 'boolean
  :group 'cube)

(defcustom cube-agent-wake-delay 6
  "Seconds to wait after starting an agent session before typing the tell."
  :type 'number
  :group 'cube)

(defun cube-agent--wake-and-deliver (name text &optional agent)
  "Start NAME's session, then type TEXT into it once it is up.
The inbox already holds TEXT; the second tell only delivers it to the
live terminal so the agent starts working without a keypress."
  (let ((host (cube-agent--transport-host (or agent (cube-agent--find name)))))
    (cube-agent--start-session name agent)
  (run-with-timer
   cube-agent-wake-delay nil
   (lambda ()
     (cube--call-json-async-on
      host
      (append (cube-agent--tell-args name text) '("--redeliver"))
      (lambda (json)
        (message "%s" (if (cube-agent--tell-delivered-p json)
                          (format "cube: %s is awake and has your message" name)
                          (format "cube: %s did not come up; message stays in its inbox" name))))
      (lambda (code err) (message "cube: wake of %s failed (%s): %s" name code err)))))))

(defun cube-agent--tell-outcome (name json)
  "Return the message describing how JSON says NAME received a tell."
  (let ((delivered (cube-agent--tell-delivered-p json)))
    (if delivered
        (format "cube: delivered to %s's live session" name)
      (format "cube: queued in %s's inbox (no live session). T talks to it now, w runs its workday"
              name))))

(defun cube-agent--workday-args (name &optional flag)
  "Return guarded workday-now arguments for NAME with FLAG."
  (list "agent" "workday" (cube--string name) "--now" (or flag "--dry-run")))

(defun cube-agent--pause-args (name paused &optional flag)
  "Return guarded pause or resume arguments for NAME and PAUSED state."
  (list "agent" (if paused "resume" "pause") (cube--string name)
        (or flag "--dry-run")))

(defun cube-agent--report-args (name)
  "Return arguments for NAME's weekly report."
  (list "agent" "report" (cube--string name) "--week"))

(defun cube-agent--new-args (plist &optional flag)
  "Return guarded `cube agent new' arguments from PLIST."
  (let ((name (string-trim (cube--string (plist-get plist :name))))
        (kind (string-trim (cube--string (plist-get plist :kind))))
        (title (string-trim (cube--string (plist-get plist :title))))
        (runtime (string-trim (cube--string (plist-get plist :runtime)))))
    (when (string-empty-p name) (user-error "cube: an agent needs a name"))
    (when (string-empty-p kind) (user-error "cube: an agent needs a kind"))
    (when (string-empty-p title) (user-error "cube: an agent needs a title"))
    (when (string-empty-p runtime) (user-error "cube: an agent needs a runtime"))
    (append (list "agent" "new" name "--kind" kind "--title" title)
            (apply #'append
                   (mapcar (lambda (topic) (list "--topic" topic))
                           (seq-filter (lambda (topic) (not (string-empty-p topic)))
                                       (plist-get plist :topics))))
            (when (and (plist-get plist :role)
                       (not (string-empty-p (plist-get plist :role))))
              (list "--role" (plist-get plist :role)))
            (list "--runtime" runtime)
            (when (plist-get plist :from-template) (list "--from-template"))
            (list (or flag "--dry-run")))))

(defun cube-agent--show-plan (label args json)
  "Show LABEL's guarded dry-run ARGS and JSON response."
  (with-current-buffer (get-buffer-create "*cube-agent-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (format "Standing agent plan: %s\n\nCommand\n  cube %s --json\n\nResult\n"
                      label (string-join args " ")))
      (when-let* ((diff (cube-get json 'diff))) (insert "\nDiff\n" diff "\n"))
      (insert (pp-to-string json))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-agent--write (args label &optional callback host)
  "Dry-run guarded agent ARGS on HOST, show LABEL, then confirm and apply.
HOST is nil for this machine; the agent's own `host:' otherwise."
  (let* ((base (seq-remove (lambda (arg) (member arg '("--dry-run" "--apply"))) args))
         (dry (append base '("--dry-run"))))
    (cube--call-json-async-on
     host dry
     (lambda (json)
       (cube-agent--show-plan label dry json)
       (when (or (not cube-agents-confirm-writes)
                 (y-or-n-p (format "Apply agent %s? " label)))
         (cube--call-json-async-on
          host (append base '("--apply"))
          (lambda (result)
            (message "cube: agent %s applied" label)
            (cube-agents-refresh)
            (when callback (funcall callback result)))
          (lambda (code err)
            (message "cube: agent %s apply failed (%s): %s" label code err)))))
     (lambda (code err)
       (message "cube: agent %s dry-run failed (%s): %s" label code err)))))

;;;; Commands

(defun cube-agent--start-session (name &optional agent)
  "Start or show the rolodex session for standing agent NAME."
  (let* ((agent (or agent (cube-agent--find name)))
         (name (cube--string name))
         (existing (cube-rolodex-find name)))
    (if (and existing (buffer-live-p (cube-session-buffer existing)))
        (cube-rolodex--show (cube-session-buffer existing))
      (let ((cube-remote-host (cube-agent--transport-host agent)))
        (cube-rolodex-start
         'agent name
         :agent-kind (and agent (cube-agent--kind agent))
         :title (and agent (cube-get agent 'title))
         :topics (and agent (cube-get agent 'topics))
         :tags (list (concat "agent:" name)))))))

(defun cube-agent-talk (&optional prefix agent-name)
  "Attach to a standing agent session.
Without a prefix use the coordinator, except when invoked on an agent row.
With a prefix prompt for an agent with completion."
  (interactive "P")
  (let* ((name (or agent-name
                   (and prefix (cube-agent--read-name))
                   (cube-agent--context-name)
                   "coordinator"))
         (agent (cube-agent--find name)))
    (cube-agent--start-session name agent)))

(defun cube-agent-tell (&optional name text)
  "Tell standing agent NAME TEXT, then show its inbox."
  (interactive)
  (let* ((name (or name (cube-agent--target-name t)))
         (agent (cube-agent--find name))
         (text (or text (read-string (format "Tell %s: " name)))))
    (when (string-empty-p (string-trim text))
      (user-error "cube: tell needs text"))
    (cube--call-json-async-on
     (cube-agent--transport-host agent)
     (cube-agent--tell-args name text)
     (lambda (json)
       (cond
        ((cube-agent--tell-delivered-p json)
         (message "%s" (cube-agent--tell-outcome name json))
         (cube-agent-open name))
        (cube-agent-tell-wakes
         (message "cube: queued for %s; waking it" name)
         (cube-agent--wake-and-deliver name text agent))
        (t
         (message "%s" (cube-agent--tell-outcome name json))
         (cube-agent-open name))))
     (lambda (code err) (message "cube: tell failed (%s): %s" code err)))))

(defun cube-ask-coordinator (text)
  "Tell the coordinator TEXT: the usual way to hand the group a request."
  (interactive (list (read-string "Ask the coordinator: ")))
  (cube-agent-tell "coordinator" text))

(defun cube-agent--inbox-args (name &optional flag)
  "Return guarded read-the-inbox-now arguments for NAME with FLAG."
  (list "agent" "inbox" (cube--string name) "--now" (or flag "--dry-run")))

(defun cube-agent-workday (&optional name)
  "Run NAME's workday now after the dry-run confirmation gate."
  (interactive)
  (let* ((name (or name (cube-agent--target-name t)))
         (agent (cube-agent--find name)))
    (cube-agent--write (cube-agent--workday-args name) (format "workday %s" name) nil
                       (cube-agent--transport-host agent))))

(defun cube-agent-inbox (&optional name)
  "Make standing agent NAME read its inbox now, after the dry-run gate.
The pass runs on the agent's own host and is restricted to the unread
messages and the assigned beads they name."
  (interactive)
  (let* ((name (or name (cube-agent--target-name t)))
         (agent (cube-agent--find name)))
    (cube-agent--write (cube-agent--inbox-args name) (format "inbox %s" name) nil
                       (cube-agent--transport-host agent))))

(defun cube-agent-pause-resume (&optional name)
  "Pause or resume NAME after previewing and confirming the write."
  (interactive)
  (let* ((name (or name (cube-agent--target-name t)))
         (agent (cube-agent--find name))
         (paused (equal (cube-get agent 'state) "paused")))
    (cube-agent--write (cube-agent--pause-args name paused)
                       (format "%s %s" (if paused "resume" "pause") name))))

(defalias 'cube-agent-pause #'cube-agent-pause-resume)

(defun cube-agent--show-report (name json)
  "Show NAME's weekly report JSON in a read-only buffer."
  (with-current-buffer (get-buffer-create (format "*cube-agent-report: %s*" name))
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (or (cube-get json 'report) (cube-get json 'text)
                  (pp-to-string json)))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-agent-report (&optional name)
  "Show NAME's weekly report."
  (interactive)
  (let ((name (or name (cube-agent--target-name t))))
    (cube--call-json-async
     (cube-agent--report-args name)
     (lambda (json) (cube-agent--show-report name json))
     (lambda (code err) (message "cube: report failed (%s): %s" code err)))))

(defun cube-agent-edit-charter (&optional name)
  "Open NAME's charter file over the backend host's file access."
  (interactive)
  (let* ((name (or name (cube-agent--target-name t)))
         (agent (or (cube-agent--find name) cube-agent--agent))
         (path (or (cube-get agent 'charter_file)
                   (cube-get agent 'charter_path)
                   (format "agents/%s/charter.md" name))))
    (let ((cube-remote-host (cube-agent--transport-host agent)))
      (find-file (cube-host-file-name path)))))

;;;; New-agent transient

(defun cube-agent--new-set (key value &optional append)
  "Set new-agent KEY to VALUE, APPENDing repeatable values."
  (setq cube-agent--new-plist
        (plist-put cube-agent--new-plist key
                   (if append (append (plist-get cube-agent--new-plist key)
                                      (list value))
                     value)))
  (message "cube: %s %s" (substring (symbol-name key) 1) value))

(defun cube-agent-new-set-name ()
  "Set the new standing-agent name."
  (interactive)
  (cube-agent--new-set :name (read-string "Agent name: ")))

(defun cube-agent-new-set-kind ()
  "Set the new standing-agent kind."
  (interactive)
  (cube-agent--new-set :kind (completing-read "Kind: " '("coordinator" "expert") nil t)))

(defun cube-agent-new-set-title ()
  "Set the new standing-agent title."
  (interactive)
  (cube-agent--new-set :title (read-string "Title: ")))

(defun cube-agent-new-add-topic ()
  "Add a topic to the new standing agent."
  (interactive)
  (cube-agent--new-set :topics (read-string "Topic: ") t))

(defun cube-agent-new-set-role ()
  "Set the functional role of the new standing agent."
  (interactive)
  (cube-agent--new-set :role (completing-read "Role: " cube-rolodex-roles nil t)))

(defun cube-agent-new-set-runtime ()
  "Set the runtime of the new standing agent."
  (interactive)
  (cube-agent--new-set :runtime (completing-read "Runtime: " '("claude" "codex" "hermes") nil t)))

(defun cube-agent-new-toggle-template ()
  "Toggle scaffolding the new agent from the standard template."
  (interactive)
  (cube-agent--new-set :from-template (not (plist-get cube-agent--new-plist :from-template))))

(defun cube-agent-new-execute ()
  "Preview and create the pending standing agent."
  (interactive)
  (cube-agent--write (cube-agent--new-args cube-agent--new-plist) "new agent"))

(transient-define-prefix cube-agent-new-menu ()
  "Create a standing agent with a guarded backend plan."
  ["Identity"
   ("n" "Name" cube-agent-new-set-name)
   ("k" "Kind" cube-agent-new-set-kind)
   ("t" "Title" cube-agent-new-set-title)
   ("o" "Add topic" cube-agent-new-add-topic)]
  ["Runtime"
   ("r" "Role" cube-agent-new-set-role)
   ("R" "Runtime" cube-agent-new-set-runtime)
   ("f" "From template" cube-agent-new-toggle-template)]
  ["Execute"
   ("RET" "Preview and create" cube-agent-new-execute)
   ("q" "Quit" transient-quit-one)])

(defun cube-agent-new ()
  "Start the transient for a new standing agent."
  (interactive)
  (setq cube-agent--new-plist '(:kind "expert" :runtime "claude"))
  (transient-setup 'cube-agent-new-menu))

;;;; Agent detail buffer

(defun cube-agent--inbox (agent)
  "Return AGENT's inbox records, unread first."
  (let ((records (copy-sequence (or (cube-get agent 'inbox)
                                   (cube-get agent 'messages)))))
    (cl-stable-sort records
                    (lambda (a b)
                      (and (cube-agent--unread-p a)
                           (not (cube-agent--unread-p b)))))))

(defun cube-agent--request-p (bead)
  "Return non-nil when BEAD is a request bead."
  (equal (cube--string (or (cube-get bead 'kind) (cube-get bead 'type)))
         "request"))

(defun cube-agent--request-id (request)
  "Return REQUEST's bead id as a string."
  (cube--string (or (cube-get request 'bead) (cube-get request 'id))))

(defun cube-agent--requests (agent)
  "Return request beads addressed to AGENT.
`cube agent show' may provide them directly as `requests', or among the
agent's beads for compatibility with older backend payloads."
  (let ((requests (append (copy-sequence (cube-get agent 'requests))
                          (seq-filter #'cube-agent--request-p
                                      (cube-get agent 'beads)))))
    (seq-uniq requests
              (lambda (a b)
                (equal (cube-agent--request-id a) (cube-agent--request-id b))))))

(defun cube-agent--request-state (request)
  "Return the display state for REQUEST."
  (cube--string (or (cube-get request 'state) (cube-get request 'status)
                    "unknown")))

(defun cube-agent--request-age (request)
  "Return REQUEST's compact age, accepting a supplied duration or timestamp."
  (cube--age-string (or (cube-get request 'age) (cube-get request 'updated_at)
                         (cube-get request 'answered_at) (cube-get request 'created_at)
                         (cube-get request 'created))))

(defun cube-agent--request-return-p (request)
  "Return non-nil when REQUEST carries an answer back to the coordinator."
  (and (cube-agent--request-p request)
       (or (cube-get request 'answer) (cube-get request 'return)
           (equal (cube-agent--request-state request) "answered"))))

(defun cube-agent--request-viewed-p (request)
  "Return non-nil when REQUEST's returned answer has already been viewed."
  (or (cube-true-p (cube-get request 'answer_viewed))
      (cube-true-p (cube-get request 'return_viewed))
      (cube-true-p (cube-get request 'viewed))
      (gethash (cube-agent--request-id request) cube-agent--viewed-request-ids)))

(defun cube-agent--has-unviewed-return-p (agent)
  "Return non-nil when AGENT's coordinator row needs its return glyph."
  (and (equal (cube-agent--kind agent) "coordinator")
       (or (let ((count (or (cube-get agent 'answered_requests_unread)
                            (cube-get agent 'request_returns_unread))))
             (and (numberp count) (> count 0)))
           (seq-some (lambda (request)
                       (and (cube-agent--request-return-p request)
                            (not (cube-agent--request-viewed-p request))))
                     (cube-agent--requests agent)))))

(defun cube-agent--mark-request-viewed (request)
  "Remember that REQUEST's returned answer was opened, then redraw agent rows."
  (puthash (cube-agent--request-id request) t cube-agent--viewed-request-ids)
  (when-let* ((dashboard (get-buffer "*cube*")))
    (with-current-buffer dashboard
      (when (derived-mode-p 'cube-dashboard-mode)
        (cube-dashboard--render)))))

(defun cube-agent--request-item (request)
  "Return a visitable detail-buffer item for request bead REQUEST."
  (let* ((state (cube-agent--request-state request))
         (age (cube-agent--request-age request))
         (detail (string-join (delq nil (list state
                                            (unless (string-empty-p age) age))) "  ")))
    (list :type 'request :id (cube-agent--request-id request)
          :label (format "%s  %s" (cube-agent--request-id request)
                         (cube--string (or (cube-get request 'title)
                                           (cube-get request 'text)
                                           (cube-get request 'summary))))
          :detail detail :data request)))

(defun cube-agent--proposals (agent)
  "Return open proposal beads from AGENT."
  (seq-filter
   (lambda (proposal)
     (equal (cube--string (or (cube-get proposal 'kind)
                              (cube-get proposal 'type))) "proposal"))
   (or (cube-get agent 'proposals)
       (cube-get agent 'open_proposals)
       (cube-get agent 'beads))))

(defun cube-agent--journal (agent)
  "Return the recent journal entries from AGENT."
  (seq-take (or (cube-get agent 'journal) (cube-get agent 'journal_entries)) 5))

(defun cube-agent--journal-path (agent entry)
  "Return the host journal path represented by AGENT ENTRY."
  (or (cube-get entry 'path) (cube-get entry 'file)
      (cube-get entry 'journal_file) (cube-get agent 'journal_file)
      (format "agents/%s/memory/journal.md" (cube-agent--name agent))))

(defun cube-agent--session (agent)
  "Return AGENT's session as a display record, or nil."
  (let ((session (cube-get agent 'session)))
    (cond ((stringp session) (list (cons 'name session)
                                   (cons 'state (cube-get agent 'state))))
          ((consp session) session)
          (t nil))))

(defun cube-agent--text-bar (used allowance &optional width)
  "Return a resource bar for USED against ALLOWANCE."
  (let* ((width (or width 12))
         (used (if (numberp used) used 0))
         (allowance (if (and (numberp allowance) (> allowance 0)) allowance 0))
         (ratio (if (> allowance 0) (min 1.0 (/ used allowance)) 0.0))
         (filled (round (* width ratio))))
    (format "[%s%s]" (make-string filled ?#)
            (make-string (- width filled) ?.))))

(defun cube-agent--allowance (resources key)
  "Return resource allowance KEY from RESOURCES, or nil."
  (or (cube-get resources 'allowance key)
      (cube-get resources 'limits key)
      (cube-get resources key)))

(defun cube-agent--resource-lines (agent)
  "Return readable allowance-versus-used lines for AGENT."
  (let* ((resources (cube-get agent 'resources))
         (used (or (cube-get resources 'used_today)
                   (cube-get agent 'resources_used_today)))
         (gpu (cube-agent--allowance resources 'node005_gpu_hours_per_day))
         (spend (cube-agent--allowance resources 'spend_usd_per_day))
         (runs (cube-agent--allowance resources 'runs_per_day)))
    (list
     (format "GPU hours      %s %.1f/%.1f"
             (cube-agent--text-bar (cube-get used 'gpu_hours) gpu)
             (or (cube-get used 'gpu_hours) 0) (or gpu 0))
     (format "Runs           %s %s/%s"
             (cube-agent--text-bar (cube-get used 'runs) runs)
             (or (cube-get used 'runs) 0) (or runs "unlimited"))
     (format "Cloud spend    %s $%.2f/$%.2f"
             (cube-agent--text-bar (cube-get used 'spend_usd) spend)
             (or (cube-get used 'spend_usd) 0) (or spend 0))
     (format "IBEX           %s"
             (cube--string (or (cube-agent--allowance resources 'ibex) "-")))
     (format "WS CPU         %s"
             (if (cube-true-p (cube-agent--allowance resources 'ws_cpu)) "allowed" "-")))))

(defun cube-agent--message-label (message)
  "Return a readable inbox row for MESSAGE."
  (format "%s %s  %s%s"
          (if (cube-agent--unread-p message) "●" "○")
          (cube--string (or (cube-get message 'from) "?"))
          (cube--string (or (cube-get message 'text) (cube-get message 'body)))
          (if-let* ((ts (cube-get message 'ts)))
              (format "  %s" (cube--age-string ts)) "")))

(defun cube-agent--proposal-item (proposal)
  "Return a visitable item for proposal PROPOSAL."
  (list :type 'proposal
        :id (cube--string (or (cube-get proposal 'bead) (cube-get proposal 'id)))
        :label (format "%s  %s" (cube--string (or (cube-get proposal 'bead)
                                                     (cube-get proposal 'id)))
                       (cube--string (or (cube-get proposal 'title)
                                         (cube-get proposal 'summary))))
        :detail (cube--string (or (cube-get proposal 'rationale)
                                  (cube-get proposal 'resources_requested)))
        :data proposal))

(defun cube-agent--journal-item (agent entry)
  "Return a visitable item for journal ENTRY belonging to AGENT."
  (let ((path (cube-agent--journal-path agent entry)))
    (list :type 'journal :id path
          :label (format "%s  %s" (cube--string (or (cube-get entry 'date)
                                                       (cube-get entry 'ts)))
                         (cube--string (or (cube-get entry 'summary)
                                           (cube-get entry 'text))))
          :detail (cube--string (cube-get entry 'path))
          :data entry)))

(defun cube-agent--work-lines (agent)
  "Return the current-work lines for AGENT's detail buffer."
  (if-let* ((work (cube-agent--work agent)))
      (append
       (list (format "state %s  host %s  next tick %s  inbox %s  last workday %s"
                     (cube--string (or (cube-get work 'state) "unknown"))
                     (cube--string (or (cube-get work 'host) "ws"))
                     (cube--string (or (cube-get work 'next_tick) "-"))
                     (cube--string (or (cube-get work 'inbox_unread) 0))
                     (cube--string (or (cube-get work 'last_workday) "never"))))
       (if-let* ((bead (cube--string (cube-get work 'current 'bead)))
                 ((not (string-empty-p bead))))
           (list (format "running %s %s" bead
                         (cube--string (cube-get work 'current 'title))))
         (list "running nothing"))
       (mapcar (lambda (row)
                 (format "assigned %s %s %s"
                         (cube--string (cube-get row 'bead))
                         (cube--string (or (cube-get row 'stage) (cube-get row 'status)))
                         (cube--string (cube-get row 'title))))
               (cube-get work 'assigned)))
    (list "no cube work payload cached; g refreshes the dashboard")))

(defun cube-agent--session-item (agent)
  "Return a visitable item for AGENT's session."
  (when-let* ((session (cube-agent--session agent)))
    (list :type 'agent-session :id (cube--string (cube-get session 'name))
          :label (format "%s  %s" (cube--string (cube-get session 'state))
                         (cube--string (cube-get session 'name)))
          :detail nil :data agent)))

(defun cube-agent--render-text (agent)
  "Return pure readable text for AGENT's detail buffer."
  (with-temp-buffer
    (insert (format "%s %s  %s\nTitle: %s\nTopics: %s\nState: %s\n\n"
                    (cube-agent--kind-glyph agent) (cube-agent--name agent)
                    (cube-agent--kind agent) (cube--string (cube-get agent 'title))
                    (if-let* ((topics (cube-get agent 'topics)))
                        (string-join (mapcar #'cube--string topics) ", ") "-")
                    (cube--string (or (cube-get agent 'state) "unknown"))))
    (insert "Charter\n" (cube--string (cube-get agent 'charter)) "\n\n")
    (insert (format "Inbox (%d)\n" (length (cube-agent--inbox agent))))
    (dolist (message (cube-agent--inbox agent))
      (insert (format "- %s\n" (cube-agent--message-label message))))
    (insert (format "\nRequests (%d)\n" (length (cube-agent--requests agent))))
    (dolist (request (cube-agent--requests agent))
      (insert (format "- %s\n" (plist-get (cube-agent--request-item request) :label))))
    (insert (format "\nProposals (%d)\n" (length (cube-agent--proposals agent))))
    (dolist (proposal (cube-agent--proposals agent))
      (insert (format "- %s\n" (plist-get (cube-agent--proposal-item proposal) :label))))
    (insert (format "\nJournal (%d)\n" (length (cube-agent--journal agent))))
    (dolist (entry (cube-agent--journal agent))
      (insert (format "- %s\n" (plist-get (cube-agent--journal-item agent entry) :label))))
    (insert "\nWork\n")
    (dolist (line (cube-agent--work-lines agent)) (insert "- " line "\n"))
    (insert "\nResources\n")
    (dolist (line (cube-agent--resource-lines agent)) (insert "- " line "\n"))
    (when-let* ((item (cube-agent--session-item agent)))
      (insert "\nSession\n- " (plist-get item :label) "\n"))
    (buffer-string)))

(defvar cube-agent--row-map
  (let ((map (make-sparse-keymap)))
    (define-key map [mouse-1] #'cube-agent-mouse-visit)
    (define-key map [mouse-3] #'cube-agent-mouse-context)
    map)
  "Mouse map applied to agent detail rows.")

(defun cube-agent--item-mouse-properties (start end)
  "Make the row from START to END clickable."
  (add-text-properties start end
                       (list 'mouse-face 'highlight 'keymap cube-agent--row-map
                             'help-echo "RET opens; mouse-3 shows agent actions")))

(defun cube-agent--insert-item (item)
  "Insert visitable agent ITEM."
  (let ((start (point)))
    (magit-insert-section (cube-agent-item item)
      (magit-insert-heading
      (concat "  " (plist-get item :label)
                (let ((detail (or (plist-get item :detail) "")))
                  (if (string-empty-p detail) ""
                    (propertize (concat "  " detail) 'font-lock-face 'shadow))))))
    (cube-agent--item-mouse-properties start (point))))

(defun cube-agent--insert-group (kind title items empty)
  "Insert agent group KIND, TITLE and ITEMS, or EMPTY."
  (magit-insert-section (cube-agent-group kind)
    (magit-insert-heading (format "%s (%d)" title (length items)))
    (if items
        (dolist (item items) (cube-agent--insert-item item))
      (insert "  " empty "\n"))
    (insert "\n")))

(defun cube-agent--insert-charter (agent)
  "Insert AGENT's folded charter section."
  (magit-insert-section (cube-agent-charter nil t)
    (magit-insert-heading "Charter")
    (insert (cube--string (cube-get agent 'charter)) "\n\n")))

(defun cube-agent--render ()
  "Render the current standing-agent detail buffer."
  (when (and cube-agent--agent (derived-mode-p 'cube-agent-mode))
    (let ((inhibit-read-only t)
          (line (line-number-at-pos))
          (column (current-column))
          (agent cube-agent--agent)
          (inbox (mapcar (lambda (message)
                           (list :type 'inbox :id (cube--string (cube-get message 'ts))
                                 :label (cube-agent--message-label message)
                                 :detail nil :data message))
                         (cube-agent--inbox cube-agent--agent)))
          (requests (mapcar #'cube-agent--request-item
                            (cube-agent--requests cube-agent--agent)))
          (proposals (mapcar #'cube-agent--proposal-item
                             (cube-agent--proposals cube-agent--agent)))
          (journal (mapcar (lambda (entry)
                             (cube-agent--journal-item cube-agent--agent entry))
                           (cube-agent--journal cube-agent--agent)))
          (session (cube-agent--session-item cube-agent--agent)))
      (erase-buffer)
      (magit-insert-section (cube-agent-root)
        (magit-insert-heading
          (format "%s %s  %s"
                  (cube-agent--kind-glyph agent) (cube-agent--name agent)
                  (cube--string (cube-get agent 'title))))
        (insert (format "Topics: %s\nState: %s\n"
                        (if-let* ((topics (cube-get agent 'topics)))
                            (string-join (mapcar #'cube--string topics) ", ") "-")
                        (cube--string (or (cube-get agent 'state) "unknown"))))
        (cube-key-legend-insert 'cube-agent-mode)
        (when-let* ((yaml (cube-get agent 'yaml)))
          (insert "\n" yaml "\n"))
        (insert "\n")
        (cube-agent--insert-charter agent)
        (cube-agent--insert-group 'inbox
                                  (format "Inbox%s"
                                          (if (> (seq-count
                                                  #'cube-agent--unread-p
                                                  (cube-agent--inbox agent)) 0)
                                              "  [unread first]" ""))
                                  inbox "empty; t tells this agent")
        (cube-agent--insert-group 'requests "Requests" requests
                                  "no requests addressed to this agent")
        (cube-agent--insert-group 'proposals "Proposals" proposals
                                  "no open proposals")
        (cube-agent--insert-group 'journal "Journal" journal
                                  "no journal entries")
        (magit-insert-section (cube-agent-work)
          (magit-insert-heading "Work")
          (dolist (line (cube-agent--work-lines agent))
            (insert "  " line "\n"))
          (insert "\n"))
        (magit-insert-section (cube-agent-resources)
          (magit-insert-heading "Resources")
          (dolist (line (cube-agent--resource-lines agent))
            (insert "  " line "\n"))
          (insert "\n"))
        (cube-agent--insert-group 'session "Session" (if session (list session) nil)
                                  "no live session"))
      (goto-char (point-min))
      (forward-line (1- line))
      (move-to-column column))))

(defun cube-agent--fetch (name buffer &optional agent)
  "Fetch the detailed standing agent NAME into BUFFER."
  (cube--call-json-async-on
   (cube-agent--transport-host (or agent (cube-agent--find name)))
   (list "agent" "show" name)
   (lambda (json)
     (when (buffer-live-p buffer)
       (with-current-buffer buffer
         (setq cube-agent--agent (cube-agent--object json))
         (cube-agent--render))))
   (lambda (code err) (message "cube: agent %s failed (%s): %s" name code err))))

(defun cube-agent-revert ()
  "Refresh the current standing-agent detail buffer."
  (interactive)
  (unless cube-agent--agent (user-error "cube: not an agent buffer"))
  (cube-agent--fetch (cube-agent--name cube-agent--agent) (current-buffer)
                     cube-agent--agent))

(defun cube-agent-open (agent)
  "Open standing AGENT, an alist or a name, in cube-agent-mode."
  (interactive (list (cube-agent--read-name)))
  (let* ((cached (if (stringp agent) (cube-agent--find agent) agent))
         (name (cube-agent--name (or cached (list (cons 'name agent)))))
         (buffer (get-buffer-create (format "*cube-agent: %s*" name))))
    (with-current-buffer buffer
      (unless (derived-mode-p 'cube-agent-mode) (cube-agent-mode))
      (setq cube-agent--agent
            (or cached (list (cons 'name name) (cons 'title name))))
      (cube-agent--render))
    (pop-to-buffer buffer)
    (cube-agent--fetch name buffer cached)))

(defun cube-agent-visit ()
  "Visit the item at point, or toggle its group."
  (interactive)
  (let* ((section (magit-current-section))
         (value (and section (oref section value))))
    (pcase (and (listp value) (plist-get value :type))
      ('proposal (cube-beads-show (plist-get value :id)))
      ('request
       (cube-agent--mark-request-viewed (plist-get value :data))
       (cube-beads-show (plist-get value :id)))
      ('journal
       (let* ((entry (plist-get value :data))
              (path (cube-agent--journal-path cube-agent--agent entry)))
         (find-file (cube-host-file-name path))
         (when-let* ((line (cube-get entry 'line))) (goto-char (point-min))
           (forward-line (1- line)))))
      ('agent-session (cube-agent-talk nil (cube-agent--name cube-agent--agent)))
      (_ (when section (magit-section-toggle section))))))

(defun cube-agent-approve ()
  "Route the proposal at point to the normal review queue."
  (interactive)
  (let* ((section (magit-current-section))
         (item (and section (oref section value))))
    (unless (eq (plist-get item :type) 'proposal)
      (user-error "cube: select a proposal first"))
    (if-let* ((approval (cube-get (plist-get item :data) 'approval))
              ((not (string-empty-p (cube--string approval)))))
        (cube-review-open (cube--string approval))
      (cube-review-queue))))

(defun cube-agent--mouse-position (event)
  "Return (BUFFER POINT) for agent mouse EVENT, or nil."
  (let* ((posn (event-end event))
         (window (posn-window posn))
         (point (posn-point posn)))
    (when (and (windowp window) (integer-or-marker-p point))
      (list (window-buffer window) point))))

(defun cube-agent-mouse-visit (event)
  "Visit the agent row clicked by mouse-1 EVENT."
  (interactive "e")
  (when-let* ((position (cube-agent--mouse-position event)))
    (with-current-buffer (nth 0 position)
      (goto-char (nth 1 position))
      (cube-agent-visit))))

(defun cube-agent-mouse-context (event)
  "Show command-table actions for the agent row clicked by mouse-3 EVENT."
  (interactive "e")
  (when-let* ((position (cube-agent--mouse-position event)))
    (with-current-buffer (nth 0 position)
      (goto-char (nth 1 position))
      (let* ((section (magit-current-section))
             (value (and section (oref section value)))
             (type (or (plist-get value :type) 'agent))
             (items (cube-menu--context-items type))
             (choice (and items (popup-menu (cons "Agent" items)))))
        (when choice (call-interactively choice))))))

(defvar cube-agent-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map magit-section-mode-map)
    (define-key map (kbd "g") #'cube-agent-revert)
    (define-key map (kbd "RET") #'cube-agent-visit)
    (define-key map (kbd "T") #'cube-agent-talk)
    (define-key map (kbd "t") #'cube-agent-tell)
    (define-key map (kbd "w") #'cube-agent-workday)
    (define-key map (kbd "i") #'cube-agent-inbox)
    (define-key map (kbd "p") #'cube-agent-pause-resume)
    (define-key map (kbd "r") #'cube-agent-report)
    (define-key map (kbd "e") #'cube-agent-edit-charter)
    (define-key map (kbd "a") #'cube-agent-approve)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap of cube-agent-mode.")

(defconst cube-agent-mode-key-help
  '(("RET" . "open") ("t" . "tell") ("i" . "read inbox") ("w" . "workday")
    ("T" . "talk") ("p" . "pause") ("r" . "report") ("e" . "charter")
    ("a" . "approve proposal") ("g" . "refresh"))
  "Key legend of `cube-agent-mode', proved against its keymap by the test suite.")

(cube-key-legend-register 'cube-agent-mode)

(define-derived-mode cube-agent-mode magit-section-mode "cube-agent"
  "Detailed charter, inbox, proposals, journal and resources for one agent."
  (setq-local revert-buffer-function (lambda (&rest _) (cube-agent-revert))))

(provide 'cube-agents)
;;; cube-agents.el ends here
