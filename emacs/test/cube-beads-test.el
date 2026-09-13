;;; cube-beads-test.el --- Tests for cube-beads  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(ert-deftest cube-beads-normalize-cube-shape ()
  (let* ((beads (cube-beads--normalize-list (cube-test-read-fixture "ready.json")))
         (b (car beads)))
    (should (= (length beads) 4))
    (should (equal (alist-get 'id b) "cube-142"))
    (should (equal (alist-get 'type b) "task"))
    (should (equal (alist-get 'stage b) "implement"))
    (should (equal (alist-get 'kind b) "experiment"))
    (should (equal (alist-get 'student b) "alex-example"))
    (should (equal (alist-get 'parent b) "cube-100"))
    (should (null (alist-get 'deadline b)))
    (should (equal (alist-get 'deadline (nth 1 beads)) "2026-09-20"))))

(ert-deftest cube-beads-normalize-bd-shape ()
  (let* ((beads (cube-beads--normalize-list (cube-test-read-fixture "bd-ready.json")))
         (b (car beads)))
    (should (= (length beads) 2))
    (should (equal (alist-get 'type b) "task"))
    (should (equal (alist-get 'stage b) "implement"))
    (should (equal (alist-get 'kind b) "experiment"))
    (should (equal (alist-get 'student b) "alex-example"))
    (should (equal (alist-get 'status b) "open"))
    (should (null (alist-get 'student (nth 1 beads))))
    ;; a single object is a list of one
    (should (= (length (cube-beads--normalize-list (cube-test-read-fixture "bead-show.json"))) 1))
    (should (equal (cube-get (cube-beads--first (cube-test-read-fixture "bd-show.json")) 'id)
                   "cube-142"))
    (should (equal (cube-get (cube-beads--first (cube-test-read-fixture "bead-show.json")) 'id)
                   "cube-142"))))

(ert-deftest cube-beads-args ()
  (let ((cube-beads-program "bd") (cube-beads-default-labels nil))
    (should (equal (cube-beads--claim-args "cube-142") '("bd" "update" "cube-142" "--claim" "--json")))
    (should (equal (cube-beads--close-args "cube-142" "done")
                   '("bd" "close" "cube-142" "--reason" "done" "--json")))
    (should (equal (cube-beads--close-args "cube-142" "") '("bd" "close" "cube-142" "--json")))
    (should (equal (cube-beads--show-args "cube-1") '("bd" "show" "cube-1" "--json")))
    (should (equal (cube-beads--create-args '(:title "T"))
                   '("bd" "create" "T" "-t" "task" "-p" "2" "--silent")))
    (should (equal (cube-beads--create-args
                    '(:title "T" :type "epic" :priority 1 :labels ("kind:paper" "student:alex-example")
                      :parent "cube-100" :description "Body"))
                   '("bd" "create" "T" "-t" "epic" "-p" "1" "-l" "kind:paper,student:alex-example"
                     "--parent" "cube-100" "-d" "Body" "--silent")))
    (should-error (cube-beads--create-args '(:type "task")))
    (let ((cube-beads-default-labels '("src:cockpit")))
      (should (member "src:cockpit,x" (cube-beads--create-args '(:title "T" :labels ("x"))))))))

(ert-deftest cube-beads-render-org ()
  (let ((org (cube-beads--render-org (cube-test-read-fixture "bead-show.json"))))
    (should (string-prefix-p "#+title: cube-142: Implement mt-aware reassembly filter\n" org))
    (should (string-match-p "^\\* Implement mt-aware reassembly filter$" org))
    (should (string-match-p "^:BEAD: cube-142$" org))
    (should (string-match-p "^:STATUS: open$" org))
    (should (string-match-p "^:STAGE: implement$" org))
    (should (string-match-p "^:LABELS: stage:implement student:alex-example kind:experiment$" org))
    (should (string-match-p "^:PARENT: \\[\\[bead:cube-100\\]\\]$" org))
    (should (string-match-p "^#\\+begin_src yaml$" org))
    (should (string-match-p "^#\\+end_src$" org))
    (should (string-match-p "^\\*\\* Depends on\n- \\[\\[bead:cube-141\\]\\[Extract mt reads\\]\\] (closed)" org))
    (should (string-match-p "^\\*\\* Blocks\n- \\[\\[bead:cube-143\\]\\[Polish and annotate\\]\\] (open)" org))
    (should (string-match-p "^\\*\\* Comments\n- programmer, 2026-09-01T16:20:00Z ::\n  Started" org))
    ;; the bd shape renders too, without the optional sections
    (let ((plain (cube-beads--render-org (cube-beads--first (cube-test-read-fixture "bd-show.json")))))
      (should (string-match-p "Filter contigs" plain))
      (should-not (string-match-p "Depends on" plain)))))

(ert-deftest cube-beads-org-escape-body ()
  (should (equal (cube-beads--org-escape-body "* not a heading\ntext") " * not a heading\ntext"))
  (should (equal (cube-beads--org-escape-body "```py\nx = 1\n```") "#+begin_src py\nx = 1\n#+end_src"))
  (should (equal (cube-beads--org-escape-body nil) "")))

(ert-deftest cube-beads-fetch-with-fake-cube ()
  (cube-test-with-local
    (let ((result 'pending))
      (cube-beads--fetch-bead "cube-142" (lambda (b) (setq result b)))
      (cube-test-wait-until (not (eq result 'pending)))
      (should (equal (cube-get result 'title) "Implement mt-aware reassembly filter"))
      (should (cube-get result 'dependencies)))
    (let ((result 'pending))
      (cube-beads--fetch-ready (lambda (b) (setq result b)))
      (cube-test-wait-until (not (eq result 'pending)))
      (should (= (length result) 4)))))

(ert-deftest cube-beads-fetch-falls-back-to-bd ()
  (cube-test-with-local
    ;; `false' is on PATH and fails, so the fallback runs the fake bd
    (let ((cube-program "false") (result 'pending))
      (cube-beads--fetch-bead "cube-142" (lambda (b) (setq result b)))
      (cube-test-wait-until (not (eq result 'pending)))
      (should (equal (cube-get result 'id) "cube-142"))
      (should-not (cube-get result 'dependencies)))
    (let ((cube-program "false") (result 'pending))
      (cube-beads--fetch-ready (lambda (b) (setq result b)))
      (cube-test-wait-until (not (eq result 'pending)))
      (should (= (length result) 2))
      (should (equal (alist-get 'stage (car result)) "implement")))))

(ert-deftest cube-beads-claim-and-close-run-bd ()
  (cube-test-with-local
    (let* ((out (cube-test-temp-file "cube-bd-out"))
           (process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment))
           (cube-beads-confirm-writes nil))
      (cube-beads-claim "cube-142")
      (cube-beads-close "cube-150" "superseded")
      (cube-test-wait-until (with-temp-buffer (insert-file-contents out)
                                              (= 2 (count-lines (point-min) (point-max)))))
      (let ((lines (with-temp-buffer (insert-file-contents out)
                                     (split-string (buffer-string) "\n" t))))
        (should (member "bd update cube-142 --claim --json" lines))
        (should (member "bd close cube-150 --reason superseded --json" lines)))
      (delete-file out))))

(ert-deftest cube-beads-writes-ask-first ()
  (cube-test-with-local
    (let ((asked nil) (ran nil))
      (cl-letf (((symbol-function 'y-or-n-p) (lambda (_p) (setq asked t) nil))
                ((symbol-function 'cube-beads--run-write) (lambda (&rest _) (setq ran t))))
        (let ((cube-beads-confirm-writes t))
          (cube-beads-claim "cube-142")
          (should asked)
          (should-not ran))))))

(ert-deftest cube-beads-create-sync-with-fake-bd ()
  (cube-test-with-local
    (should (equal (cube-beads--create-sync '(:title "New bead")) "cube-999"))))

(ert-deftest cube-beads-heading-plist ()
  (with-temp-buffer
    (org-mode)
    (insert "* TODO [#A] Write the evaluation :alex:paper:\n"
            ":PROPERTIES:\n:PARENT: cube-100\n:LABELS: stage:design\n:END:\n"
            "First paragraph.\n\n- item\n")
    (goto-char (point-min))
    (let ((plist (cube-beads--heading-plist)))
      (should (equal (plist-get plist :title) "Write the evaluation"))
      (should (equal (plist-get plist :priority) 1))
      (should (equal (plist-get plist :parent) "cube-100"))
      (should (equal (plist-get plist :labels) '("alex" "paper" "stage:design")))
      (should (equal (plist-get plist :description) "First paragraph.\n\n- item")))))

(ert-deftest cube-beads-capture-finalize-rewrites-bead-property ()
  (with-temp-buffer
    (org-mode)
    (insert "* TODO Draft the rebuttal\n:PROPERTIES:\n:BEAD: pending\n:END:\nBody text\n")
    (let ((seen nil))
      (should (equal (cube-beads--capture-finalize
                      (lambda (plist) (setq seen plist) "cube-999"))
                     "cube-999"))
      (should (equal (plist-get seen :title) "Draft the rebuttal"))
      (should (equal (plist-get seen :description) "Body text"))
      (should (equal (org-entry-get (point-min) "BEAD") "cube-999"))
      ;; a second finalize leaves the real id alone
      (should-not (cube-beads--capture-finalize (lambda (_) "cube-1000")))
      (should (equal (org-entry-get (point-min) "BEAD") "cube-999")))))

(ert-deftest cube-beads-capture-template-installed ()
  (let ((org-capture-templates nil)
        (org-capture-before-finalize-hook nil))
    (cube-beads-install-capture)
    (should (equal (car (assoc "b" org-capture-templates)) "b"))
    (should (equal (nth 3 (assoc "b" org-capture-templates)) '(file cube-beads-inbox-file)))
    (should (string-match-p ":BEAD: pending" (nth 4 (assoc "b" org-capture-templates))))
    (should (memq #'cube-beads-capture-finalize org-capture-before-finalize-hook))
    ;; idempotent
    (cube-beads-install-capture)
    (should (= 1 (seq-count (lambda (tpl) (equal (car tpl) "b")) org-capture-templates)))))

(ert-deftest cube-beads-org-link-type ()
  (should (org-link-get-parameter "bead" :follow))
  (should (equal (cube-beads-link-export "cube-142" "Reassembly" 'html)
                 "<code>Reassembly (bead cube-142)</code>"))
  (should (equal (cube-beads-link-export "cube-142" nil 'ascii) "bead cube-142"))
  (should (equal (cube-beads-link-export "cube-142" "" 'latex) "\\texttt{bead cube-142}"))
  (let ((shown nil))
    (cl-letf (((symbol-function 'cube-beads-show) (lambda (id) (setq shown id))))
      (cube-beads-link-follow " cube-142 ")
      (should (equal shown "cube-142")))))

(ert-deftest cube-beads-show-renders-buffer ()
  (cube-test-with-local
    (let ((name (cube-beads--buffer-name "cube-142")))
      (when (get-buffer name) (kill-buffer name))
      (save-window-excursion
        (cube-beads-show "cube-142")
        (cube-test-wait-until (and (get-buffer name)
                                   (with-current-buffer name (> (buffer-size) 0))))
        (with-current-buffer name
          (should (derived-mode-p 'org-mode))
          (should cube-bead-mode)
          (should (equal cube-bead--id "cube-142"))
          (should (string-match-p ":BEAD: cube-142" (buffer-string)))))
      (kill-buffer name))))

(ert-deftest cube-beads-list-with-fake ()
  (cube-test-with-local
    (when (get-buffer "*cube-beads*") (kill-buffer "*cube-beads*"))
    (save-window-excursion
      (cube-beads-list)
      (cube-test-wait-until (with-current-buffer "*cube-beads*" (= (length tabulated-list-entries) 4)))
      (with-current-buffer "*cube-beads*"
        (should (derived-mode-p 'cube-beads-mode))
        (goto-char (point-min))
        ;; The column names are printed into the buffer so the header line can
        ;; carry the key legend, so the first entry is on the second line.
        (forward-line 1)
        (should (member (tabulated-list-get-id) '("cube-142" "cube-150" "cube-171" "cube-180")))))
    (kill-buffer "*cube-beads*")))

(provide 'cube-beads-test)
;;; cube-beads-test.el ends here
