;;; cube-dashboard-test.el --- Tests for cube-dashboard  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(defun cube-test-dashboard-load-fixtures ()
  "Fill `cube-dashboard--data' from the fixtures as if every call succeeded."
  (setq cube-dashboard--data nil)
  (dolist (pair '((goals . "goals.json") (pipelines . "pipeline-status.json")
                  (decisions . "decisions.json")
                  (attention . "attention.json") (status . "status.json")
                  (agents . "agents.json") (work . "work.json")
                  (ready . "ready.json") (people . "people.json")
                  (projects . "projects.json")
                  (papers . "papers.json") (literature . "literature.json")
                  (repos . "repos.json")
                  (budget . "budget.json")))
    (setf (alist-get (car pair) cube-dashboard--data)
          (list :json (cube-test-read-fixture (cdr pair)) :time (current-time) :error nil))))

(defmacro cube-test-with-dashboard (&rest body)
  "Run BODY with a fresh *cube* buffer and isolated dashboard state."
  (declare (indent 0))
  `(let ((cube-dashboard--data nil)
         (cube-dashboard--pending nil)
         (cube-dashboard-auto-refresh nil))
     (when (get-buffer "*cube*") (kill-buffer "*cube*"))
     (unwind-protect
         (progn ,@body)
       (when (get-buffer "*cube*") (kill-buffer "*cube*")))))

(ert-deftest cube-dashboard-normalize-attention ()
  (let* ((items (cube-get (cube-test-read-fixture "attention.json") 'items))
         (norm (mapcar #'cube-dashboard--normalize-attention items)))
    (should (equal (mapcar (lambda (i) (plist-get i :type)) norm) '(approval session bead)))
    (should (equal (mapcar (lambda (i) (plist-get i :id)) norm)
                   '("cube-301" "alex-plan" "cube-233")))
    (should (string-match-p "Outbound email to Alex" (plist-get (car norm) :label)))
    (should (string-prefix-p "!!" (plist-get (car norm) :label)))
    (should (string-match-p "approval" (plist-get (car norm) :detail)))
    (should (string-match-p "20m" (plist-get (car norm) :detail)))
    (should (eq (plist-get (car norm) :data) (car items)))))

(ert-deftest cube-dashboard-normalize-attention-tolerates-missing ()
  (let ((item (cube-dashboard--normalize-attention '((id . "att-x") (kind . "finding")))))
    (should (eq (plist-get item :type) 'finding))
    (should (equal (plist-get item :id) "att-x"))
    (should (stringp (plist-get item :label)))))

(ert-deftest cube-dashboard-banner-selection-and-text ()
  (let* ((status (cube-test-read-fixture "status.json"))
         (banner (cube-dashboard--select-banner status)))
    (should (equal (cube-get banner 'severity) "p0"))
    (should (equal (cube-get banner 'bead) "cube-410"))
    (should (equal (cube-dashboard--banner-text banner)
                   "P0  Codex runner exhausted"))
    (should (eq (cube-dashboard--banner-face banner) 'cube-banner-p0))
    (should-not (cube-dashboard--select-banner
                 '((incidents . ((banner . ((severity . "p2"))))))))))

(ert-deftest cube-dashboard-budget-segment-formatting ()
  (let* ((status (cube-test-read-fixture "status.json"))
         (budget (cube-get status 'budget))
         (detail (cube-test-read-fixture "budget.json"))
         (segment (cube-dashboard--budget-segment budget detail))
         (impl (string-match "impl 80%" segment))
         (exhausted (string-match "codex exhausted until 21:00" segment)))
    (should (string-match-p "plan 42%" segment))
    (should (string-match-p "impl 80%" segment))
    (should (string-match-p "bulk 3%" segment))
    (should exhausted)
    (should-not (get-text-property impl 'face segment))
    (let* ((warning-budget '((plan . 90)))
           (warning (cube-dashboard--budget-segment warning-budget))
           (at (string-match "plan 90%" warning)))
      (should (eq (get-text-property at 'face warning) 'warning)))))

(ert-deftest cube-dashboard-peer-header-formatting ()
  (should (equal (cube-dashboard--peer-text
                  '((name . "ws") (reachable . t) (sha . "d5d5270")
                    (lag_commits . 0)))
                 "ws ✓ d5d5270"))
  (should (equal (cube-dashboard--peer-text
                  '((name . "laptop") (reachable . t) (lag_commits . 0)))
                 "laptop ✓"))
  (should (equal (cube-dashboard--peer-text
                  '((name . "ws") (reachable . :false) (lag_commits . 0)))
                 "ws ⊘ unreachable"))
  (should (equal (cube-dashboard--peer-text
                  '((name . "laptop") (reachable . t) (lag_commits . 3)))
                 "laptop ✓ lag 3"))
  ;; a peer with no ssh route from this host is not broken, it pulls on its own
  (should (equal (cube-dashboard--peer-text
                  '((name . "laptop") (reachable . :false) (route . "none")))
                 "laptop pull-only"))
  (let ((segment (cube-dashboard--peers-segment
                  (cube-test-read-fixture "status.json"))))
    (should (string-match-p "ws ✓ d5d5270" segment))
    (should (string-match-p "laptop ✓ lag 3" segment))))

(ert-deftest cube-dashboard-budget-lines-have-tiers-and-runners ()
  (let ((lines (cube-dashboard--budget-lines (cube-test-read-fixture "budget.json"))))
    (should (= (length lines) 9))
    (should (string-match-p "plan +[[]" (car lines)))
    (should (string-match-p "codex +exhausted.*until 21:00" (nth 5 lines)))))

(ert-deftest cube-dashboard-loudest ()
  (let* ((items (cube-get (cube-test-read-fixture "attention.json") 'items))
         (ids (lambda (l) (mapcar (lambda (i) (cube-get i 'id)) l))))
    ;; severity first, backend order kept on ties
    (should (equal (funcall ids (cube-dashboard--loudest items 3))
                   '("att-cube-301" "att-session-alex-plan" "att-cube-233")))
    (should (equal (funcall ids (cube-dashboard--loudest items 1)) '("att-cube-301")))
    (should (= (length (cube-dashboard--loudest items 10)) 3))
    (should (null (cube-dashboard--loudest nil 3)))
    (let ((cube-attention-count 2))
      (should (= (length (cube-dashboard--loudest items)) 2)))
    ;; a high item further down moves to the front
    (let ((shuffled (list (nth 1 items) (nth 2 items) (nth 0 items))))
      (should (equal (car (funcall ids (cube-dashboard--loudest shuffled 3))) "att-cube-301")))
    ;; the input is not modified
    (should (equal (funcall ids items) '("att-cube-301" "att-session-alex-plan" "att-cube-233")))))

(ert-deftest cube-dashboard-normalize-fleet ()
  (let* ((status (cube-test-read-fixture "status.json"))
         (session (cube-dashboard--normalize-session (car (cube-get status 'sessions))))
         (run (cube-dashboard--normalize-run (car (cube-get status 'runs)))))
    (should (eq (plist-get session :type) 'session))
    (should (equal (plist-get session :id) "alex-plan"))
    (should (string-match-p "○ alex-plan" (plist-get session :label)))
    (should (string-match-p "claude" (plist-get session :detail)))
    (should (eq (plist-get run :type) 'run))
    (should (equal (plist-get run :id) "r-20260902-0912-a1"))
    (should (string-match-p "programmer on cube-142" (plist-get run :label)))
    (should (string-match-p "codex" (plist-get run :detail)))))

(ert-deftest cube-dashboard-normalize-bead-person-paper-repo ()
  (let ((bead (cube-dashboard--normalize-bead
               (car (cube-get (cube-test-read-fixture "ready.json") 'beads))))
        (person (cube-dashboard--normalize-person
                 (car (cube-get (cube-test-read-fixture "people.json") 'people))))
        (paper (cube-dashboard--normalize-paper
                (car (cube-get (cube-test-read-fixture "papers.json") 'papers))))
        (repo (cube-dashboard--normalize-repo
               (cadr (cube-get (cube-test-read-fixture "repos.json") 'repos)))))
    (should (eq (plist-get bead :type) 'bead))
    (should (equal (plist-get bead :id) "cube-142"))
    (should (string-match-p "P2 Implement mt-aware" (plist-get bead :label)))
    (should (string-match-p "implement" (plist-get bead :detail)))
    (should (string-match-p "alex-example" (plist-get bead :detail)))
    (should (eq (plist-get person :type) 'student))
    (should (equal (plist-get person :id) "alex-example"))
    (should (string-match-p "⚠ Alex Example" (plist-get person :label)))
    (should (string-match-p "proposal defense in 74 d" (plist-get person :detail)))
    (should (eq (plist-get paper :type) 'paper))
    (should (equal (plist-get paper :id) "cube-210"))
    (should (string-match-p "REVISION" (plist-get paper :label)))
    (should (string-match-p "Bioinformatics" (plist-get paper :detail)))
    (should (eq (plist-get repo :type) 'repo))
    (should (equal (plist-get repo :id) "borg-website"))
    (should (string-prefix-p "*" (plist-get repo :label)))
    (should (string-match-p "\\+1/-0" (plist-get repo :detail)))
    (should (string-match-p "audit cube-171" (plist-get repo :detail)))))

(ert-deftest cube-dashboard-visit-table ()
  (dolist (type '(session bead student paper repo project goal run approval file))
    (let ((fn (cube-dashboard--visit-function type)))
      (should fn)
      (should (fboundp fn))))
  (should-not (cube-dashboard--visit-function 'unknown))
  (should-error (cube-dashboard-visit-item '(:type unknown :id "x")) :type 'user-error))

(ert-deftest cube-dashboard-visit-dispatches ()
  (let ((calls nil))
    (cl-letf (((symbol-function 'cube-beads-show) (lambda (id) (push (list 'bead id) calls)))
              ((symbol-function 'cube-org-open-person) (lambda (id) (push (list 'student id) calls)))
              ((symbol-function 'cube-review-open) (lambda (id) (push (list 'approval id) calls)))
              ((symbol-function 'cube-project-open)
               (lambda (id &optional _project) (push (list 'project id) calls))))
      (cube-dashboard-visit-item '(:type bead :id "cube-142"))
      (cube-dashboard-visit-item '(:type student :id "alex-example"))
      (cube-dashboard-visit-item '(:type project :id "mt-assembly"))
      (cube-dashboard-visit-item '(:type approval :id "cube-301"))
      (should (equal (nreverse calls)
                     '((bead "cube-142") (student "alex-example")
                       (project "mt-assembly") (approval "cube-301")))))))

(ert-deftest cube-dashboard-run-log-text ()
  (let ((text (cube-dashboard--run-log-text (cube-test-read-fixture "run-show.json"))))
    (should (string-match-p "^run_id:     r-20260901-0700-k1" text))
    (should (string-match-p "^role:       advisor" text))
    (should (string-match-p "Log tail:" text))
    (should (string-match-p "Progress note: Alex Example" text))))

(ert-deftest cube-dashboard-render-from-fixtures ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (cube-test-with-dashboard
        (cube-test-dashboard-load-fixtures)
        (with-current-buffer (get-buffer-create "*cube*")
          (cube-dashboard-mode)
          (cube-dashboard--render)
          (let ((text (buffer-string)))
            (should (string-match-p "^Goals (1)" text))
            (should (string-match-p "^Pipelines (2)" text))
            (should (string-match-p "Protein function survey  survey  iteration 0" text))
            (should (string-match-p "^Attention (3)" text))
            (should (string-match-p "^Fleet (2)" text))
            (should (string-match-p "^Ready work (4)" text))
            (should (string-match-p "^Students (3)" text))
            (should (string-match-p "^Papers (2)" text))
            (should (string-match-p "^Repos (2)" text))
            (should (string-match-p "attention 2  ready 4  running 1  approvals 1" text))
            (should (string-match-p "peers: ws ✓ d5d5270  laptop ✓ lag 3" text))
            (should (string-match-p "Alex Example" text)))
          ;; the item under the first attention line carries the plist
          (goto-char (point-min))
          (re-search-forward "Outbound email to Alex")
          (let ((item (cube-dashboard--current-item)))
            (should (eq (plist-get item :type) 'approval))
            (should (equal (plist-get item :id) "cube-301")))
          ;; group headings have no item
          (goto-char (point-min))
          (re-search-forward "^Ready work")
          (should-not (cube-dashboard--current-item))
          (re-search-forward "cube-150\\|gapsmith-db")
          (should (eq (plist-get (cube-dashboard--current-item) :type) 'bead)))))))

(ert-deftest cube-dashboard-header-click-runs-the-cockpit-doctor ()
  (cube-test-with-dashboard
    (cube-test-dashboard-load-fixtures)
    (with-current-buffer (get-buffer-create "*cube*")
      (cube-dashboard-mode)
      (cube-dashboard--render)
      (goto-char (point-min))
      (re-search-forward "borg-cube on")
      (should (eq (lookup-key (get-text-property (match-beginning 0) 'keymap) [mouse-1])
                  #'cube-dashboard-mouse-doctor)))
    (let ((ran nil))
      (cl-letf (((symbol-function 'cube-doctor) (lambda () (setq ran t))))
        (cube-dashboard-mouse-doctor nil))
      (should ran))))

(ert-deftest cube-dashboard-render-banner-and-optional-budget ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (cube-test-with-dashboard
        (cube-test-dashboard-load-fixtures)
        (let ((cube-dashboard-sections '(budget)))
          (with-current-buffer (get-buffer-create "*cube*")
            (cube-dashboard-mode)
            (cube-dashboard--render)
            (goto-char (point-min))
            (should (search-forward "P0  Codex runner exhausted" nil t))
            (should (eq (get-text-property (line-beginning-position) 'face)
                        'cube-banner-p0))
            (should (equal (plist-get (cube-dashboard--current-item) :id)
                           "cube-410"))
            (should (search-forward "Budget (4 tiers, 5 runners)" nil t))
            (should (search-forward "codex      exhausted" nil t))))))))

(ert-deftest cube-dashboard-render-tolerates-failures ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (cube-test-with-dashboard
        (cube-test-dashboard-load-fixtures)
        (setf (alist-get 'repos cube-dashboard--data)
              (list :json nil :time (current-time) :error "repos failed (2): boom"))
        (setf (alist-get 'papers cube-dashboard--data) nil)
        (with-current-buffer (get-buffer-create "*cube*")
          (cube-dashboard-mode)
          (cube-dashboard--render)
          (let ((text (buffer-string)))
            (should (string-match-p "Repos (0)  \\[repos failed (2): boom\\]" text))
            (should (string-match-p "Papers (0)  (loading)" text))
            (should (string-match-p "^Attention (3)" text))))))))

(ert-deftest cube-dashboard-fleet-merges-local-sessions ()
  (cube-test-with-clean-rolodex
    (cube-test-with-dashboard
      (cube-test-dashboard-load-fixtures)
      (let ((b1 (generate-new-buffer " *cube-dash-1*"))
            (b2 (generate-new-buffer " *cube-dash-2*")))
        (unwind-protect
            (progn
              (cube-rolodex--register
               (cube-session-create :name "alex-plan" :kind 'claude :state 'idle :buffer b1))
              (cube-rolodex--register
               (cube-session-create :name "local-only" :kind 'shell :state 'running :buffer b2))
              (let ((items (cube-dashboard--fleet-items)))
                ;; host session, host run, and the local session the host does not know
                (should (equal (mapcar (lambda (i) (plist-get i :id)) items)
                               '("alex-plan" "r-20260902-0912-a1" "local-only")))))
          (kill-buffer b1) (kill-buffer b2))))))

(ert-deftest cube-dashboard-async-refresh-with-fake ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (cube-test-with-dashboard
        (save-window-excursion
          (cube-dashboard)
          (cube-test-wait-until (null cube-dashboard--pending))
          (should (= (length cube-dashboard--data) 14))
          (dolist (entry cube-dashboard--data)
            (should (plist-get (cdr entry) :json))
            (should-not (plist-get (cdr entry) :error)))
          ;; the attention cache feeds the mode line
          (should (= (length cube--attention-items) 3))
          (with-current-buffer "*cube*"
            (should (derived-mode-p 'cube-dashboard-mode))
            (should (string-match-p "Genome-scale protein function" (buffer-string)))
            (should (string-match-p "^Projects (3)" (buffer-string)))
            (should (string-match-p "Attention (3)  (" (buffer-string)))))))))

(ert-deftest cube-dashboard-refresh-records-per-section-errors ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (cube-test-with-dashboard
        (let ((cube-dashboard--calls '((attention "attention") (status "fail"))))
          (with-current-buffer (get-buffer-create "*cube*") (cube-dashboard-mode))
          (cube-dashboard-refresh)
          (cube-test-wait-until (null cube-dashboard--pending))
          (should (plist-get (cube-dashboard--entry 'attention) :json))
          (should (string-match-p "fail failed (7): fake failure"
                                  (plist-get (cube-dashboard--entry 'status) :error)))
          (with-current-buffer "*cube*"
            (should (string-match-p "\\[fail failed" (buffer-string)))))))))

(ert-deftest cube-dashboard-attention-items-merge-local ()
  (cube-test-with-clean-rolodex
    (cube-attention-set-items (cube-test-read-fixture "attention.json"))
    (let ((b1 (generate-new-buffer " *cube-att-1*"))
          (b2 (generate-new-buffer " *cube-att-2*")))
      (unwind-protect
          (progn
            (cube-rolodex--register
             (cube-session-create :name "alex-plan" :kind 'claude :state 'attention :buffer b1))
            (cube-rolodex--register
             (cube-session-create :name "fix-tests" :kind 'codex :state 'error :buffer b2))
            (let ((items (cube-attention-items)))
              (should (equal (mapcar (lambda (i) (plist-get i :id)) items)
                             '("cube-301" "alex-plan" "cube-233" "fix-tests")))
              (should (eq (plist-get (car (last items)) :type) 'session))))
        (kill-buffer b1) (kill-buffer b2)))
    (cube-attention-set-items nil)))

(ert-deftest cube-dashboard-attention-nth-dispatches ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (cube-attention-set-items (cube-test-read-fixture "attention.json"))
      (let ((visited nil))
        (cl-letf (((symbol-function 'cube-review-open) (lambda (id) (push id visited)))
                  ((symbol-function 'cube-beads-show) (lambda (id) (push id visited))))
          (cube-attention)
          (cube-attention-nth 3)
          (should (equal (nreverse visited) '("cube-301" "cube-233")))
          ;; a session without a local buffer only reports, in local mode
          (should (string-match-p "no buffer here" (cube-attention-nth 2)))
          (should (string-match-p "nothing needs attention" (cube-attention-nth 9)))))
      (cube-attention-set-items nil))))

(ert-deftest cube-dashboard-brief-with-fake ()
  (cube-test-with-local
    (when (get-buffer "*cube-brief*") (kill-buffer "*cube-brief*"))
    (save-window-excursion
      (cube-brief)
      (cube-test-wait-until (get-buffer "*cube-brief*"))
      (with-current-buffer "*cube-brief*"
        (should (string-match-p "# Brief for Tuesday" (buffer-string)))
        (should buffer-read-only)))
    (kill-buffer "*cube-brief*")))

(ert-deftest cube-dashboard-keys ()
  (dolist (pair '(("g" . cube-dashboard-refresh) ("RET" . cube-dashboard-visit)
                  ("o" . cube-dashboard-open-url) ("1" . cube-attention-1)
                  ("3" . cube-attention-3) ("a" . cube-dashboard-approve)
                  ("x" . cube-dashboard-reject) ("s" . cube-dashboard-student-session)
                  ("S" . cube-dashboard-student-dossier) ("m" . cube-dashboard-meeting-note)
                  ("c" . cube-dashboard-claim) ("k" . cube-dashboard-kill)
                  ("v" . cube-review-queue) ("w" . cube-dashboard-workday)
                  ("b" . cube-beads-list) ("t" . cube-agent-tell) ("T" . cube-agent-talk)
                  ("i" . cube-dashboard-agent-inbox) ("q" . cube-cockpit-restore)
                  ("y" . cube-dashboard-yes) ("n" . cube-dashboard-no)
                  ("D" . cube-decisions)
                  ("p" . magit-section-backward)
                  ("TAB" . magit-section-toggle)))
    (should (eq (lookup-key cube-dashboard-mode-map (kbd (car pair))) (cdr pair)))))


;;;; Work section: what the cube is working on

(ert-deftest cube-dashboard-work-agent-rows ()
  "Each agent row names its host, tick, state, running bead, inbox and runs."
  (let* ((json (cube-test-read-fixture "work.json"))
         (now (encode-time '(0 12 9 4 9 2026 nil nil 0)))
         (rows (mapcar (lambda (agent)
                         (cube-dashboard--normalize-work-agent agent now))
                       (cube-dashboard--work-agents json))))
    (should (equal (mapcar (lambda (row) (plist-get row :id)) rows)
                   '("coordinator" "literature" "liaison")))
    (should (equal (mapcar (lambda (row) (plist-get row :type)) rows)
                   '(agent agent agent)))
    (let ((coordinator (plist-get (nth 0 rows) :label)))
      (should (string-prefix-p "◎ coordinator" coordinator))
      (should (string-match-p " ws " coordinator))
      (should (string-match-p "hourly" coordinator))
      (should (string-match-p "●running" coordinator))
      (should (string-match-p "cube-pjr\\.4 plan1:final" coordinator))
      (should (string-match-p "glm-5\\.3-flash" coordinator))
      (should (string-match-p "inbox 2" coordinator))
      (should (string-match-p "today 1 run\\'" coordinator)))
    (let ((literature (plist-get (nth 1 rows) :label)))
      (should (string-match-p "○not-due" literature))
      (should (string-match-p "next 07:00" literature))
      (should (string-match-p "today 0 runs" literature)))
    (should (string-match-p "○idle" (plist-get (nth 2 rows) :label)))))

(ert-deftest cube-dashboard-work-task-rows ()
  "Task rows carry the bead, stage, owner, title and deadline, running first."
  (let* ((json (cube-test-read-fixture "work.json"))
         (rows (mapcar #'cube-dashboard--normalize-work-task
                       (cube-dashboard--work-tasks json))))
    (should (equal (mapcar (lambda (row) (plist-get row :id)) rows)
                   '("cube-pjr.4" "cube-171" "cube-180")))
    (should (equal (mapcar (lambda (row) (plist-get row :type)) rows)
                   '(bead bead bead)))
    (let ((first (plist-get (car rows) :label)))
      (should (string-prefix-p "● cube-pjr.4" first))
      (should (string-match-p "plan1:final" first))
      (should (string-match-p "agent:coordinator" first))
      (should (string-match-p "Final plan v1" first))
      (should (string-match-p "due 2026-09-10" first)))
    (should (string-prefix-p "○ cube-171" (plist-get (nth 1 rows) :label)))))

(ert-deftest cube-dashboard-work-section-renders-both-groups ()
  "The work section renders an Agents group and a Tasks group with the legend."
  (cube-test-with-dashboard
    (with-current-buffer (get-buffer-create "*cube*")
      (cube-dashboard-mode)
      (cube-test-dashboard-load-fixtures)
      (let ((cube-dashboard-sections '(work)))
        (cube-dashboard--render))
      (let ((text (buffer-string)))
        (should (string-match-p "^Agents (3)" text))
        (should (string-match-p "^Tasks (3)" text))
        (should (string-match-p "◎ coordinator" text))
        (should (string-match-p "● cube-pjr\\.4" text))
        ;; the legend is inside the buffer, under the heading
        (should (string-match-p "RET open  t tell  i inbox  w workday" text))
        (should (string-match-p "? all keys" text))))))

(ert-deftest cube-dashboard-work-agent-inbox-goes-through-the-write-gate ()
  "`i' on an agent row dry-runs `agent inbox NAME --now' on the agent host first."
  (cube-test-with-dashboard
    (with-current-buffer (get-buffer-create "*cube*")
      (cube-dashboard-mode)
      (cube-test-dashboard-load-fixtures)
      (let ((cube-dashboard-sections '(work)))
        (cube-dashboard--render))
      (goto-char (point-min))
      (should (re-search-forward "◎ coordinator" nil t))
      (should (eq (plist-get (cube-dashboard--current-item) :type) 'agent))
      (let ((calls nil)
            (cube-agents-confirm-writes t)
            (cube-agent--cache (cube-agents--list (cube-test-read-fixture "agents.json"))))
        (cl-letf (((symbol-function 'cube--call-json-async-on)
                   (lambda (host args callback &optional _error)
                     (push (cons host args) calls)
                     (funcall callback '((ok . t)))))
                  ((symbol-function 'cube-agent--show-plan) (lambda (&rest _) nil))
                  ((symbol-function 'cube-agents-refresh) (lambda () nil))
                  ((symbol-function 'y-or-n-p) (lambda (&rest _) t)))
          (call-interactively #'cube-dashboard-agent-inbox))
        (should (equal (nreverse calls)
                       '(("ws" "agent" "inbox" "coordinator" "--now" "--dry-run")
                         ("ws" "agent" "inbox" "coordinator" "--now" "--apply"))))))))

(provide 'cube-dashboard-test)
;;; cube-dashboard-test.el ends here
