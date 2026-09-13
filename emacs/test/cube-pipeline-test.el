;;; cube-pipeline-test.el --- Tests for research pipelines  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(ert-deftest cube-pipeline-new-and-advance-arguments ()
  (let ((plist '(:title "Protein function survey" :target "2026-12-31"
                :success ("A checked reading list" "A reviewed experiment")
                :from-mail "protein function" :person "alex-example"
                :project "mt-assembly" :privacy "local-only")))
    (should
     (equal (cube-pipeline--new-args plist)
            '("pipeline" "new" "--title" "Protein function survey" "--target" "2026-12-31"
              "--success" "A checked reading list" "--success" "A reviewed experiment"
              "--from-mail" "protein function" "--person" "alex-example"
              "--project" "mt-assembly" "--privacy" "local-only" "--dry-run"))))
  (should (equal (cube-pipeline--advance-args "cube-500")
                 '("pipeline" "advance" "cube-500" "--dry-run")))
  (should (equal (cube-pipeline--advance-args "cube-500" "--apply")
                 '("pipeline" "advance" "cube-500" "--apply")))
  (should-error (cube-pipeline--new-args
                 '(:title "Missing mail" :target "2026-12-31" :success ("done")))))

(ert-deftest cube-pipeline-list-and-show-render-contract-fields ()
  (let* ((payload (cube-test-read-fixture "pipeline-status.json"))
         (pipelines (cube-pipeline--pipelines payload))
         (survey (car pipelines))
         (revise (cadr pipelines))
         (list-buffer (get-buffer-create " *cube-pipeline-list-test*"))
         (show-buffer (get-buffer-create " *cube-pipeline-show-test*")))
    (unwind-protect
        (progn
          (setq cube-pipelines--cache pipelines cube-pipelines--error nil)
          (with-current-buffer list-buffer
            (cube-pipeline-mode)
            (setq cube-pipeline--view 'list)
            (cube-pipeline--render)
            (should (string-match-p "Pipelines (2)" (buffer-string)))
            (should (string-match-p "Protein function survey  stage survey" (buffer-string)))
            (should (string-match-p "gate revise  kill yes" (buffer-string)))
            (should (string-match-p "Robert reviews the kill condition" (buffer-string))))
          (with-current-buffer show-buffer
            (cube-pipeline-mode)
            (setq cube-pipeline--view 'show cube-pipeline--pipeline revise)
            (cube-pipeline--render)
            (let ((text (buffer-string)))
              (should (string-match-p "Stages (4)" text))
              (should (string-match-p "Experiments (2)" text))
              (should (string-match-p "Gate (1)" text))
              (should (string-match-p "2  bead cube-608  revise" text))
              (should (string-match-p "Kill: yes" text))
              (should (string-match-p "Robert reviews the kill condition" text))))
          (let ((text (cube-pipeline--render-text survey)))
            (should (string-match-p "Stage: survey" text))
            (should (string-match-p "The senior runs the checked literature survey next" text))))
      (kill-buffer list-buffer)
      (kill-buffer show-buffer))))

(ert-deftest cube-pipeline-visit-opens-selected-bead ()
  (let ((buffer (get-buffer-create " *cube-pipeline-visit-test*"))
        (opened nil)
        (pipeline (cube-test-read-fixture "pipeline-show.json")))
    (unwind-protect
        (with-current-buffer buffer
          (cube-pipeline-mode)
          (setq cube-pipeline--view 'show cube-pipeline--pipeline pipeline)
          (cube-pipeline--render)
          (goto-char (point-min))
          (re-search-forward "cube-503")
          (cl-letf (((symbol-function 'cube-beads-show) (lambda (id) (setq opened id))))
            (cube-pipeline-visit))
          (should (equal opened "cube-503")))
      (kill-buffer buffer))))

(ert-deftest cube-pipeline-command-table-generates-keys-and-menu ()
  (dolist (pair '(("P n" . cube-pipeline-new) ("P l" . cube-pipeline-list)
                  ("P s" . cube-pipeline-show) ("P a" . cube-pipeline-advance)
                  ("P r" . cube-pipeline-rehearse)))
    (should (eq (lookup-key cube-command-map (kbd (car pair))) (cdr pair))))
  (dolist (pair '(("g" . cube-pipeline-revert) ("RET" . cube-pipeline-visit)
                  ("A" . cube-pipeline-advance) ("d" . cube-pipeline-advance-dry-run)
                  ("T" . cube-pipeline-talk) ("t" . cube-pipeline-tell)
                  ("o" . cube-pipeline-open-plan)))
    (should (eq (lookup-key cube-pipeline-mode-map (kbd (car pair))) (cdr pair))))
  (let ((menu (cube-menu--global-menu)))
    (should (seq-find (lambda (item) (and (listp item) (equal (car item) "Pipelines")))
                      (cdr menu)))))

(ert-deftest cube-pipeline-dashboard-section-opens-focused-status ()
  (let ((cube-dashboard--data nil)
        (cube-dashboard--pending nil)
        (cube-dashboard-sections '(goals pipelines agents))
        (opened nil))
    (unwind-protect
        (progn
          (setf (alist-get 'pipelines cube-dashboard--data)
                (list :json (cube-test-read-fixture "pipeline-status.json")
                      :time (current-time) :error nil))
          (with-current-buffer (get-buffer-create "*cube*")
            (cube-dashboard-mode)
            (cube-dashboard--render)
            (goto-char (point-min))
            (re-search-forward "Protein function survey")
            (let ((item (cube-dashboard--current-item)))
              (should (eq (plist-get item :type) 'pipeline))
              (cl-letf (((symbol-function 'cube-pipeline-show)
                         (lambda (epic) (setq opened (cube-pipeline--id epic)))))
                (cube-dashboard-visit-item item))))
          (should (equal opened "cube-500")))
      (when (get-buffer "*cube*") (kill-buffer "*cube*")))))

(ert-deftest cube-pipeline-bounded-failures-render-in-place ()
  (let ((cube-pipelines--cache nil)
        (cube-pipelines--error nil))
    (unwind-protect
        (cl-letf (((symbol-function 'cube--call-json-async)
                   (lambda (_args _success failure)
                     (funcall failure 2 "cube: unknown command pipeline"))))
          (cube-pipeline-list)
          (with-current-buffer "*cube-pipelines*"
            (should (string-match-p "pipeline status failed (2): cube: unknown command pipeline"
                                    (buffer-string))))
          (cube-pipeline-show "cube-missing")
          (with-current-buffer "*cube-pipeline: cube-missing*"
            (should (string-match-p "pipeline status failed (2): cube: unknown command pipeline"
                                    (buffer-string)))))
      (when (get-buffer "*cube-pipelines*") (kill-buffer "*cube-pipelines*"))
      (when (get-buffer "*cube-pipeline: cube-missing*")
        (kill-buffer "*cube-pipeline: cube-missing*")))))

(provide 'cube-pipeline-test)
;;; cube-pipeline-test.el ends here
