;;; cube-dashboard.el --- The *cube* overview buffer  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools

;;; Commentary:

;; One buffer that answers "what needs me, what is running, what is
;; ready": Goals (active group objectives), Attention (the loudest items), Fleet (sessions and runs on the
;; host plus local buffers), Projects, Ready work (beads), Students, Papers
;; and Repos.  Ten backend calls run in parallel; each section renders as
;; soon as its data arrives and shows its own age, so a failing command
;; only degrades one section.
;;
;; Every item is a magit-section whose value is a plist (:type :id :data)
;; and RET dispatches on :type through `cube-dashboard-visit-table'.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'magit-section)
(require 'cube-core)
(require 'cube-rolodex)
(require 'cube-server)
(require 'cube-beads)
(require 'cube-org)
(require 'cube-project)
(require 'cube-review)
(require 'cube-decisions)
(require 'cube-goals)
(require 'cube-agents)
(require 'cube-pipeline)

(declare-function magit-status "magit-status" (&optional directory cache))
(declare-function markdown-mode "markdown-mode")
(declare-function cube-cockpit-restore "cube-cockpit")
(declare-function cube-menu--context-items "cube-menu" (type))
(declare-function cube-menu--key-description "cube-menu" (key &optional prefix))
(declare-function cube-doctor "borg-cube" ())

(defcustom cube-dashboard-sections
  '(goals decisions work pipelines attention fleet projects ready students papers literature repos)
  "Sections of the dashboard, in order.
The `work' section answers what the cube is working on: one row per standing
agent and one row per open task.  The older `agents' section is still
available and shows charter-level detail instead."
  :type '(repeat symbol)
  :group 'borg-cube)

(defcustom cube-dashboard-auto-refresh t
  "When non-nil the dashboard refreshes with the attention poll."
  :type 'boolean
  :group 'borg-cube)

(defface cube-banner-p0
  '((((class color) (background light))
     (:background "red3" :foreground "white" :weight bold))
    (((class color) (background dark))
     (:background "#b21818" :foreground "white" :weight bold))
    (t (:weight bold)))
  "Face for a P0 incident banner."
  :group 'borg-cube)

(defface cube-banner-p1
  '((((class color) (background light))
     (:background "orange" :foreground "black" :weight bold))
    (((class color) (background dark))
     (:background "#d97706" :foreground "black" :weight bold))
    (t (:weight bold)))
  "Face for a P1 incident banner."
  :group 'borg-cube)

(defconst cube-dashboard--calls
  '((goals "goals") (decisions "decisions") (work "work") (pipelines "pipeline" "status") (agents "agent" "list") (attention "attention") (status "status") (ready "ready")
    (people "people") (projects "projects") (papers "papers") (literature "literature") (repos "repos")
    (budget "budget"))
  "Backend calls of the dashboard: (KEY . ARGS).")

(defvar cube-dashboard--data nil
  "Alist KEY -> plist (:json :time :error) for each backend call.")

(defvar cube-dashboard--pending nil
  "Keys of the calls still running during a refresh.")

;;;; Normalisers (pure)

(defun cube-dashboard--item (type id label detail data)
  "Build the item plist for TYPE, ID, LABEL, DETAIL and the raw DATA."
  (list :type type :id (cube--string id) :label label :detail detail :data data))

(defun cube-dashboard--severity-rank (severity)
  "Return the sort rank of SEVERITY, lower is louder."
  (pcase severity
    ("high" 0) ("critical" 0) ("normal" 1) ("low" 2) (_ 1)))

(defun cube-dashboard--normalize-attention (item)
  "Return the dashboard item for the attention ITEM.
The :type is the target type (approval, session, bead, file, run)."
  (let* ((target (cube-get item 'target))
         (type (intern (or (cube-get target 'type) (cube-get item 'kind) "attention")))
         (id (or (cube-get target 'id) (cube-get item 'id)))
         (age (cube--age-string (cube-get item 'age))))
    (cube-dashboard--item
     type id
     (format "%s %s" (pcase (cube-get item 'severity) ("high" "!!") ("low" " .") (_ " !"))
             (cube--string (cube-get item 'title)))
     (string-join (delq nil (list (cube-get item 'kind)
                                  (and (not (string-empty-p age)) age)
                                  (let ((actions (cube-get item 'actions)))
                                    (and actions (string-join (mapcar #'cube--string actions) "/")))))
                  "  ")
     item)))

(defun cube-dashboard--loudest (items &optional n)
  "Return the N loudest of the attention ITEMS (default `cube-attention-count').
