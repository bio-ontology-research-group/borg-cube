;;; cube-contract-test.el --- Real backend contracts for the cockpit  -*- lexical-binding: t; -*-

;; This suite deliberately does not use emacs/test/bin/cube.  It starts a
;; disposable Beads repository and invokes the installed project CLI through
;; test/contract/cube-real, so a changed Python payload cannot silently drift
;; away from the Emacs normalisers.

;;; Code:

(require 'cube-test-helper)

(defconst cube-contract--directory
  (file-name-directory (or load-file-name buffer-file-name))
  "Directory containing this contract suite.")

(defconst cube-contract--repo-root
  (expand-file-name ".." cube-contract--directory)
  "The borg-cube checkout containing the real CLI.")

(defconst cube-contract--real-cube
  (expand-file-name "test/contract/cube-real" cube-contract--directory)
  "Wrapper that runs the real project CLI against a disposable root.")

(defconst cube-contract--error-cube
  (expand-file-name "test/contract/cube-error" cube-contract--directory)
  "Argparse-shaped failing cube used for UI error-path tests.")

(defconst cube-contract--ssh-sleep
  (expand-file-name "test/contract/ssh-sleep" cube-contract--directory)
  "Sleeping fake ssh used to prove the cockpit watchdog path.")

(defconst cube-contract--config
  "host: contract-host
paths:
  pa: pa
  org: org
  rkg: rkg
  website: website
  skills_library: skills
  infra: infra
  papers: papers
  hermes_home: hermes
  runs: runs
  state: state
beads: {bin: bd}
tiers:
  plan: [{runner: stub, model: stub}]
  implement: [{runner: stub, model: stub}]
  bulk: [{runner: stub, model: stub}]
  local: [{runner: stub, model: stub}]
"
  "Minimal isolated backend configuration.  No real runner is selected.")

(defun cube-contract--write (root relative text)
  "Write TEXT below ROOT at RELATIVE and return the resulting file name."
  (let ((file (expand-file-name relative root)))
    (make-directory (file-name-directory file) t)
    (with-temp-file file (insert text))
    file))

(defun cube-contract--make-root ()
  "Create a disposable backend root and initialise a real Beads database.
Skip explicitly if the installed bd cannot make such a repository."
  (unless (executable-find "bd")
    (ert-skip "contract skipped: real bd is unavailable"))
  (let ((root (make-temp-file "cube-contract-" t)))
    (dolist (dir '("pa" "org" "rkg" "website" "skills" "infra" "papers" "hermes"
                   "runs" "state" "roles" "brain/facts"))
      (make-directory (expand-file-name dir root) t))
    (cube-contract--write root "cube.yaml" cube-contract--config)
    (cube-contract--write root ".gitignore" ".env\nruns/\nstate/\n")
    ;; repos must not reach GitHub from a test: a fresh empty snapshot in the cache
    (make-directory (expand-file-name "state/cache" root) t)
    (cube-contract--write root "state/cache/github.json"
                          (format "{\"org\": \"bio-ontology-research-group\", \"fetched_at\": %S, \"from_cache\": false, \"warnings\": [], \"repos\": []}"
                                  (format-time-string "%Y-%m-%dT%H:%M:%S+00:00" nil t)))
    (cube-contract--write root "contacts.yaml" "grants: {}\n")
    (cube-contract--write
     root "people.yaml"
     "people:\n  contract-student: {name: Contract Student, role: student, program: MS, source: contract}\n")
    (cube-contract--write root "org/staff.org" "* Students\n- Contract Student\n")
    (cube-contract--write root "rkg/projects.jsonld" "{\"@graph\": []}\n")
    (cube-contract--write root "state/events.jsonl" "")
    (let ((default-directory root)
          (process-environment (cons "BD_NON_INTERACTIVE=1" process-environment)))
      (with-temp-buffer
        (let ((code (call-process "bd" nil (current-buffer) nil
                                  "init" "--non-interactive" "--skip-agents" "--skip-hooks"
                                  "--prefix" "cube")))
          (unless (and (integerp code) (zerop code))
            (let ((detail (string-trim (buffer-string))))
              (delete-directory root t)
              (ert-skip (format "contract skipped: real bd init failed%s"
                                (if (string-empty-p detail) "" (concat ": " detail)))))))))
    root))

