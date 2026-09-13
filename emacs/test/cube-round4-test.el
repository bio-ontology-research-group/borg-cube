;;; cube-round4-test.el --- Tests for adoption and runner profiles  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(defun cube-round4--project (slug)
  "Return fixture project SLUG."
  (seq-find (lambda (project) (equal (cube-get project 'slug) slug))
            (cube-get (cube-test-read-fixture "projects.json") 'projects)))

(ert-deftest cube-round4-adopt-arguments-and-dry-run-gate ()
  "Adoption constructs its exact argv and never applies without confirmation."
  (should (equal (cube-rolodex--adopt-args
                  "cube/kobayashi-codex"
                  '(:project "kobayashi-marust" :bead "cube-142" :role "programmer"))
                 '("adopt" "kobayashi-codex" "--project" "kobayashi-marust"
                   "--bead" "cube-142" "--role" "programmer" "--dry-run")))
  (should-error (cube-rolodex--adopt-args "codex" '(:role "programmer")))
  (let ((calls nil)
        (cube-rolodex--adopt-name "kobayashi-codex")
        (cube-rolodex--adopt-plist '(:project "kobayashi-marust" :role "programmer")))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error)
                 (push args calls)
                 (funcall callback (cube-test-read-fixture "adopt.json"))))
              ((symbol-function 'cube-rolodex--show-adopt-plan) (lambda (&rest _) nil))
              ((symbol-function 'y-or-n-p) (lambda (_prompt) nil)))
      (cube-rolodex-adopt-execute))
    (should (equal calls
                   '(("adopt" "kobayashi-codex" "--project" "kobayashi-marust"
                      "--role" "programmer" "--dry-run"))))))

(ert-deftest cube-round4-adopt-applies-only-after-confirmation ()
  "A confirmed adoption follows the preview with exactly one apply call."
  (let ((calls nil) (finished nil)
        (cube-rolodex--adopt-name "kobayashi-codex")
        (cube-rolodex--adopt-plist '(:project "kobayashi-marust" :bead "cube-142"
                                      :role "programmer")))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error)
                 (push args calls)
                 (funcall callback (cube-test-read-fixture
                                    (if (member "--apply" args) "adopt-apply.json" "adopt.json")))) )
              ((symbol-function 'cube-rolodex--show-adopt-plan) (lambda (&rest _) nil))
              ((symbol-function 'cube-rolodex--finish-adopt)
               (lambda (name result) (setq finished (list name result))))
              ((symbol-function 'y-or-n-p) (lambda (_prompt) t)))
      (cube-rolodex-adopt-execute))
    (should (equal (mapcar (lambda (args) (car (last args))) (nreverse calls))
                   '("--dry-run" "--apply")))
    (should (equal (car finished) "kobayashi-codex"))))

(ert-deftest cube-round4-run-resume-decision-and-profile-preview ()
  "Runner argv adds --resume only for a stored resume id and previews profile."
  (cube-test-with-local
    (should (equal (cube-run--args "programmer" "cube-142" nil t nil)
                   '("run" "programmer" "--bead" "cube-142" "--dry-run")))
    (should (equal (cube-run--args "programmer" "cube-142" "0198" t nil)
                   '("run" "programmer" "--bead" "cube-142" "--resume" "--dry-run")))
    (should (equal (cube-rolodex--command-for
                    'run '(:name "programmer-cube-142" :role "programmer"
                             :bead "cube-142" :resume "0198"))
                   '("env" "CUBE_SESSION=programmer-cube-142" "cube" "run" "programmer"
                     "--bead" "cube-142" "--resume" "--attach"))))
  (let ((starts nil) (calls nil))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error)
                 (push args calls)
                 (funcall callback (cube-test-read-fixture "run.json"))))
              ((symbol-function 'cube-run--show-plan) (lambda (&rest _) nil))
              ((symbol-function 'cube-rolodex-start)
               (lambda (&rest args) (setq starts args)))
              ((symbol-function 'y-or-n-p) (lambda (_prompt) t)))
      (cube-run-bead "programmer" "cube-142" "0198"))
    (should (equal (car calls)
                   '("run" "programmer" "--bead" "cube-142" "--resume" "--dry-run")))
    (should (equal (seq-drop starts 2)
                   '(:role "programmer" :bead "cube-142" :resume "0198"
                     :project "kobayashi-marust"))))
  (let ((text (cube-run--profile-text (cube-test-read-fixture "run.json"))))
    (should (string-match-p "Sandbox: danger-full-access" text))
    (should (string-match-p "Cwd: ~/Public/software/kobayashi-marust" text))
    (should (string-match-p "workspace-preflight" text))))

(ert-deftest cube-round4-project-renders-runner-and-adopted-session-groups ()
  "Project rendering retains the runner profile and its matching adopted session."
  (let* ((project (cube-round4--project "kobayashi-marust"))
         (sessions (cube-get (cube-test-read-fixture "fleet.json") 'sessions))
         (text (cube-project--render-text project nil nil nil sessions)))
    (should (string-match-p "Runner profile" text))
    (should (string-match-p "Path: ~/Public/software/kobayashi-marust" text))
    (should (string-match-p "Runner: codex" text))
    (should (string-match-p "Sandbox: danger-full-access" text))
    (should (string-match-p "Pre-steps: ./tools/workspace-preflight.sh" text))
    (should (string-match-p "Adopted sessions (1)" text))
    (should (string-match-p "↻ cube/kobayashi-marust-codex" text)))
  (let* ((project (cube-round4--project "kobayashi-marust"))
         (sessions (cube-get (cube-test-read-fixture "fleet.json") 'sessions))
         (buffer (get-buffer-create "*cube-project: round4*")))
    (unwind-protect
        (with-current-buffer buffer
          (cube-project-mode)
          (setq cube-project--project project cube-project--beads nil
                cube-project--people nil cube-project--sessions sessions)
          (cube-project--render)
          (should (string-match-p "Runner profile" (buffer-string)))
          (should (string-match-p "Adopted sessions (1)" (buffer-string))))
      (kill-buffer buffer))))

(ert-deftest cube-round4-fleet-rendering-and-rolodex-project-suffix ()
  "Fleet rows expose project and resume state, while adopted headers name project."
  (let* ((sessions (cube-get (cube-test-read-fixture "fleet.json") 'sessions))
         (buffer (get-buffer-create "*cube-fleet: round4*")))
    (unwind-protect
        (with-current-buffer buffer
          (cube-fleet-mode)
          (let ((cube-fleet--cache sessions)
                (cube-rolodex--sessions nil))
            (cube-fleet--render)
            (should (string-match-p "kobayashi-marust" (buffer-string)))
            (should (string-match-p "↻" (buffer-string)))
            (goto-char (point-min))
            (re-search-forward "kobayashi-marust-codex")
            (let ((map (get-text-property (1- (point)) 'keymap)))
              (should (eq (lookup-key map [mouse-1]) #'cube-fleet-mouse-visit))
              (should (eq (lookup-key map [mouse-3]) #'cube-fleet-mouse-context)))))
      (kill-buffer buffer)))
  (let* ((session (cube-session-create :name "kobayashi-marust-codex" :kind 'codex
                                       :state 'running :project "kobayashi-marust"))
         (line (cube-rolodex--header-line session (list session))))
    (should (string-suffix-p "[kobayashi-marust]" line))))

(ert-deftest cube-round4-fake-adopt-fleet-and-menu-surfaces ()
  "The test CLI exposes the new backend payloads and all new keys are catalogued."
  (cube-test-with-local
    (should (equal (cube-get (cube--call-json '("adopt" "kobayashi-codex"
                                                "--project" "kobayashi-marust" "--dry-run"))
                             'project)
                   "kobayashi-marust"))
    (should (= (length (cube-get (cube--call-json '("fleet")) 'sessions)) 2))
    (should (cube-round4--project "kobayashi-marust")))
  (should (eq (lookup-key cube-fleet-mode-map (kbd "A")) #'cube-fleet-adopt))
  (should (eq (lookup-key cube-session-mode-map (kbd "A")) #'cube-session-adopt))
  (should (eq (lookup-key cube-goal-mode-map (kbd "r")) #'cube-goal-run-agent))
  (should (eq (lookup-key cube-beads-list-mode-map (kbd "r")) #'cube-beads-list-run))
  (dolist (type '(session bead agent))
    (should (cube-menu--context-items type))))

(provide 'cube-round4-test)
;;; cube-round4-test.el ends here