Ordered by severity; the sort is stable so the backend's own ordering
\(severity, then age) decides ties."
  (seq-take (sort (copy-sequence items)
                  (lambda (a b)
                    (< (cube-dashboard--severity-rank (cube-get a 'severity))
                       (cube-dashboard--severity-rank (cube-get b 'severity)))))
            (or n cube-attention-count)))

(defun cube-dashboard--normalize-session (session)
  "Return the dashboard item for a host SESSION (from `cube status')."
  (let ((name (cube-get session 'name)))
    (cube-dashboard--item
     'session name
     (format "%s %s" (cube-rolodex--state-glyph
                      (or (cube-server--event-state (or (cube-get session 'last_event) ""))
                          'running))
             (cube--string name))
     (string-join (delq nil (list (cube-get session 'kind)
                                  (cube-get session 'last_event)
                                  (let ((age (cube--age-string (cube-get session 'last_event_ts))))
                                    (and (not (string-empty-p age)) age))))
                  "  ")
     session)))

(defun cube-dashboard--normalize-run (run)
  "Return the dashboard item for a headless RUN (from `cube status')."
  (cube-dashboard--item
   'run (cube-get run 'run_id)
   (format "%s %s%s" (if (equal (cube-get run 'state) "running") "●" "○")
           (cube--string (cube-get run 'role))
           (if-let* ((bead (cube-get run 'bead))) (format " on %s" bead) ""))
   (string-join (delq nil (list (cube-get run 'runner) (cube-get run 'model)
                                (cube-get run 'state)
                                (let ((age (cube--age-string (cube-get run 'started))))
                                  (and (not (string-empty-p age)) age))))
                "  ")
   run))

(defun cube-dashboard--normalize-local-session (session)
  "Return the dashboard item for a rolodex SESSION struct."
  (cube-dashboard--item
   'session (cube-session-name session)
   (format "%s %s" (cube-rolodex--state-glyph (cube-session-state session))
           (cube-rolodex--label session))
   (string-join (delq nil (list (symbol-name (cube-session-state session))
                                (cube-session-reason session)
                                (let ((age (cube--age-string (cube-session-last-activity session))))
                                  (and (not (string-empty-p age)) age))))
                "  ")
   session))

(defun cube-dashboard--normalize-bead (bead)
  "Return the dashboard item for a ready BEAD (normalised or raw)."
  (let ((b (if (assq 'stage bead) bead (cube-beads--normalize bead))))
    (cube-dashboard--item
     'bead (alist-get 'id b)
     (format "P%s %s" (cube--string (alist-get 'priority b)) (cube--string (alist-get 'title b)))
     (string-join (delq nil (list (alist-get 'stage b) (alist-get 'kind b)
                                  (alist-get 'student b)
                                  (and (alist-get 'deadline b)
                                       (format "due %s" (alist-get 'deadline b)))))
                  "  ")
     b)))

(defun cube-dashboard--normalize-person (person)
  "Return the dashboard item for PERSON (from `cube people')."
  (let ((milestone (cube-get person 'next_milestone))
        (attention (cube-get person 'attention)))
    (cube-dashboard--item
     'student (cube-get person 'slug)
     (format "%s %s" (if (and (numberp attention) (> attention 0)) "⚠" " ")
             (cube--string (cube-get person 'name)))
     (string-join (delq nil (list (cube-get person 'role)
                                  (and milestone
                                       (format "%s in %s d" (cube-get milestone 'name)
                                               (cube-get milestone 'days)))
                                  (and (cube-get person 'last_meeting)
                                       (format "met %s" (cube-get person 'last_meeting)))))
                  "  ")
     person)))

(defun cube-dashboard--normalize-paper (paper)
  "Return the dashboard item for PAPER (from `cube papers')."
  (cube-dashboard--item
   'paper (cube-get paper 'id)
   (format "%-16s %s" (cube--string (cube-get paper 'state)) (cube--string (cube-get paper 'title)))
   (string-join (delq nil (list (cube-get paper 'venue)
                                (and (cube-get paper 'deadline)
                                     (format "due %s" (cube-get paper 'deadline)))
                                (cube-get paper 'lead)))
                "  ")
   paper))

(defun cube-dashboard--literature-targets (entry)
  "Return the \"for: ...\" text of literature ENTRY, or nil."
  (let ((targets (delq nil (mapcar (lambda (rel)
                                     (let ((kind (cube-get rel 'kind))
                                           (ref (cube-get rel 'ref)))
                                       (and kind ref (format "%s %s" kind ref))))
                                   (append (cube-get entry 'relevance) nil)))))
    (and targets (concat "for: " (string-join targets ", ")))))

(defun cube-dashboard--normalize-literature (entry)
  "Return the dashboard item for the literature ENTRY (from `cube literature')."
  (cube-dashboard--item
   'literature (cube-get entry 'id)
   (format "[%s] %s" (cube--string (cube-get entry 'priority))
           (cube--string (cube-get entry 'title)))
   (string-join (delq nil (list (and (cube-get entry 'source)
                                     (format "(%s)" (cube-get entry 'source)))
                                (cube-dashboard--literature-targets entry)))
                "  ")
   entry))

(defun cube-dashboard--normalize-repo (repo)
  "Return the dashboard item for REPO (from `cube repos')."
  (cube-dashboard--item
   'repo (cube-get repo 'name)
   (format "%s %s" (if (cube-true-p (cube-get repo 'dirty)) "*" " ") (cube--string (cube-get repo 'name)))
   (string-join (delq nil (list (cube-get repo 'branch)
                                (let ((ahead (or (cube-get repo 'ahead) 0))
                                      (behind (or (cube-get repo 'behind) 0)))
                                  (and (or (> ahead 0) (> behind 0))
                                       (format "+%d/-%d" ahead behind)))
                                (let ((prs (cube-get repo 'open_prs)))
                                  (and (numberp prs) (> prs 0) (format "%d PR" prs)))
                                (and (cube-get repo 'ci) (format "ci %s" (cube-get repo 'ci)))
                                (and (cube-get repo 'audit_bead)
                                     (format "audit %s" (cube-get repo 'audit_bead)))))
                "  ")
   repo))

(defun cube-dashboard--normalize-project (project &optional people now)
  "Return the dashboard item for PROJECT, using PEOPLE and NOW when given."
  (cube-project--row project people now))

(defun cube-dashboard--normalize-agent (agent &optional now)
  "Return the dashboard item for standing AGENT, using NOW for journal age."
  (cube-agent--row-item agent now))

(defun cube-dashboard--work-state-glyph (state)
  "Return the one-glyph marker for an agent STATE from `cube work'."
  (pcase state
    ("running" "●")
    ("paused" "‖")
    ("killed" "✗")
    (_ "○")))

(defun cube-dashboard--work-model (model)
  "Return the short display name of MODEL, dropping any provider prefix."
  (let ((text (cube--string model)))
    (if (string-empty-p text) "" (car (last (split-string text "/"))))))

(defun cube-dashboard--work-current-text (agent &optional now)
  "Return the running-work fragment of AGENT's work row, using NOW for the age."
  (let* ((current (cube-get agent 'current))
         (bead (cube--string (cube-get current 'bead)))
         (stage (cube--string
                 (cube-get (seq-find (lambda (row)
                                       (equal (cube--string (cube-get row 'bead)) bead))
                                     (cube-get agent 'assigned))
                           'stage)))
         (age (cube--age-string (cube-get current 'since) now))
         (model (cube-dashboard--work-model (cube-get current 'model)))
         (detail (string-join (seq-remove #'string-empty-p (list age model)) ", ")))
    (if (string-empty-p bead)
        ""
      (concat " " bead
              (if (string-empty-p stage) "" (concat " " stage))
              (if (string-empty-p detail) "" (format " (%s)" detail))))))

(defun cube-dashboard--work-agent-text (agent &optional now)
  "Return the dashboard row text for AGENT from the `cube work' payload."
  (let* ((state (cube--string (or (cube-get agent 'state) "idle")))
         (tick (cube--string (or (cube-get agent 'next_tick) "-")))
         (runs (or (cube-get agent 'today 'runs) 0)))
    (format "%s %-14s %-7s %-7s %s%-8s%s  inbox %d  today %d run%s"
            (cube-agent--kind-glyph agent)
            (cube-agent--name agent)
            (cube--string (or (cube-get agent 'host) "ws"))
            tick
            (cube-dashboard--work-state-glyph state)
            state
            (if (equal state "not-due")
                (format " next %s" tick)
              (cube-dashboard--work-current-text agent now))
            (or (cube-get agent 'inbox_unread) 0)
            runs
            (if (= runs 1) "" "s"))))

(defun cube-dashboard--normalize-work-agent (agent &optional now)
  "Return the dashboard item for the `cube work' AGENT row."
  (list :type 'agent :id (cube-agent--name agent)
        :label (cube-dashboard--work-agent-text agent now) :detail nil :data agent))

(defun cube-dashboard--work-task-text (task)
  "Return the dashboard row text for the `cube work' TASK row."
  (format "%s %-12s %-12s %-18s %-40s %s"
          (if (cube-true-p (cube-get task 'running)) "●" "○")
          (cube--string (cube-get task 'bead))
          (cube--string (or (cube-get task 'stage) (cube-get task 'status)))
          (cube--string (or (cube-get task 'owner) "-"))
          (truncate-string-to-width (cube--string (cube-get task 'title)) 40)
          (if-let* ((due (cube-get task 'deadline)))
              (format "due %s" (cube--string due))
            "")))

(defun cube-dashboard--normalize-work-task (task)
  "Return the dashboard item for the `cube work' TASK row."
  (list :type 'bead :id (cube--string (cube-get task 'bead))
        :label (cube-dashboard--work-task-text task) :detail nil :data task))

(defun cube-dashboard--work-agents (json)
  "Return the agent rows of the `cube work' payload JSON."
  (cube-get json 'agents))

(defun cube-dashboard--work-tasks (json)
  "Return the task rows of the `cube work' payload JSON."
  (cube-get json 'tasks))

;;;; Data

(defun cube-dashboard--entry (key)
  "Return the data plist stored for KEY."
  (alist-get key cube-dashboard--data))

(defun cube-dashboard--json (key)
  "Return the JSON stored for KEY, or nil."
  (plist-get (cube-dashboard--entry key) :json))

(defun cube-dashboard--store (key json error)
  "Record JSON or ERROR for KEY with the current time."
  (setf (alist-get key cube-dashboard--data)
        (list :json (or json (plist-get (cube-dashboard--entry key) :json))
              :time (current-time) :error error))
  (when (and (eq key 'attention) json)
    (cube-attention-set-items json))
  (when (and (eq key 'status) json)
    (cube-status-set-json json))
  (when (and (eq key 'agents) json)
    (cube-agents--set-cache json))
  (when (and (eq key 'work) json)
    (cube-agent--set-work-cache json))
  (when (and (eq key 'pipelines) json)
    (cube-pipeline--set-cache json))
  (when (and (eq key 'decisions) json)
    ;; the dashboard renders right after this; do not let the shared cache
    ;; hook render it a second time
    (let ((cube-decisions-update-hook nil)) (cube-decisions-set-json json))))

;;;; Banner and budget formatting (pure)

(defun cube-dashboard--select-banner (status)
  "Return the incident banner selected by STATUS, or nil.
The backend has already selected the loudest open incident.  Validate the
severity here so malformed or P2-only payloads never become a banner."
  (let ((banner (cube-get status 'incidents 'banner)))
    (when (and (consp banner)
               (member (cube-get banner 'severity) '("p0" "p1")))
      banner)))

(defun cube-dashboard--banner-text (banner)
  "Return the display text for incident BANNER."
  (let ((severity (upcase (or (cube-get banner 'severity) "incident")))
        (text (or (cube-get banner 'text) "Incident requires attention"))
        (count (cube-get banner 'count)))
    (format "%s  %s%s" severity text
            (if (and (numberp count) (> count 1))
                (format "  (%d incidents)" count)
              ""))))

(defun cube-dashboard--banner-face (banner)
  "Return the face symbol for incident BANNER."
  (if (equal (cube-get banner 'severity) "p0") 'cube-banner-p0 'cube-banner-p1))

(defun cube-dashboard--percent (value)
  "Return VALUE as a bounded integer percentage, or nil."
  (when (numberp value) (max 0 (min 100 (round value)))))

(defun cube-dashboard--budget-label (tier)
  "Return the compact display label for TIER."
  (alist-get tier '((plan . "plan") (implement . "impl")
                   (bulk . "bulk") (local . "local"))))

(defun cube-dashboard--until-text (until)
  "Return the local time portion of ISO UNTIL, or UNTIL itself."
  (if (and (stringp until) (not (string-empty-p until)))
      (condition-case nil
          (format-time-string "%H:%M" (encode-time (iso8601-parse until)))
        (error until))
    ""))

(defun cube-dashboard--budget-runner (runner budget-json)
  "Return RUNNER's detail from the parsed `cube budget' BUDGET-JSON."
  (cube-get budget-json 'runners runner))

(defun cube-dashboard--exhausted-text (exhausted budget-json)
  "Return display text for EXHAUSTED runners using BUDGET-JSON until times."
  (mapconcat
   (lambda (value)
     (let* ((runner (if (consp value) (cube-get value 'runner) value))
            (detail (and runner
                         (cube-dashboard--budget-runner
                          (if (symbolp runner) runner (intern runner)) budget-json)))
            (until (or (and (consp value) (cube-get value 'until))
                       (cube-get detail 'until))))
       (format "%s exhausted%s" (cube--string runner)
               (if until (format " until %s" (cube-dashboard--until-text until)) ""))))
   exhausted ", "))

(defun cube-dashboard--budget-segment (budget &optional budget-json)
  "Return the header budget segment for STATUS BUDGET.
Tier percentages at or above 90 are warning-faced.  BUDGET-JSON supplies
runner exhaustion times, which are not duplicated in `status.budget'."
  (when (consp budget)
    (let ((parts nil))
      (dolist (tier '(plan implement bulk local))
        (let ((pct (cube-dashboard--percent (cube-get budget tier))))
          (when pct
            (push (propertize (format "%s %d%%" (cube-dashboard--budget-label tier) pct)
                              'face (and (>= pct 90) 'warning))
                  parts))))
      (setq parts (nreverse parts))
      (let ((exhausted (cube-get budget 'exhausted)))
        (when exhausted
          (push (cube-dashboard--exhausted-text exhausted budget-json) parts)))
      (when parts (concat "   " (string-join parts " "))))))

(defun cube-dashboard--peer-text (peer)
  "Return the compact header text for one status PEER."
  (let* ((name (cube--string (cube-get peer 'name)))
         (reachable (cube-true-p (cube-get peer 'reachable)))
         (pull-only (equal (cube--string (cube-get peer 'route)) "none"))
         (sha (cube--string (cube-get peer 'sha)))
         (lag (cube-get peer 'lag_commits)))
    (string-join
     (delq nil
           (list name
                 (cond (pull-only "pull-only")
                       (reachable "✓")
                       (t "⊘ unreachable"))
                 (unless (string-empty-p sha) sha)
                 (when (and (numberp lag) (> lag 0)) (format "lag %d" lag))))
     " ")))

(defun cube-dashboard--peers-segment (status)
  "Return the status header's peer-health segment, or the empty string."
  (when-let* ((peers (cube-get status 'peers)))
    (concat "   peers: "
            (string-join (mapcar #'cube-dashboard--peer-text peers) "  "))))

(defun cube-dashboard--header-text (status)
  "Return the full dashboard header text for STATUS."
  (concat
   (format "borg-cube on %s" (or cube-remote-host "this machine"))
   (when-let* ((missing (cube--status-missing-commands status)))
     (propertize (format "  [host lacks: %s]" (string-join missing ", "))
                 'face 'error))
   (let* ((counts (cube-get status 'counts))
          (count-text
           (if counts
               (propertize (format "   attention %s  ready %s  running %s  approvals %s"
                                   (cube--string (cube-get counts 'attention))
                                   (cube--string (cube-get counts 'ready))
                                   (cube--string (cube-get counts 'running))
                                   (cube--string (cube-get counts 'approvals)))
                           'font-lock-face 'shadow)
             "")))
     (concat count-text
             (cube-dashboard--budget-segment
              (cube-get status 'budget) (cube-dashboard--json 'budget))))
   (cube-dashboard--peers-segment status)))

(defun cube-dashboard--text-bar (pct &optional width)
  "Return a small text bar for PCT with WIDTH cells."
  (let* ((width (or width 10))
         (pct (cube-dashboard--percent pct)))
    (if (null pct)
        (format "[%s]" (make-string width ?.))
      (let ((filled (round (* width (/ pct 100.0)))))
        (format "[%s%s]" (make-string filled ?#)
                (make-string (- width filled) ?.))))))

(defun cube-dashboard--budget-tier-line (tier data)
  "Return one display line for budget TIER DATA."
  (let ((pct (cube-dashboard--percent (cube-get data 'pct))))
    (format "  %-10s %s %s"
            (symbol-name tier) (cube-dashboard--text-bar pct)
            (if pct (format "%3d%%" pct) "  --"))))

(defun cube-dashboard--budget-runner-line (runner data)
  "Return one display line for budget RUNNER DATA."
  (format "  %-10s %-10s%s%s"
          (symbol-name runner)
          (cube--string (cube-get data 'state))
          (if-let* ((until (cube-get data 'until)))
              (format " until %s" (cube-dashboard--until-text until)) "")
          (if-let* ((reason (cube-get data 'reason)))
              (format "  %s" reason) "")))

(defun cube-dashboard--budget-lines (json)
  "Return the pure display lines for parsed BUDGET JSON."
  (let ((lines nil))
    (dolist (pair (cube-get json 'tiers))
      (push (cube-dashboard--budget-tier-line (car pair) (cdr pair)) lines))
    (setq lines (nreverse lines))
    (append lines
            (mapcar (lambda (pair)
                      (cube-dashboard--budget-runner-line (car pair) (cdr pair)))
                    (cube-get json 'runners)))))

(defun cube-dashboard--status-line (key)
  "Return the age or failure label for dashboard section KEY.
Failures include their age and use the error face, so a section can never be
mistaken for a still-running refresh after its bounded backend call ended."
  (let ((entry (cube-dashboard--entry key)))
    (cond ((null entry) "  (loading)")
          ((plist-get entry :error)
           (propertize
            (format "  [%s]  (%s)" (plist-get entry :error)
                    (cube--age-string (plist-get entry :time)))
            'face 'error))
          ((memq key cube-dashboard--pending) "  (refreshing)")
          (t (format "  (%s)" (cube--age-string (plist-get entry :time)))))))

(defun cube-dashboard-refresh ()
  "Refetch every section in parallel; each redraws when its data arrives."
  (interactive)
  (setq cube-dashboard--pending (mapcar #'car cube-dashboard--calls))
  (dolist (call cube-dashboard--calls)
    (let ((key (car call)) (args (cdr call)))
      (cube--call-json-async
       args
       (lambda (json)
         (setq cube-dashboard--pending (delq key cube-dashboard--pending))
         (cube-dashboard--store key json nil)
         (cube-dashboard--render))
       (lambda (code err)
         (setq cube-dashboard--pending (delq key cube-dashboard--pending))
         (cube-dashboard--store
          key nil
          (if (string-match-p "\\`\\(?:ssh:\\|cube:\\)" err)
              err
            (format "%s failed (%s): %s" (car args) code
                    (truncate-string-to-width err 60 nil nil "..."))))
         (cube-dashboard--render))))))

;;;; Rendering

(defun cube-dashboard--mouse-position (event)
  "Return (BUFFER POINT) for dashboard mouse EVENT, or nil."
  (let* ((posn (event-end event))
         (window (posn-window posn))
         (point (posn-point posn)))
    (when (and (windowp window) (integer-or-marker-p point))
      (list (window-buffer window) point))))

(defun cube-dashboard-mouse-doctor (_event)
  "Run the cockpit doctor when the dashboard header is clicked."
  (interactive "e")
  (cube-doctor))

(defvar cube-dashboard--header-map
  (let ((map (make-sparse-keymap)))
    (define-key map [mouse-1] #'cube-dashboard-mouse-doctor)
    map)
  "Mouse map on the dashboard header's peer and transport health summary.")

(defun cube-dashboard-mouse-visit (event)
  "Open the dashboard row clicked by mouse-1 EVENT."
  (interactive "e")
  (pcase (cube-dashboard--mouse-position event)
    (`(,buffer ,point)
     (with-current-buffer buffer
       (goto-char point)
       (when-let* ((item (get-text-property (point) 'cube-dashboard-item)))
         (cube-dashboard-visit-item item))))))

(defun cube-dashboard-mouse-context (event)
  "Open the dashboard row context menu clicked by mouse-3 EVENT."
  (interactive "e")
  (pcase (cube-dashboard--mouse-position event)
    (`(,buffer ,point)
     (with-current-buffer buffer
       (goto-char point)
       (when-let* ((item (get-text-property (point) 'cube-dashboard-item))
                   (type (plist-get item :type))
                   (actions (cube-menu--context-items type))
                   (choice (x-popup-menu event
                                         (list "Cube item"
                                               (cons "Actions" actions)))))
         (call-interactively choice))))))

(defvar cube-dashboard--item-map
  (let ((map (make-sparse-keymap)))
    (define-key map [mouse-1] #'cube-dashboard-mouse-visit)
    (define-key map [mouse-3] #'cube-dashboard-mouse-context)
    map)
  "Mouse map installed on visitable dashboard rows.")

(defun cube-dashboard--item-mouse-properties (start end item)
  "Make the text from START to END a clickable dashboard ITEM.
Text that is already a button (a decision's [Yes]/[No]) keeps its own
keymap, so clicking the button answers instead of opening the row."
  (add-text-properties
   start end
   (list 'mouse-face 'highlight
         'help-echo (format "%s" (plist-get item :label))
         'cube-dashboard-item item))
  (let ((pos start))
    (while (< pos end)
      (let ((next (or (next-single-property-change pos 'button nil end) end)))
        (unless (get-text-property pos 'button)
          (put-text-property pos next 'keymap cube-dashboard--item-map))
        (setq pos next)))))

(defun cube-dashboard--insert-item (item)
  "Insert ITEM as a one line section."
  (let ((start (point)))
    (magit-insert-section (cube-item item)
      (magit-insert-heading
        (concat "  " (plist-get item :label)
                (let ((detail (plist-get item :detail)))
                  (if (and detail (not (string-empty-p detail)))
                      (propertize (concat "   " detail) 'font-lock-face 'shadow)
                    ""))))
    (cube-dashboard--item-mouse-properties start (point) item))))

(defun cube-dashboard--insert-group (type title status items &optional empty count)
  "Insert the group section TYPE titled TITLE with STATUS and ITEMS.
EMPTY is the text shown when ITEMS is nil.  COUNT overrides the number in
the heading, for a section that shows only its first rows."
  (magit-insert-section (cube-group type)
    (magit-insert-heading
      (propertize (format "%s (%d)" title (or count (length items)))
                  'font-lock-face 'magit-section-heading)
      (if (get-text-property 0 'face status)
          status
        (propertize status 'font-lock-face 'shadow)))
    (if items
        (dolist (item items) (cube-dashboard--insert-item item))
      (insert "  " (or empty "nothing") "\n"))
    (insert "\n")))

(defun cube-dashboard--insert-banner (banner)
  "Insert incident BANNER as the first line below the dashboard header."
  (let ((item (list :type 'incident :id (cube--string (cube-get banner 'bead))
                    :label (cube-dashboard--banner-text banner)
                    :detail nil :data banner)))
    (let ((start (point)))
      (magit-insert-section (cube-banner item)
        (magit-insert-heading
          (propertize (concat "  " (plist-get item :label) "\n")
                      'face (cube-dashboard--banner-face banner))))
      (cube-dashboard--item-mouse-properties start (point) item))))

(defun cube-dashboard--insert-transport-banner ()
  "Insert the one-line actionable banner for an unreachable remote host."
  (when-let* ((text (cube--remote-unreachable-message)))
    (magit-insert-heading
      (propertize (concat "  " text "\n") 'face 'error))))

(defun cube-dashboard--insert-budget (json)
  "Insert the tier and runner rows from BUDGET JSON."
  (let ((tiers (cube-get json 'tiers))
        (runners (cube-get json 'runners)))
    (magit-insert-section (cube-group 'budget)
      (magit-insert-heading
        (propertize (format "Budget (%d tiers, %d runners)"
                            (length tiers) (length runners))
                    'font-lock-face 'magit-section-heading)
        (let ((status (cube-dashboard--status-line 'budget)))
          (if (get-text-property 0 'face status)
              status
            (propertize status 'font-lock-face 'shadow))))
      (if (or tiers runners)
          (progn
            (dolist (pair tiers)
              (magit-insert-section (cube-budget-tier (car pair))
                (insert (cube-dashboard--budget-tier-line (car pair) (cdr pair)) "\n")))
            (dolist (pair runners)
              (magit-insert-section (cube-budget-runner (car pair))
                (insert (cube-dashboard--budget-runner-line (car pair) (cdr pair)) "\n"))))
        (insert "  no budget data\n"))
      (insert "\n"))))

(defun cube-dashboard--attention-items ()
  "Return the attention items to show."
  (mapcar #'cube-dashboard--normalize-attention
          (cube-dashboard--loudest (cube-get (cube-dashboard--json 'attention) 'items))))

(defun cube-dashboard--decision-items ()
  "Return the first `cube-decisions-count' pending decisions as dashboard rows."
  (mapcar (lambda (item)
            (cube-dashboard--item
             'decision (cube-decisions--id item)
             (concat (cube-decisions--buttons-string item) "  "
                     (cube-decisions--row-text item))
             (cube-decisions--kind item)
             item))
          (seq-take cube-decisions--items cube-decisions-count)))


(defun cube-dashboard--fleet-items ()
  "Return the fleet items: host sessions and runs, then local-only sessions."
  (let* ((status (cube-dashboard--json 'status))
         (host-sessions (cube-get status 'sessions))
         (host-names (mapcar (lambda (s) (cube-get s 'name)) host-sessions))
         (local (seq-remove (lambda (s) (member (cube-session-name s) host-names))
                            (cube-rolodex--ordered (cube-rolodex-live-sessions)))))
    (append (mapcar #'cube-dashboard--normalize-session host-sessions)
            (mapcar #'cube-dashboard--normalize-run (cube-get status 'runs))
            (mapcar #'cube-dashboard--normalize-local-session local))))

(defun cube-dashboard--project-items ()
  "Return sorted project rows from the projects and people sections."
  (cube-project--row-items (cube-dashboard--json 'projects)
                           (cube-get (cube-dashboard--json 'people) 'people)))

(defun cube-dashboard--goal-items ()
  "Return active goal rows from the cached goals dashboard section."
  (mapcar #'cube-goal--row-item
          (seq-filter #'cube-goal--active-p
                      (cube-goals--list (cube-dashboard--json 'goals)))))

(defun cube-dashboard--pipeline-items ()
  "Return research-pipeline rows from the shared status response."
  (mapcar #'cube-pipeline--row-item
          (cube-pipeline--pipelines (cube-dashboard--json 'pipelines))))

(defun cube-dashboard--work-agent-items ()
  "Return one row per standing agent from the cached `cube work' payload."
  (mapcar #'cube-dashboard--normalize-work-agent
          (cube-dashboard--work-agents (cube-dashboard--json 'work))))

(defun cube-dashboard--work-task-items ()
  "Return one row per open task from the cached `cube work' payload."
  (mapcar #'cube-dashboard--normalize-work-task
          (cube-dashboard--work-tasks (cube-dashboard--json 'work))))

(defun cube-dashboard--agent-items ()
  "Return standing-agent rows from the cached agent list."
  (mapcar #'cube-dashboard--normalize-agent
          (cube-agents--list (cube-dashboard--json 'agents))))

(defun cube-dashboard--render ()
  "Redraw the *cube* buffer from `cube-dashboard--data'."
  (when-let* ((buffer (get-buffer "*cube*")))
    (with-current-buffer buffer
      (let ((inhibit-read-only t)
            (line (line-number-at-pos))
            (col (current-column))
            header-start header-end)
        (erase-buffer)
        (magit-insert-section (cube-dashboard-root)
          (setq header-start (point))
          (progn
            (magit-insert-heading
              (cube-dashboard--header-text (cube-dashboard--json 'status)))
            (setq header-end (point)))
          (insert "\n")
          (cube-key-legend-insert 'cube-dashboard-mode)
          (insert "\n")
          (when (cube--remote-unreachable-p)
            (cube-dashboard--insert-transport-banner)
            (insert "\n"))
          (when-let* ((banner (cube-dashboard--select-banner
                               (cube-dashboard--json 'status))))
            (cube-dashboard--insert-banner banner)
            (insert "\n"))
          (dolist (section (cons 'goals (delq 'goals (copy-sequence cube-dashboard-sections))))
            (pcase section
              ('goals
               (cube-dashboard--insert-group
                'goals "Goals" (cube-dashboard--status-line 'goals)
                (cube-dashboard--goal-items) "no active goals"))
              ('decisions
               (cube-dashboard--insert-group
                'decisions "Decisions" (cube-dashboard--status-line 'decisions)
                (cube-dashboard--decision-items) "nothing to decide"
                (length cube-decisions--items)))
              ('work
               (cube-dashboard--insert-group
                'work-agents "Agents" (cube-dashboard--status-line 'work)
                (cube-dashboard--work-agent-items) "no standing agents")
               (cube-dashboard--insert-group
                'work-tasks "Tasks" (cube-dashboard--status-line 'work)
                (cube-dashboard--work-task-items) "no open tasks"))
              ('pipelines
               (cube-dashboard--insert-group
                'pipelines "Pipelines" (cube-dashboard--status-line 'pipelines)
                (cube-dashboard--pipeline-items) "no research pipelines"))
              ('agents
               (cube-dashboard--insert-group
                'agents "Agents" (cube-dashboard--status-line 'agents)
                (cube-dashboard--agent-items) "no standing agents"))
              ('attention
               (cube-dashboard--insert-group
                'attention "Attention" (cube-dashboard--status-line 'attention)
                (cube-dashboard--attention-items) "nothing needs you"))
              ('fleet
               (cube-dashboard--insert-group
                'fleet "Fleet" (cube-dashboard--status-line 'status)
                (cube-dashboard--fleet-items) "no sessions or runs"))
              ('projects
               (cube-dashboard--insert-group
                'projects "Projects" (cube-dashboard--status-line 'projects)
                (cube-dashboard--project-items) "no projects"))
              ('ready
               (cube-dashboard--insert-group
                'ready "Ready work" (cube-dashboard--status-line 'ready)
                (mapcar #'cube-dashboard--normalize-bead
                        (cube-beads--normalize-list (cube-dashboard--json 'ready)))
                "no ready beads"))
              ('students
               (cube-dashboard--insert-group
                'students "Students" (cube-dashboard--status-line 'people)
                (mapcar #'cube-dashboard--normalize-person
                        (cube-get (cube-dashboard--json 'people) 'people))
                "no people"))
              ('papers
               (cube-dashboard--insert-group
                'papers "Papers" (cube-dashboard--status-line 'papers)
                (mapcar #'cube-dashboard--normalize-paper
                        (cube-get (cube-dashboard--json 'papers) 'papers))
                "no papers"))
              ('literature
               (cube-dashboard--insert-group
                'literature "Literature" (cube-dashboard--status-line 'literature)
                (mapcar #'cube-dashboard--normalize-literature
                        (cube-get (cube-dashboard--json 'literature) 'entries))
                "no new relevant preprints"))
              ('repos
               (cube-dashboard--insert-group
                'repos "Repos" (cube-dashboard--status-line 'repos)
                (mapcar #'cube-dashboard--normalize-repo
                        (cube-get (cube-dashboard--json 'repos) 'repos))
                "no repos"))
              ('budget
               (cube-dashboard--insert-budget (cube-dashboard--json 'budget))))))
        ;; `magit-insert-section' installs its heading map on exit, so this
        ;; must run after the root section has finished rather than alongside
        ;; `magit-insert-heading' above.
        (add-text-properties
         header-start header-end
         (list 'mouse-face 'highlight 'keymap cube-dashboard--header-map
               'help-echo "mouse-1: run cube doctor --cockpit"))
        (goto-char (point-min))
        (forward-line (1- line))
        (move-to-column col)))))

;;;; Dispatch

(defun cube-dashboard--visit-session (id data)
  "Visit session ID: its rolodex buffer, or offer to attach.  DATA is unused."
  (ignore data)
  (let ((session (cube-rolodex-find id)))
    (cond ((and session (buffer-live-p (cube-session-buffer session)))
           (cube-rolodex--show (cube-session-buffer session)))
          (cube-remote-host
           (when (y-or-n-p (format "Attach to tmux %s%s? " cube-tmux-session-prefix id))
             (cube-rolodex-attach id)))
          (t (message "cube: session %s has no buffer here" id)))))

(defun cube-dashboard--visit-bead (id _data)
  "Show bead ID."
  (cube-beads-show id))

(defun cube-dashboard--visit-student (id _data)
  "Open the org file of student ID."
  (cube-org-open-person id))

(defun cube-dashboard--visit-paper (_id data)
  "Open the paper DATA: org heading, else directory."
  (cube-org-open-paper data))

(defun cube-dashboard--visit-repo (_id data)
  "Open repo DATA with magit locally, or dired."
  (let ((path (cube-host-file-name (or (cube-get data 'path)
                                       (user-error "cube: repo has no path")))))
    (if (and (null cube-remote-host) (fboundp 'magit-status))
        (magit-status path)
      (dired path))))

(defun cube-dashboard--visit-project (id data)
  "Open project ID, using its dashboard DATA."
  (cube-project-open id data))

(defun cube-dashboard--visit-goal (id data)
  "Open goal ID, using its dashboard DATA while the full payload loads."
  (cube-goal-open (or data id)))

(defun cube-dashboard--visit-pipeline (id data)
  "Open pipeline ID, retaining dashboard DATA while full status loads."
  (cube-pipeline-show (or data id)))

(defun cube-dashboard--visit-agent (id data)
  "Open standing agent ID, using dashboard DATA while its show loads."
  (cube-agent-open (or data id)))

(defun cube-dashboard--run-log-text (json)
  "Return the text shown for the `cube runs show' payload JSON."
  (with-temp-buffer
    (dolist (key '(run_id role bead runner model state started finished exit log notes_file))
      (let ((v (cube-get json key)))
        (when v (insert (format "%-11s %s\n" (concat (symbol-name key) ":") (cube--string v))))))
    (when-let* ((summary (cube-get json 'summary)))
      (insert "\n" summary "\n"))
    (when-let* ((tail (cube-get json 'log_tail)))
      (insert "\nLog tail:\n")
      (dolist (line tail) (insert (cube--string line) "\n")))
    (when-let* ((notes (cube-get json 'notes)))
      (insert "\nNotes:\n\n" notes "\n"))
    (buffer-string)))

(defun cube-dashboard--show-run-log (id text)
  "Show TEXT in the *cube-run-log: ID* buffer."
  (with-current-buffer (get-buffer-create (format "*cube-run-log: %s*" id))
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert text)
      (goto-char (point-min)))
    (if (require 'markdown-mode nil t) (markdown-mode) (text-mode))
    (view-mode 1)
    (pop-to-buffer (current-buffer))))

(defun cube-dashboard--visit-run (id data)
  "Show the log of run ID: `cube runs show', else the log file in DATA."
  (cube--call-json-async
   (list "runs" "show" id)
   (lambda (json) (cube-dashboard--show-run-log id (cube-dashboard--run-log-text json)))
   (lambda (_code _err)
     (let ((file (or (cube-get data 'log) (format "runs/%s/log.jsonl" id))))
       (if-let* ((text (cube-host-file-contents file)))
           (cube-dashboard--show-run-log id text)
         (message "cube: no log for run %s" id))))))

(defun cube-dashboard--visit-approval (id _data)
  "Open approval ID in the review queue."
  (cube-review-open id))

(defun cube-dashboard--visit-decision (_id data)
  "Open the bead or approval behind decision DATA."
  (if (equal (cube-decisions--kind data) "approval")
      (cube-review-open (cube-decisions--id data))
    (if-let* ((bead (cube-decisions--bead data)))
        (cube-beads-show bead)
      (message "cube: this decision has nothing to open"))))

(defun cube-dashboard--visit-incident (id _data)
  "Open the bead behind incident ID."
  (if (string-empty-p id)
      (message "cube: incident has no bead")
    (cube-beads-show id)))

(defun cube-dashboard--visit-file (id data)
  "Open the file ID (a host path) at the line in DATA."
  (cube-open-file id (cube-get data 'target 'line)))

(defun cube-dashboard--visit-literature (_id _data)
  "Open today's literature digest markdown."
  (let ((path (cube-get (cube-dashboard--json 'literature) 'path)))
    (if path
        (cube-open-file path)
      (message "cube: no literature digest for today"))))

(defvar cube-dashboard-visit-table
  '((session . cube-dashboard--visit-session)
    (bead . cube-dashboard--visit-bead)
    (student . cube-dashboard--visit-student)
    (paper . cube-dashboard--visit-paper)
    (literature . cube-dashboard--visit-literature)
    (repo . cube-dashboard--visit-repo)
    (project . cube-dashboard--visit-project)
    (goal . cube-dashboard--visit-goal)
    (pipeline . cube-dashboard--visit-pipeline)
    (agent . cube-dashboard--visit-agent)
    (run . cube-dashboard--visit-run)
    (approval . cube-dashboard--visit-approval)
    (decision . cube-dashboard--visit-decision)
    (incident . cube-dashboard--visit-incident)
    (file . cube-dashboard--visit-file))
  "Item :type to visit function (ID DATA).")

(defun cube-dashboard--visit-function (type)
  "Return the visit function for item TYPE, or nil."
  (alist-get type cube-dashboard-visit-table))

(defun cube-dashboard-visit-item (item)
  "Visit ITEM (a plist with :type :id :data)."
  (let ((fn (cube-dashboard--visit-function (plist-get item :type))))
    (if fn
        (funcall fn (plist-get item :id) (plist-get item :data))
      (user-error "cube: do not know how to open a %s" (plist-get item :type)))))

(defun cube-dashboard--current-item ()
  "Return the item plist at point, or nil on a group heading."
  (when-let* ((section (magit-current-section)))
    (let ((value (oref section value)))
      (and (listp value) (plist-get value :type) value))))

(defun cube-dashboard--require-item (&rest types)
  "Return the item at point, which must be of one of TYPES when given."
  (let ((item (or (cube-dashboard--current-item) (user-error "cube: no item at point"))))
    (when (and types (not (memq (plist-get item :type) types)))
      (user-error "cube: this needs a %s item" (mapconcat #'symbol-name types " or ")))
    item))

(defun cube-dashboard-visit ()
  "Open the item at point; on a group heading toggle it."
  (interactive)
  (if-let* ((item (cube-dashboard--current-item)))
      (cube-dashboard-visit-item item)
    (when-let* ((section (magit-current-section)))
      (magit-section-toggle section))))

;;;; Item commands

(defun cube-dashboard--decision-at-point ()
  "Return the decision at point, or nil when the row is something else."
  (let ((item (cube-dashboard--current-item)))
    (and (eq (plist-get item :type) 'decision) (plist-get item :data))))

(defun cube-dashboard-approve ()
  "Approve the approval at point, or answer the decision at point."
  (interactive)
  (if (cube-dashboard--decision-at-point)
      (cube-decisions-answer)
    (let ((item (cube-dashboard--require-item 'approval)))
      (cube-review-approve-id (plist-get item :id)))))

(defun cube-dashboard-yes ()
  "Answer the decision at point affirmatively, or approve the approval at point."
  (interactive)
  (if (cube-dashboard--decision-at-point)
      (cube-decisions-yes)
    (let ((item (cube-dashboard--require-item 'approval)))
      (cube-review-approve-id (plist-get item :id)))))

(defun cube-dashboard-no ()
  "Answer the decision at point negatively, else move to the next section.
`n' stays magit's forward motion everywhere except on a decision row."
  (interactive)
  (if (cube-dashboard--decision-at-point)
      (cube-decisions-no)
    (magit-section-forward)))

(defun cube-dashboard-reject ()
  "Reject the approval at point."
  (interactive)
  (if (cube-dashboard--decision-at-point)
      (cube-decisions-no)
    (let ((item (cube-dashboard--require-item 'approval)))
      (cube-review-reject-id (plist-get item :id)))))

(defun cube-dashboard--student-slug (item)
  "Return the student slug for ITEM (student or bead)."
  (pcase (plist-get item :type)
    ('student (plist-get item :id))
    ('bead (or (alist-get 'student (plist-get item :data))
               (user-error "cube: bead has no student")))
    (_ (user-error "cube: this needs a student or bead item"))))

(defun cube-dashboard-student-session ()
  "Start or show the advisor session for the student at point."
  (interactive)
  (cube-student-session (cube-dashboard--student-slug (cube-dashboard--require-item))))

(defun cube-dashboard-student-dossier ()
  "Show the dossier of the student at point."
  (interactive)
  (cube-org-student-context (cube-dashboard--student-slug (cube-dashboard--require-item))))

(defun cube-dashboard-meeting-note ()
  "Insert a meeting note for the student at point."
  (interactive)
  (cube-org-meeting-note (cube-dashboard--student-slug (cube-dashboard--require-item))))

(defun cube-dashboard-claim ()
  "Claim the bead at point."
  (interactive)
  (cube-beads-claim (plist-get (cube-dashboard--require-item 'bead) :id)))

(defun cube-dashboard-assign ()
  "Open the assignment transient for the bead at point."
  (interactive)
  (cube-beads-assign (plist-get (cube-dashboard--require-item 'bead) :id)))

(defun cube-dashboard-kill ()
  "Close the bead at point, or kill the session at point."
  (interactive)
  (let ((item (cube-dashboard--require-item 'bead 'session)))
    (pcase (plist-get item :type)
      ('bead (cube-beads-close (plist-get item :id)
                               (read-string (format "Reason for closing %s: " (plist-get item :id)))))
      ('session (if-let* ((session (cube-rolodex-find (plist-get item :id))))
                    (cube-rolodex-kill session)
                  (user-error "cube: session %s has no local buffer" (plist-get item :id)))))))

(defun cube-dashboard-workday ()
  "Run the workday of the agent at point, or open the ready bead list."
  (interactive)
  (let ((item (cube-dashboard--current-item)))
    (if (eq (plist-get item :type) 'agent)
        (cube-agent-workday (plist-get item :id))
      (cube-beads-list))))

(defun cube-dashboard-agent-inbox ()
  "Make the agent at point read its inbox now."
  (interactive)
  (cube-agent-inbox (plist-get (cube-dashboard--require-item 'agent) :id)))

(defun cube-dashboard-ack ()
  "Dismiss the attention item at point (`cube attention ack')."
  (interactive)
  (let* ((item (cube-dashboard--require-item))
         (data (plist-get item :data))
         (id (and data (cube-get data 'id))))
    (unless (and id (string-prefix-p "att-" (cube--string id)))
      (user-error "cube: not an attention item"))
    (let ((reason (read-string (format "Dismiss %s, reason: " id))))
      (cube--call-json-async
       (list "attention" "ack" (cube--string id) "--reason" reason "--apply")
       (lambda (_json)
         (message "cube: dismissed %s" id)
         (cube-dashboard-refresh))
       (lambda (code err)
         (message "cube: ack failed (%s): %s" code err))))))

;;;; Mode

(defun cube-dashboard-open-url ()
  "Open the URL of the item at point in a browser, else open the item itself."
  (interactive)
  (let* ((item (cube-dashboard--current-item))
         (url (and item (cube-get (plist-get item :data) 'url))))
    (cond ((and url (not (string-empty-p (cube--string url))))
           (browse-url (cube--string url)))
          (item (cube-dashboard-visit-item item))
          (t (cube-dashboard-visit)))))

(defvar cube-dashboard-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map magit-section-mode-map)
    (define-key map (kbd "g") #'cube-dashboard-refresh)
    (define-key map (kbd "RET") #'cube-dashboard-visit)
    (define-key map (kbd "o") #'cube-dashboard-open-url)
    (define-key map (kbd "1") #'cube-attention-1)
    (define-key map (kbd "2") #'cube-attention-2)
    (define-key map (kbd "3") #'cube-attention-3)
    (define-key map (kbd "a") #'cube-dashboard-approve)
    (define-key map (kbd "y") #'cube-dashboard-yes)
    (define-key map (kbd "n") #'cube-dashboard-no)
    (define-key map (kbd "D") #'cube-decisions)
    (define-key map (kbd "x") #'cube-dashboard-reject)
    (define-key map (kbd "s") #'cube-dashboard-student-session)
    (define-key map (kbd "S") #'cube-dashboard-student-dossier)
    (define-key map (kbd "m") #'cube-dashboard-meeting-note)
    (define-key map (kbd "c") #'cube-dashboard-claim)
    (define-key map (kbd "k") #'cube-dashboard-kill)
    (define-key map (kbd "d") #'cube-dashboard-ack)
    (define-key map (kbd "v") #'cube-review-queue)
    (define-key map (kbd "w") #'cube-dashboard-workday)
    (define-key map (kbd "b") #'cube-beads-list)
    (define-key map (kbd "t") #'cube-agent-tell)
    (define-key map (kbd "T") #'cube-agent-talk)
    (define-key map (kbd "i") #'cube-dashboard-agent-inbox)
    (define-key map (kbd "q") #'cube-cockpit-restore)
    map)
  "Keymap of `cube-dashboard-mode'.")

(defconst cube-dashboard-mode-key-help
  '(("RET" . "open") ("t" . "tell") ("i" . "inbox") ("w" . "workday")
    ("T" . "talk") ("o" . "url") ("c" . "claim") ("k" . "close") ("d" . "dismiss")
    ("g" . "refresh") ("y" . "yes") ("n" . "no") ("a" . "answer")
    ("D" . "decisions") ("x" . "reject") ("s" . "session")
    ("S" . "dossier") ("m" . "note") ("v" . "review") ("b" . "beads"))
  "Key legend of `cube-dashboard-mode', proved against its keymap by the tests.")

(cube-key-legend-register 'cube-dashboard-mode)

(define-derived-mode cube-dashboard-mode magit-section-mode "cube"
  "Overview of the borg-cube backend."
  (setq-local revert-buffer-function (lambda (&rest _) (cube-dashboard-refresh))))

(defun cube-dashboard ()
  "Show the *cube* dashboard and refresh it."
  (interactive)
  (with-current-buffer (get-buffer-create "*cube*")
    (unless (derived-mode-p 'cube-dashboard-mode) (cube-dashboard-mode))
    (pop-to-buffer (current-buffer)))
  (cube-dashboard--render)
  (cube-dashboard-refresh))

(defun cube-dashboard--on-attention-update ()
  "Redraw the dashboard when the attention cache changed elsewhere."
  (when (and cube-dashboard-auto-refresh (get-buffer "*cube*"))
    (unless (memq 'attention cube-dashboard--pending)
      (setf (alist-get 'attention cube-dashboard--data)
            (list :json (list (cons 'items cube--attention-items)
                              (cons 'generated cube--attention-generated))
                  :time (current-time) :error nil))
      (cube-dashboard--render))))

(add-hook 'cube-attention-update-hook #'cube-dashboard--on-attention-update)

(defun cube-dashboard--on-decisions-update ()
  "Redraw the dashboard when the decisions cache changed elsewhere."
  (when (and cube-dashboard-auto-refresh (get-buffer "*cube*"))
    (unless (memq 'decisions cube-dashboard--pending)
      (setf (alist-get 'decisions cube-dashboard--data)
            (list :json (list (cons 'decisions cube-decisions--items)
                              (cons 'answered cube-decisions--answered)
                              (cons 'generated cube-decisions--generated))
                  :time (current-time) :error nil))
      (cube-dashboard--render))))

(add-hook 'cube-decisions-update-hook #'cube-dashboard--on-decisions-update)

;;;; Attention commands (shared with the C-c b prefix)

(defun cube-attention-items ()
  "Return the merged attention list, loudest first.
Backend items (normalised dashboard items) come first, then local
sessions in attention or error state that the backend does not list."
  (let* ((backend (mapcar #'cube-dashboard--normalize-attention
                          (cube-dashboard--loudest cube--attention-items
                                                   (length cube--attention-items))))
         (listed (mapcar (lambda (i) (plist-get i :id)) backend))
         (local (seq-remove (lambda (s) (member (cube-session-name s) listed))
                            (cube-rolodex-attention-sessions))))
    (append backend (mapcar #'cube-dashboard--normalize-local-session local))))

(defun cube-attention-nth (n)
  "Jump to the Nth loudest attention item (1-based)."
  (interactive "p")
  (let ((item (nth (1- (max 1 (or n 1))) (cube-attention-items))))
    (if item
        (cube-dashboard-visit-item item)
      (message "cube: nothing needs attention%s" (if (and n (> n 1)) (format " at %d" n) "")))))

(defun cube-attention ()
  "Jump to the loudest attention item."
  (interactive)
  (cube-attention-nth 1))

(defun cube-attention-1 () "Jump to the loudest item." (interactive) (cube-attention-nth 1))
(defun cube-attention-2 () "Jump to the second loudest item." (interactive) (cube-attention-nth 2))
(defun cube-attention-3 () "Jump to the third loudest item." (interactive) (cube-attention-nth 3))

;;;; Brief

(defun cube-brief ()
  "Show the morning brief from `cube brief' as markdown."
  (interactive)
  (message "cube: fetching brief...")
  (cube--call-json-async
   '("brief")
   (lambda (json)
     (let ((markdown (cube-get json 'markdown)))
       (if (and markdown (not (string-empty-p markdown)))
           (with-current-buffer (get-buffer-create "*cube-brief*")
             (let ((inhibit-read-only t))
               (erase-buffer)
               (insert markdown)
               (goto-char (point-min)))
             (if (require 'markdown-mode nil t) (markdown-mode) (text-mode))
             (view-mode 1)
             (pop-to-buffer (current-buffer)))
         (with-current-buffer (get-buffer-create "*cube-doc*")
           (let ((inhibit-read-only t))
             (erase-buffer)
             (insert (or (and (cube-get json 'file)
                              (cube-host-file-contents (cube-get json 'file)))
                         (pp-to-string json)))
             (goto-char (point-min)))
           (view-mode 1)
           (pop-to-buffer (current-buffer))))))
   (lambda (code err) (message "cube: brief failed (%s): %s" code err))))

(defun cube-budget ()
  "Show the backend budget table in a dedicated read-only buffer."
  (interactive)
  (cube--call-json-async
   '("budget")
   (lambda (json)
     (with-current-buffer (get-buffer-create "*cube-budget*")
       (let ((inhibit-read-only t))
         (erase-buffer)
         (insert "Cube budget\n\n"
                 (string-join (cube-dashboard--budget-lines json) "\n")
                 "\n")
         (goto-char (point-min)))
       (special-mode)
       (pop-to-buffer (current-buffer))))
   (lambda (code err) (message "cube: budget failed (%s): %s" code err))))

(provide 'cube-dashboard)
;;; cube-dashboard.el ends here