(defmacro cube-contract-with-real-backend (binding &rest body)
  "Run BODY with ROOT as a local real backend repository."
  (declare (indent 1))
  (let ((root (car binding)))
    `(let* ((,root (cube-contract--make-root))
            (cube-remote-host nil)
            (cube-root ,root)
            (cube-program cube-contract--real-cube)
            (cube-call-timeout 20)
            (cube-notify-method nil)
            (process-environment
             (append (list (concat "CUBE_CONTRACT_REPO=" cube-contract--repo-root)
                           (concat "CUBE_CONTRACT_ROOT=" ,root))
                     process-environment)))
       (unwind-protect
           (progn ,@body)
         (delete-directory ,root t)))))

(defun cube-contract--goal-id ()
  "Create one disposable goal through the real CLI and return its bead id."
  (let ((payload
         (cube--call-json
          '("goal" "new" "--title" "Contract goal" "--target" "2030-01-01"
            "--success" "contract passes" "--provenance" "contract:1" "--apply"))))
    (or (cube-get payload 'id) (cube-get payload 'goal)
        (ert-fail (format "goal creation returned no id: %S" payload)))))

(defun cube-contract--pipeline-id ()
  "Create one disposable research pipeline through the real CLI and return its epic id."
  (let ((payload
         (cube--call-json
          '("pipeline" "new" "--title" "Contract pipeline" "--target" "2030-01-01"
            "--success" "contract pipeline passes" "--from-mail" "contract mail"
            "--apply"))))
    (or (cube-get payload 'epic)
        (ert-fail (format "pipeline creation returned no epic: %S" payload)))))

(defun cube-contract--normalise (name payload)
  "Run NAME's cockpit normaliser on real backend PAYLOAD."
  (pcase name
    ("status"
     (cube-status-set-json payload)
     (mapcar #'cube-dashboard--normalize-session (cube-get payload 'sessions)))
    ("attention" (mapcar #'cube-dashboard--normalize-attention (cube-get payload 'items)))
    ("ready" (cube-beads--normalize-list payload))
    ("people" (mapcar #'cube-dashboard--normalize-person (cube-get payload 'people)))
    ("student" (cube-org--student-context-org payload))
    ("papers" (mapcar #'cube-dashboard--normalize-paper (cube-get payload 'papers)))
    ("literature" (mapcar #'cube-dashboard--normalize-literature (cube-get payload 'entries)))
    ("repos" (mapcar #'cube-dashboard--normalize-repo (cube-get payload 'repos)))
    ("approvals" (mapcar #'cube-review--heading (cube-get payload 'approvals)))
    ("decisions" (list (mapcar #'cube-decisions--row-text (cube-get payload 'decisions))
                       (mapcar #'cube-decisions--answered-text (cube-get payload 'answered))
                       (cube-decisions--in-section "Questions"
                                                   (append (cube-get payload 'decisions) nil))))
    ("runs" (mapcar #'cube-dashboard--normalize-run (cube-get payload 'runs)))
    ("fleet" (mapcar #'cube-dashboard--normalize-session (cube-get payload 'sessions)))
    ("doctor" (mapcar (lambda (check) (list (cube-get check 'name) (cube-get check 'ok)))
                       (cube-get payload 'checks)))
    ("budget" (cube-dashboard--budget-lines payload))
    ("tier" (cube-tier--tier-table-text payload))
    ("incidents" (cube-dashboard--select-banner payload))
    ("projects" (cube-project--row-items payload))
    ("roster" (cube-roster--table-text payload))
    ("goals" (mapcar #'cube-goal--row-item (cube-goals--list payload)))
    ("goal show" (cube-goal--render-text (cube-goal--object payload)))
    ("pipeline status" (mapcar #'cube-pipeline--row-item (cube-pipeline--pipelines payload)))
    ("pipeline show" (cube-pipeline--render-text (cube-pipeline--object payload)))
    ("agent list" (cube-agents--list payload))
    ("work" (list (mapcar #'cube-dashboard--normalize-work-agent
                          (cube-dashboard--work-agents payload))
                  (mapcar #'cube-dashboard--normalize-work-task
                          (cube-dashboard--work-tasks payload))
                  (cube-get payload 'epics)))
    (_ (ert-fail (format "no normaliser registered for %s" name)))))

(defun cube-contract--render-normalised (name normalised)
  "Render NORMALISED in a disposable cockpit buffer with NAME as its header."
  (with-temp-buffer
    (insert (format "%s contract\n" name))
    (prin1 normalised (current-buffer))
    (insert "\n")
    (goto-char (point-min))
    (should (looking-at (regexp-quote name)))))

(ert-deftest cube-contract-real-backend-payloads-reach-normalisers ()
  "Every cockpit read call accepts the real backend payload it invokes."
  (cube-contract-with-real-backend (root)
    (let ((goal (cube-contract--goal-id))
          (pipeline (cube-contract--pipeline-id)))
      (dolist
          (spec `(("status" ("status"))
                  ("attention" ("attention"))
                  ("ready" ("ready"))
                  ("people" ("people"))
                  ("student" ("student" "contract-student"))
                  ("papers" ("papers"))
                  ("literature" ("literature"))
                  ("repos" ("repos"))
                  ("approvals" ("approvals"))
                  ("decisions" ("decisions"))
                  ("runs" ("runs"))
                  ("fleet" ("fleet"))
                  ("doctor" ("doctor"))
                  ("budget" ("budget"))
                  ("tier" ("tier"))
                  ("incidents" ("incidents"))
                  ("projects" ("projects"))
                  ("roster" ("roster" "--offline"))
                  ("goals" ("goals"))
                  ("goal show" ("goal" "show" ,goal))
                  ("pipeline status" ("pipeline" "status"))
                  ("pipeline show" ("pipeline" "status" ,pipeline))
                  ("agent list" ("agent" "list"))
                  ("work" ("work"))))
        (let* ((name (car spec))
               (payload (cube--call-json (cadr spec)))
               (normalised (cube-contract--normalise name payload)))
          (cube-contract--render-normalised name normalised))))))

