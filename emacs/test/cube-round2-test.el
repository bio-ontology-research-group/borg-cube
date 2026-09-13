;;; cube-round2-test.el --- Tests for projects, assignment and roster  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(ert-deftest cube-project-rows-sort-and-render-purely ()
  (let* ((json (cube-test-read-fixture "projects.json"))
         (people (cube-get (cube-test-read-fixture "people.json") 'people))
         (now (encode-time (iso8601-parse "2026-09-02T09:15:00+03:00")))
         (rows (cube-project--row-items json people now)))
    (should (equal (mapcar (lambda (row) (plist-get row :id)) rows)
                   '("kobayashi-marust" "mt-assembly" "ontology-kg")))
    (let ((mt (seq-find (lambda (row) (equal (plist-get row :id) "mt-assembly")) rows)))
      (should (string-match-p "● Mitochondrial assembly" (plist-get mt :label)))
      (should (string-match-p "lead Alex Example" (plist-get mt :detail)))
      (should (string-match-p "8 open/2 in progress" (plist-get mt :detail)))
      (should (string-match-p "3 papers  1 software  5m" (plist-get mt :detail))))))

(ert-deftest cube-project-buffer-text-renders-project-facts-and-beads ()
  (let* ((project (seq-find (lambda (item) (equal (cube-get item 'slug) "mt-assembly"))
                            (cube-get (cube-test-read-fixture "projects.json") 'projects)))
         (people (cube-get (cube-test-read-fixture "people.json") 'people))
         (beads (cube-project--beads-for
                 "mt-assembly"
                 (cube-beads--normalize-list (cube-test-read-fixture "ready.json"))))
         (text (cube-project--render-text project beads people)))
    ;; The fixture order is deliberately not the activity order.
    (should (string-match-p "Mitochondrial assembly" text))
    (should (string-match-p "Members\n- Alex Example (alex-example)" text))
    (should (string-match-p "grant-mt-2024" text))
    (should (string-match-p "reassembly filters" text))
    (should (string-match-p "Implement mt-aware reassembly filter" text))))

(ert-deftest cube-project-buffer-bead-row-is-visitable ()
  (let* ((project (seq-find (lambda (item) (equal (cube-get item 'slug) "mt-assembly"))
                            (cube-get (cube-test-read-fixture "projects.json") 'projects)))
         (beads (cube-project--beads-for
                 "mt-assembly"
                 (cube-beads--normalize-list (cube-test-read-fixture "ready.json"))))
         (buffer (get-buffer-create "*cube-project: test*")))
    (unwind-protect
        (with-current-buffer buffer
          (cube-project-mode)
          (setq cube-project--project project cube-project--beads beads
                cube-project--people nil)
          (cube-project--render)
          (should (string-match-p "Beads (1)" (buffer-string)))
          (goto-char (point-min))
          (re-search-forward "Implement mt-aware")
          (let ((shown nil))
            (cl-letf (((symbol-function 'cube-beads-show)
                       (lambda (id) (setq shown id))))
              (cube-project--visit)
              (should (equal shown "cube-142")))))
      (kill-buffer buffer))))

(ert-deftest cube-beads-assign-and-create-argument-builders ()
  (should (equal
           (cube-beads--assign-args
            "cube-142"
            '(:role "programmer" :person "alex-example" :project "mt-assembly"
              :deadline "2026-09-20" :note "start" :run t))
           '("assign" "cube-142" "--role" "programmer" "--person" "alex-example"
             "--project" "mt-assembly" "--deadline" "2026-09-20" "--note" "start"
             "--run" "--dry-run")))
  (should (equal
           (cube-beads--cube-create-args
            '(:title "A bead" :kind "task" :role "programmer"
              :acceptance "It passes" :provenance ("path::line")))
           '("create" "--title" "A bead" "--kind" "task" "--role" "programmer"
             "--acceptance" "It passes" "--provenance" "path::line" "--dry-run")))
  (should-error (cube-beads--cube-create-args
                 '(:title "Missing evidence" :acceptance "yes")))
  (should-error (cube-beads--cube-create-args
                 '(:title "Missing acceptance" :provenance ("path::line")))))

(ert-deftest cube-beads-write-gate-never-applies-without-confirmation ()
  (let ((calls nil)
        (cube-beads-confirm-writes t))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error-callback)
                 (push args calls)
                 (funcall callback (cube-test-read-fixture "assign.json"))))
              ((symbol-function 'y-or-n-p) (lambda (_prompt) nil)))
      (cube-beads--write-cube
       (cube-beads--assign-args "cube-142" '(:project "mt-assembly")) "assign"))
    (should (= (length calls) 1))
    (should (member "--dry-run" (car calls)))
    (should-not (member "--apply" (car calls)))))

(ert-deftest cube-org-write-arguments-and-gate ()
  (should (equal (cube-org--append-args "~/org/alex.org" "Meeting" "2026-09-02"
                                        '("one" "two") nil)
                 '("org" "append" "~/org/alex.org" "--heading" "Meeting"
                   "--date" "2026-09-02" "--item" "one" "--item" "two" "--dry-run")))
  (should (equal (cube-org--todo-args "~/org/alex.org" "Meeting" "one" t "--apply")
                 '("org" "todo" "~/org/alex.org" "--heading-match" "Meeting"
                   "--item" "one" "--done" "--apply")))
  (should (equal (cube-org--property-args "~/org/alex.org" "Meeting" "RUN" "r-1")
                 '("org" "property" "~/org/alex.org" "--heading-match" "Meeting"
                   "--set" "RUN=r-1" "--dry-run")))
  (should (equal (cube-org--status-args "alex-example")
                 '("org" "status" "--person" "alex-example")))
  (let ((calls nil) (cube-org-confirm-writes t))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error-callback)
                 (push args calls)
                 (funcall callback (cube-test-read-fixture "org-property.json"))))
              ((symbol-function 'y-or-n-p) (lambda (_prompt) nil)))
      (cube-org--write (cube-org--property-args "file" "Heading" "A" "B")
                       "property A" nil))
    (should (= (length calls) 1))
    (should (member "--dry-run" (car calls)))
    (should-not (member "--apply" (car calls)))
    (with-current-buffer "*cube-org-diff*"
      (should (derived-mode-p 'diff-mode)))
    (kill-buffer "*cube-org-diff*")))

(ert-deftest cube-roster-table-renders-checks-and-conflict-values ()
  (let ((text (cube-roster--table-text (cube-test-read-fixture "roster.json")))
        (conflict (cadr (cube-get (cube-test-read-fixture "roster.json") 'people))))
    (should (string-match-p "Roster" text))
    (should (string-match-p "Alex Example" text))
    (should (string-match-p "✓" text))
    (should (string-match-p "Gus Student.*conflict" text))
    (let ((values (cube-roster--conflict-text conflict)))
      (should (string-match-p "name:" values))
      (should (string-match-p "staff_org: Gus Student" values))
      (should (string-match-p "website: Gus S. Student" values)))))

(ert-deftest cube-roster-sync-arguments-and-transient-keys ()
  (should (equal (cube-roster--sync-args) '("roster" "sync" "--dry-run")))
  (should (equal (cube-roster--sync-args "--apply") '("roster" "sync" "--apply")))
  (dolist (key '("RET" "s" "S" "g" "q"))
    (should (lookup-key cube-roster-mode-map (kbd key)))))

(provide 'cube-round2-test)
;;; cube-round2-test.el ends here
