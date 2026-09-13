;;; cube-goals-test.el --- Tests for goals and the People board  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(ert-deftest cube-goal-row-renders-bar-glyph-days-blockers-and-people ()
  (let* ((goal (car (cube-get (cube-test-read-fixture "goals.json") 'goals)))
         (row (cube-goal--row-text goal)))
    (should (string-match-p "✓" row))
    (should (string-match-p "[[]#####-----[]]" row))
    (should (string-match-p " 50%" row))
    (should (string-match-p "28d left" row))
    (should (string-match-p "blockers 1" row))
    (should (string-match-p "AE,FF" row)))
  (should (equal (cube-goal--on-track-glyph '((on_track . :false))) "!"))
  (should (equal (cube-goal--on-track-glyph '((on_track . nil))) "?")))

(ert-deftest cube-goal-buffer-text-has-header-and-three-driver-groups ()
  (let ((text (cube-goal--render-text (cube-test-read-fixture "goal-show.json"))))
    (should (string-match-p "Goal: Publish the mitochondrial assembly benchmark" text))
    (should (string-match-p "Target: 2026-09-30" text))
    (should (string-match-p "Project: mt-assembly" text))
    (should (string-match-p "Benchmark data and code are archived" text))
    (should (string-match-p "\nAgents\n" text))
    (should (string-match-p "cube-403  programmer  ready" text))
    (should (string-match-p "\nPeople\n" text))
    (should (string-match-p "Bring the reassembly benchmark" text))
    (should (string-match-p "\nBlockers\n" text))
    (should (string-match-p "Reference set awaits curation" text))))

(ert-deftest cube-goal-new-arguments-and-write-gate ()
  (let ((plist '(:title "Archive benchmark" :target "2026-09-30"
                :success ("Code is archived" "Data is archived")
                :project "mt-assembly" :people ("alex-example" "fin-fellow")
                :provenance ("doc/plan.md::Goals"))))
    (should
     (equal (cube-goal--new-args plist)
            '("goal" "new" "--title" "Archive benchmark" "--target" "2026-09-30"
              "--success" "Code is archived" "--success" "Data is archived"
              "--project" "mt-assembly" "--person" "alex-example" "--person" "fin-fellow"
              "--provenance" "doc/plan.md::Goals" "--dry-run"))))
  (should-error (cube-goal--new-args '(:title "No evidence" :target "2026-09-30"
                                        :success ("done"))))
  (let ((calls nil) (cube-goals-confirm-writes t))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error)
                 (push args calls)
                 (funcall callback '((applied . :false)))))
              ((symbol-function 'cube-goal--show-plan) (lambda (&rest _) nil))
              ((symbol-function 'y-or-n-p) (lambda (_prompt) nil)))
      (cube-goal--write '("goal" "spin" "cube-400" "--dry-run") "spin"))
    (should (equal calls '(("goal" "spin" "cube-400" "--dry-run"))))))

(ert-deftest cube-goal-fixtures-drive-goals-and-goal-show ()
  (cube-test-with-local
    (cube-goals-refresh)
    (cube-test-wait-until cube-goals--cache)
    (should (equal (cube-goal--id (car cube-goals--cache)) "cube-400"))
    (let ((buffer (get-buffer-create "*cube-goal: cube-400*")))
      (unwind-protect
          (progn
            (with-current-buffer buffer
              (cube-goal-mode)
              (setq cube-goal--goal (list (cons 'id "cube-400")))
              (cube-goal-revert))
            (cube-test-wait-until
              (with-current-buffer buffer
                (string-match-p "Manuscript passes" (buffer-string))))
            (with-current-buffer buffer
              (should (derived-mode-p 'cube-goal-mode))))
        (kill-buffer buffer)))))

(ert-deftest cube-people-board-rows-use-goals-owed-meetings-and-milestones ()
  (let* ((people (cube-get (cube-test-read-fixture "people.json") 'people))
         (now (encode-time (iso8601-parse "2026-09-02T09:15:00+03:00")))
         (entries (cube-people--entries people now))
         (alex (assoc "alex-example" entries))
         (columns (cadr alex)))
    (should (= (length entries) 3))
    (should (equal (aref columns 1) "phd"))
    (should (equal (aref columns 2) "1"))
    (should (equal (aref columns 3) "1"))
    (should (equal (aref columns 4) "5d ago"))
    (should (string-match-p "proposal defense (74d)" (aref columns 5)))))

(ert-deftest cube-person-dossier-includes-owed-items-and-next-agenda ()
  (let* ((student (cube-test-read-fixture "student-alex.json"))
         (person (car (cube-get (cube-test-read-fixture "people.json") 'people)))
         (text (cube-org--student-context-org student person)))
    (should (string-match-p "[*][*] Owed items" text))
    (should (string-match-p "Bring the reassembly benchmark" text))
    (should (string-match-p "[*][*] Next meeting agenda" text))
    (should (string-match-p "Proposal defense outline" text))))

(ert-deftest cube-goals-and-people-bindings-are-in-the-command-table ()
  (should (eq (lookup-key cube-command-map (kbd "G")) #'cube-goal-new))
  (should (eq (lookup-key cube-command-map (kbd "u")) #'cube-people))
  (should (eq (lookup-key cube-command-map (kbd "U")) #'cube-budget))
  (should (eq (lookup-key cube-goal-mode-map (kbd "G")) #'cube-goal-new))
  (dolist (map '(cube-goal-mode-map cube-people-mode-map))
    (should (lookup-key (symbol-value map) (kbd "?")))))

(provide 'cube-goals-test)
;;; cube-goals-test.el ends here