(defun cube-contract--cube-commands ()
  "Return every unique interactive cube command from the command table."
  (delete-dups
   (seq-filter
    (lambda (command)
      (and (symbolp command) (commandp command)
           (string-prefix-p "cube-" (symbol-name command))))
    (mapcar (lambda (entry) (plist-get entry :command)) cube-command-table))))

(defun cube-contract--visible-error-p ()
  "Return non-nil when an error is visible in the echo area or a cube buffer."
  (or (string-match-p "cube: unknown command" (or (current-message) ""))
      (seq-some
       (lambda (buffer)
         (and (string-prefix-p "*cube" (buffer-name buffer))
              (with-current-buffer buffer
                (string-match-p "cube: unknown command" (buffer-string)))))
       (buffer-list))))

(defun cube-contract--cube-buffer-state ()
  "Return the current text of every visible cockpit buffer for change checks."
  (mapcar (lambda (buffer)
            (cons buffer (with-current-buffer buffer (buffer-string))))
          (seq-filter (lambda (buffer) (string-prefix-p "*cube" (buffer-name buffer)))
                      (buffer-list))))

(defun cube-contract--new-visible-error-p (before)
  "Return non-nil when a cockpit buffer newly renders a failure after BEFORE."
  (seq-some
   (lambda (buffer)
     (let ((text (with-current-buffer buffer (buffer-string))))
       (and (not (equal text (alist-get buffer before)))
            (string-match-p "cube:\\|failed (" text))))
   (seq-filter (lambda (buffer) (string-prefix-p "*cube" (buffer-name buffer)))
               (buffer-list))))

(defun cube-contract--call-with-timeout (args)
  "Return the classified failure reported by asynchronous ARGS."
  (let ((failure nil))
    (cube--call-json-async args (lambda (_json) nil)
                          (lambda (_code message) (setq failure message)))
    (cube-test-wait-until failure 3)
    failure))

(defmacro cube-contract-with-dashboard (&rest body)
  "Run BODY in an isolated dashboard buffer named as the real dashboard."
  (declare (indent 0))
  `(let ((cube-dashboard--data nil)
         (cube-dashboard--pending nil))
     (when (get-buffer "*cube*") (kill-buffer "*cube*"))
     (unwind-protect
         (with-current-buffer (get-buffer-create "*cube*")
           (cube-dashboard-mode)
           ,@body)
       (when (get-buffer "*cube*") (kill-buffer "*cube*")))))

(ert-deftest cube-contract-ssh-timeout-is-visible-and-actionable ()
  "A sleeping ssh process renders a bounded, actionable dashboard failure."
  (let* ((fake-bin (make-temp-file "cube-contract-ssh-" t))
         (fake-ssh (expand-file-name "ssh" fake-bin))
         (cube-remote-host "ws")
         (cube-root cube-contract--repo-root)
         (cube-program cube-contract--error-cube)
         (cube-call-timeout 0.05)
         (cube-notify-method nil)
         (exec-path (cons fake-bin exec-path))
         (process-environment
          (cons (concat "PATH=" fake-bin ":" (getenv "PATH")) process-environment)))
    (unwind-protect
        (progn
          (copy-file cube-contract--ssh-sleep fake-ssh t)
          (set-file-modes fake-ssh #o755)
          (setq cube--remote-unreachable-since nil
                cube--remote-unreachable-host nil)
          (should (equal (cube-contract--call-with-timeout '("goals"))
                         "ssh: connection timed out"))
          (should (cube--remote-unreachable-p))
          (should (string-prefix-p "⊘ws" (cube-mode-line-string)))
          (should (string-match-p
                   "ws unreachable since [0-9][0-9]:[0-9][0-9] (ssh timeout). M-x cube-toggle-remote for local mode"
                   (cube--remote-unreachable-message)))
          (cube-contract-with-dashboard
            (let ((cube-dashboard--calls nil)
                  (cube-dashboard--data nil)
                  (cube-dashboard--pending nil))
              (cube-dashboard--render)
              (should (string-match-p "ws unreachable since" (buffer-string)))))
          (should-error (cube--ssh-args '("tmux" "new-session") t)
                        :type 'user-error))
      (delete-directory fake-bin t))))

(ert-deftest cube-contract-unknown-command-renders-in-place ()
  "Argparse's invalid-choice text becomes a stable section-header error."
  (let ((cube-remote-host nil)
        (cube-root cube-contract--repo-root)
        (cube-program cube-contract--error-cube)
        (cube-call-timeout 1)
        (cube-notify-method nil))
    (cube-contract-with-dashboard
      (let ((cube-dashboard--calls '((goals "goals")))
            (cube-dashboard--data nil)
            (cube-dashboard--pending nil))
        (cube-dashboard-refresh)
        (cube-test-wait-until (null cube-dashboard--pending) 3)
        (should (string-match-p "\\[cube: unknown command goals\\][[:space:]]+([0-9]+s)"
                                (buffer-string)))
        (should-not (string-match-p "goals[[:space:]]+Refreshing" (buffer-string)))))))

(ert-deftest cube-contract-remote-doctor-runs-local-skew-check ()
  "The cockpit doctor delegates version comparison to the local CLI."
  (let ((cube-remote-host "ws")
        (cube-program "cube"))
    (let ((command (cube--command '("doctor"))))
      (should-not (equal (car command) "ssh"))
      (should (equal (last command 5)
                     '("doctor" "--cockpit" "--host" "ws" "--json"))))))

(ert-deftest cube-contract-toggle-remote-is-session-local-and-refreshes ()
  "Toggling a failed host is reversible and redraws the cockpit." 
  (let ((cube-remote-host "ws")
        (cube--toggle-remote-host nil)
        (refreshes nil))
    (cl-letf (((symbol-function 'cube-dashboard-refresh)
               (lambda () (push cube-remote-host refreshes)))
              ((symbol-function 'cube-refresh)
               (lambda () (push cube-remote-host refreshes))))
      (cube-toggle-remote)
      (should-not cube-remote-host)
      (cube-toggle-remote)
      (should (equal cube-remote-host "ws"))
      (should (equal refreshes '("ws" nil))))))

(ert-deftest cube-contract-capabilities-grey-menu-and-mark-dashboard ()
  "Status capability metadata marks commands the selected host lacks."
  (let* ((cube-remote-host "ws")
         (available (seq-remove (lambda (name) (member name '("goals" "agent")))
                                (cube--refresh-required-commands)))
         (status `((version . ((commands . ,available))))))
    (cube-status-set-json status)
    (should (equal (cube--status-missing-commands status) '("agent" "goals")))
    (cube-contract-with-dashboard
      (setf (alist-get 'status cube-dashboard--data)
            (list :json status :time (current-time) :error nil))
      (cube-dashboard--render)
      (should (string-match-p "\\[host lacks: agent, goals\\]" (buffer-string))))
    (let* ((entry (seq-find (lambda (item) (eq (plist-get item :command) 'cube-goals))
                            cube-command-table))
           (item (cube-menu--item entry)))
      (should (string-match-p "host lacks: goals" (aref item 0)))
      (should-not (cadr (member :enable (append item nil)))))))

(ert-deftest cube-contract-command-table-failures-are-bounded-and-visible ()
  "Invoke every cockpit command-table action with an argparse-failing backend."
  (let* ((log (cube-test-temp-file "cube-contract-command-log-" ""))
         (cube-remote-host nil)
         (cube-root cube-contract--repo-root)
         (cube-program cube-contract--error-cube)
         (cube-beads-program cube-contract--error-cube)
         (cube-call-timeout 0.2)
         (cube-notify-method nil)
         (cube-terminal-backend 'auto)
         (process-environment
          (cons (concat "CUBE_FAKE_OUT=" log) process-environment)))
    (unwind-protect
        (cl-letf (((symbol-function 'read-string) (lambda (&rest _) "contract"))
                  ((symbol-function 'completing-read) (lambda (&rest _) "contract"))
                  ((symbol-function 'read-file-name) (lambda (&rest _) "contract"))
                  ((symbol-function 'y-or-n-p) (lambda (&rest _) nil))
                  ((symbol-function 'yes-or-no-p) (lambda (&rest _) nil))
                  ((symbol-function 'transient-setup)
                   (lambda (&rest _) (message "cube: transient unavailable in error test")))
                  ((symbol-function 'pop-to-buffer)
                   (lambda (&rest _) (user-error "cube: simulated display failure"))))
          (dolist (command (cube-contract--cube-commands))
            (let ((timed-out nil)
                  (messages nil)
                  (before (cube-contract--cube-buffer-state))
                  (original-message (symbol-function 'message)))
              (cl-letf (((symbol-function 'message)
                         (lambda (format-string &rest args)
                           (let ((text (apply original-message format-string args)))
                             (push text messages)
                             text))))
                (condition-case err
                    (with-timeout (1 (setq timed-out t))
                      (call-interactively command))
                  (error (message "cube: %s" (error-message-string err))))
                (with-timeout (2 (setq timed-out t))
                  (while (and (null messages)
                              (not (cube-contract--new-visible-error-p before))
                              (not (cube-contract--visible-error-p)))
                    (accept-process-output nil 0.05))))
              (when timed-out
                (ert-fail (format "%s exceeded the bounded command-table test" command)))
              (unless (or (seq-some (lambda (text) (string-prefix-p "cube:" text)) messages)
                          (cube-contract--new-visible-error-p before)
                          (cube-contract--visible-error-p))
                (ert-fail (format "%s produced no visible failure: %S" command messages)))))
          ;; Do not let a delayed error callback escape the isolated fake
          ;; interaction and prompt a later real-backend contract test.
          (cube-test-wait-until
              (not (seq-some (lambda (process)
                               (and (equal (process-name process) "cube")
                                    (process-live-p process)))
                             (process-list)))
            5)
          (dotimes (_ 20) (accept-process-output nil 0.05))
          ;; The commands that issue a backend request reached the executable
          ;; error double with their machine-readable argv, not a mock result.
          (with-temp-buffer
            (insert-file-contents log)
            (should (string-match-p "--json" (buffer-string))))
      (delete-file log)))))

(provide 'cube-contract-test)
;;; cube-contract-test.el ends here
