;;; cube-org-test.el --- Tests for cube-org  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(defconst cube-test-org-newest-first
  "* Todo items

- XRF \"gun\"


** 27 January 2025
- QC on 16S, 18S, WGS

** 27 November, meeting with corelabs
- 450 bacterial cultures

** 24 November 2024
- plan for isolation

*** Bioinformatics tools to include
- assembly

** 6 November 2024
- first meeting
"
  "Sample in the empty_quarter.org style: newest first, level 2.")

(defconst cube-test-org-oldest-first
  "* Todo 4 Nov 2024
- write algorithm down formally

* Projects

** Pathway analysis

* Notes

** Discussion 6 November 2023
- idea

** Meeting 20 November 2023
- progress
*** Sub item
- x

* Academics
"
  "Sample in the alex.org style: a Notes section, oldest first.")

(defconst cube-test-org-notes-only
  "* Projects

** Something

* Notes

* Academics
"
  "Sample without dated headings but with a Notes heading.")

(defun cube-test-org-position (text)
  "Return (POS . LEVEL) and the line at POS for TEXT."
  (with-temp-buffer
    (insert text)
    (let ((where (cube-org--insert-position)))
      (goto-char (car where))
      (list (car where) (cdr where)
            (buffer-substring-no-properties (line-beginning-position) (line-end-position))))))

(ert-deftest cube-org-heading-date-forms ()
  (should (equal (cube-org--heading-date "** 27 January 2025") '(2 27 1 2025)))
  (should (equal (cube-org--heading-date "** Meeting 20 November 2023") '(2 20 11 2023)))
  (should (equal (cube-org--heading-date "* Todo 4 Nov 2024") '(1 4 11 2024)))
  (should (equal (cube-org--heading-date "*** 16 April 2026") '(3 16 4 2026)))
  (should (equal (cube-org--heading-date "** 13 Nov 2024") '(2 13 11 2024)))
  (should (equal (cube-org--heading-date "** 27 November, meeting with corelabs") '(2 27 11 nil)))
  (should (equal (cube-org--heading-date "** 23 Oct") '(2 23 10 nil)))
  (should (equal (cube-org--heading-date "** 1 Sept 2025") '(2 1 9 2025)))
  (should-not (cube-org--heading-date "** Pathway analysis"))
  (should-not (cube-org--heading-date "- 30 June 2026 contract end"))
  (should-not (cube-org--heading-date "** 2024 plan")))

(ert-deftest cube-org-insert-position-newest-first ()
  (pcase-let ((`(,_pos ,level ,line) (cube-test-org-position cube-test-org-newest-first)))
    (should (= level 2))
    (should (equal line "** 27 January 2025"))))

(ert-deftest cube-org-insert-position-oldest-first-goes-after-last ()
  (pcase-let ((`(,pos ,level ,line) (cube-test-org-position cube-test-org-oldest-first)))
    (should (= level 2))
    ;; after the whole subtree of the last dated heading, before the next top level
    (should (equal line "* Academics"))
    (with-temp-buffer
      (insert cube-test-org-oldest-first)
      (goto-char pos)
      (should (looking-back "- x\n\n" (- pos 6))))))

(ert-deftest cube-org-note-level-headings ()
  (with-temp-buffer
    (insert cube-test-org-oldest-first)
    (let ((dated (cube-org--dated-headings)))
      (should (= (length dated) 3))
      ;; the level 1 todo heading is not where the notes live
      (should (equal (mapcar #'cadr (cube-org--note-level-headings dated)) '(2 2)))))
  (with-temp-buffer
    (insert "* 1 January 2025\n** 2 January 2025\n")
    ;; ties go to the deeper level
    (should (equal (mapcar #'cadr (cube-org--note-level-headings (cube-org--dated-headings)))
                   '(2)))))

(ert-deftest cube-org-insert-position-notes-heading ()
  (pcase-let ((`(,_pos ,level ,line) (cube-test-org-position cube-test-org-notes-only)))
    (should (= level 2))
    (should (equal line ""))
    (with-temp-buffer
      (insert cube-test-org-notes-only)
      (goto-char (car (cube-org--insert-position)))
      (forward-line -1)
      (should (looking-at-p "\\* Notes")))))

(ert-deftest cube-org-insert-position-empty-file ()
  (should (equal (cube-org--insert-position) (cons 1 2)))
  (with-temp-buffer
    (insert "* Only heading\n- text\n")
    (should (equal (cube-org--insert-position) (cons (point-max) 2)))))

(ert-deftest cube-org-insert-heading-newest-first-sample ()
  (with-temp-buffer
    (insert cube-test-org-newest-first)
    (let ((where (cube-org--insert-position)))
      (cube-org--insert-heading-at (car where) (cdr where) "2 September 2026")
      (should (looking-back "^- " (line-beginning-position)))
      (should (string-match-p
               "- XRF \"gun\"\n\n\n\\*\\* 2 September 2026\n- \n\n\\*\\* 27 January 2025"
               (buffer-string))))))

(ert-deftest cube-org-ensure-today-heading ()
  (with-temp-buffer
    (insert cube-test-org-newest-first)
    (let* ((today (cube-org--today-title))
           (first (cube-org--ensure-today-heading))
           (second (cube-org--ensure-today-heading)))
      (should (equal first second))
      (should (= (cdr first) 2))
      (should (= 1 (how-many (concat "^\\*\\* " (regexp-quote today) "$") (point-min) (point-max)))))))

(ert-deftest cube-org-today-title-format ()
  (let ((cube-org-meeting-heading-format "%-d %B %Y"))
    (should (equal (cube-org--today-title (encode-time '(0 0 12 4 11 2024 nil nil t)))
                   "4 November 2024"))))

(ert-deftest cube-org-md-to-org ()
  (let ((org (cube-org-md->org (cube-get (cube-test-read-fixture "run-show.json") 'notes) 3)))
    (should (string-match-p "^\\*\\*\\* Progress note: Alex Example$" org))
    (should (string-match-p "^\\*\\*\\*\\* Evidence$" org))
    (should (string-match-p "^- 14 commits in alex/mt-assembly" org))
    (should (string-match-p "Draft =main.tex= touched" org))
    (should (string-match-p "^2\\. Reassembly artifact (269 nt fusion): \\*status\\* of" org))
    (should (string-match-p "\\[\\[bead:cube-103\\]\\[the milestone\\]\\]" org))
    (should (string-match-p "^#\\+begin_src sh\ncube student alex-example --json\n#\\+end_src" org)))
  (should (equal (cube-org-md->org "# T\n\n* a\n* b\n\n_em_ and __strong__\n---\n> quoted")
                 "* T\n\n- a\n- b\n\n/em/ and *strong*\n-----\nquoted"))
  (should (equal (cube-org-md->org "*not a heading") " *not a heading"))
  (should (equal (cube-org-md->org "snake_case_name stays") "snake_case_name stays"))
  (should (equal (cube-org-md->org nil) "")))

(ert-deftest cube-org-agent-notes-block ()
  (let ((block (cube-org--agent-notes-block "r-1" "* Top\n** Sub\ntext\n" 3)))
    (should (equal block "*** Agent notes :draft:\n:PROPERTIES:\n:RUN: r-1\n:END:\n**** Top\n***** Sub\ntext\n")))
  (should (string-match-p "^:RUN: unknown$" (cube-org--agent-notes-block nil "text" 2)))
  (should (equal (cube-org--demote "no headings" 4) "no headings")))

(ert-deftest cube-org-insert-agent-notes-under-today ()
  (with-temp-buffer
    (org-mode)
    (insert cube-test-org-newest-first)
    (cube-org--insert-agent-notes "r-20260901-0700-k1" "# Note\n\n- one\n")
    (let ((text (buffer-string))
          (today (cube-org--today-title)))
      (should (string-match-p (concat "^\\*\\* " (regexp-quote today) "\n- \n\n"
                                      "\\*\\*\\* Agent notes :draft:\n:PROPERTIES:\n"
                                      ":RUN: r-20260901-0700-k1\n:END:\n"
                                      "\\*\\*\\*\\* Note\n\n- one\n\n\\*\\* 27 January 2025")
                              text)))))

(ert-deftest cube-org-parse-staff ()
  (let* ((people (cube-org--parse-staff
                  (with-temp-buffer
                    (insert-file-contents (cube-test-fixture "staff.org"))
                    (buffer-string))))
         (alex (cube-org--person "alex-example" people))
         (fin (cube-org--person "Fin Fellow" people))
         (eve (cube-org--person "eve-sample" people)))
    (should (= (length people) 6))
    (should (equal (cube-get alex 'name) "Alex Example"))
    (should (equal (cube-get alex 'role) "phd"))
    (should (equal (cube-get alex 'org_file) "~/org/alex.org"))
    (should (equal (cube-get fin 'slug) "fin-fellow"))
    (should (equal (cube-get fin 'role) "postdoc"))
    (should (equal (cube-get eve 'role) "msc"))
    (should (equal (cube-get (cube-org--person "carla-staff" people) 'role) "staff"))
    ;; "** Carla" under "* Research staff" is not a roster entry
    (should-not (cube-org--person "carla" people))))

(ert-deftest cube-org-people-fake-and-fallback ()
  (cube-test-with-local
    (let ((cube-org--people nil))
      (should (= (length (cube-org-people)) 3))
      (should (equal (cube-get (cube-org--person "alex-example") 'org_file) "~/org/alex.org")))
    (let ((cube-org--people nil)
          (cube-program "false")
          (cube-org-directory cube-test-fixtures))
      (should (= (length (cube-org-people t)) 6))
      (should (equal (cube-get (cube-org--person "Alex Example") 'slug) "alex-example")))))

(ert-deftest cube-org-person-file-remote-and-local ()
  (let ((person '((slug . "alex-example") (org_file . "~/org/alex.org"))))
    (cube-test-with-remote
      (should (equal (cube-org--person-file person) "/ssh:ws:~/org/alex.org"))
      (should (equal (cube-org--person-file '((slug . "gus-student"))) "/ssh:ws:~/org/gus.org"))
      (should (equal (cube-org-file "papers.org") "/ssh:ws:~/org/papers.org")))
    (cube-test-with-local
      (should (equal (cube-org--person-file person) (expand-file-name "~/org/alex.org")))
      (should (equal (cube-org-file "papers.org") (expand-file-name "~/org/papers.org"))))))

(defconst cube-test-papers-org
  "#+TODO: READY_TO_SUBMIT SUBMITTED REVISING PAUSED TODO | PUBLISHED CANCELED
#+OPTIONS: toc:1

* In preparation

** Scincus mt
- mitogenome

** Syntactic encoding of ontology axioms

* Ready to submit or submitted

** REVISING Genome-scale PFP evaluation
- rebuttal due

** SUBMITTED [#A] Adverse Event Prediction :ml:
"
  "Sample papers.org with the custom TODO sequence.")

(ert-deftest cube-org-todo-keywords ()
  (should (equal (cube-org--todo-keywords cube-test-papers-org)
                 '("READY_TO_SUBMIT" "SUBMITTED" "REVISING" "PAUSED" "TODO" "PUBLISHED" "CANCELED")))
  (should (equal (cube-org--todo-keywords "#+TODO: TODO(t) | DONE(d)") '("TODO" "DONE")))
  (should (null (cube-org--todo-keywords "no keywords"))))

(ert-deftest cube-org-paper-states ()
  (let ((states (cube-org--paper-states cube-test-papers-org)))
    (should (equal states
                   '(("Scincus mt") ("Syntactic encoding of ontology axioms")
                     ("Genome-scale PFP evaluation" . "REVISING")
                     ("Adverse Event Prediction" . "SUBMITTED"))))))

(ert-deftest cube-org-papers-diff ()
  (let* ((papers (cube-get (cube-test-read-fixture "papers.json") 'papers))
         (states (cube-org--paper-states cube-test-papers-org))
         (diff (cube-org--papers-diff papers states)))
    (should (= (length diff) 2))
    (let ((pfp (car diff)) (mt (cadr diff)))
      (should (equal (plist-get pfp :id) "cube-210"))
      (should (equal (plist-get pfp :heading) "Genome-scale PFP evaluation"))
      (should (equal (plist-get pfp :backend) "REVISION"))
      (should (equal (plist-get pfp :org) "REVISING"))
      (should (plist-get pfp :found))
      (should (equal (plist-get mt :heading) "Scincus mt"))
      (should (equal (plist-get mt :backend) "DRAFT"))
      (should (null (plist-get mt :org))))
    ;; agreeing states produce no entry; unknown headings are reported
    (should (null (cube-org--papers-diff
                   '(((id . "x") (state . "REVISING") (org_heading . "papers.org::*Genome-scale PFP")))
                   states)))
    (let ((missing (cube-org--papers-diff
                    '(((id . "y") (title . "Nowhere") (state . "TODO")))
                    states)))
      (should (= (length missing) 1))
      (should-not (plist-get (car missing) :found)))))

(ert-deftest cube-org-apply-paper-state-keeps-todo-sequence ()
  (let ((file (cube-test-temp-file "cube-papers" cube-test-papers-org ".org")))
    (unwind-protect
        (progn
          (cube-org--apply-paper-state file "Scincus mt" "SUBMITTED")
          (cube-org--apply-paper-state file "Genome-scale PFP evaluation" "PUBLISHED")
          (let ((text (with-temp-buffer (insert-file-contents file) (buffer-string))))
            (should (string-prefix-p "#+TODO: READY_TO_SUBMIT SUBMITTED REVISING PAUSED TODO | PUBLISHED CANCELED\n" text))
            (should (string-match-p "^\\*\\* SUBMITTED Scincus mt$" text))
            (should (string-match-p "^\\*\\* PUBLISHED Genome-scale PFP evaluation$" text))
            (should (string-match-p "^\\*\\* SUBMITTED \\[#A\\] Adverse Event Prediction" text)))
          (should-error (cube-org--apply-paper-state file "Nope" "TODO") :type 'user-error))
      (when-let* ((buf (find-buffer-visiting file))) (kill-buffer buf))
      (delete-file file))))

(ert-deftest cube-org-heading-title ()
  (should (equal (cube-org--heading-title "papers.org::*Genome-scale PFP") "Genome-scale PFP"))
  (should (equal (cube-org--heading-title "*** Deep heading") "Deep heading"))
  (should (null (cube-org--heading-title nil))))

(ert-deftest cube-org-student-context-org ()
  (let ((org (cube-org--student-context-org (cube-test-read-fixture "student-alex.json"))))
    (should (string-prefix-p "#+title: Alex Example\n" org))
    (should (string-match-p "^\\* Alex Example (phd)$" org))
    (should (string-match-p "\\[\\[bead:cube-100\\]\\[PhD program: Alex Example\\]\\]" org))
    (should (string-match-p "^- \\[X\\] coursework, due 2025-05-31 \\[\\[bead:cube-101\\]\\]$" org))
    (should (string-match-p "^- \\[ \\] proposal defense, due 2026-11-15 (74 days) \\[\\[bead:cube-103\\]\\]$" org))
    (should (string-match-p "^\\*\\* Agenda draft :draft:\n- Proposal outline" org))
    (should (string-match-p "^- Commits (7 days): 14$" org))
    (should (string-match-p "r-20260901-0700-k1" org))))

(ert-deftest cube-org-student-context-buffer-with-fake ()
  (cube-test-with-local
    (let ((name "*cube-student: alex-example*"))
      (when (get-buffer name) (kill-buffer name))
      (save-window-excursion
        (cube-org-student-context "alex-example")
        (cube-test-wait-until (get-buffer name))
        (with-current-buffer name
          (should (derived-mode-p 'org-mode))
          (should (string-match-p "Alex Example" (buffer-string)))))
      (kill-buffer name))))

(ert-deftest cube-org-pull-meeting-notes-end-to-end ()
  (cube-test-with-local
    (let* ((file (cube-test-temp-file "cube-alex" cube-test-org-newest-first ".org"))
           (cube-org--people (list (list (cons 'slug "alex-example") (cons 'name "Alex Example")
                                         (cons 'org_file file))))
           (done nil))
      (unwind-protect
          (save-window-excursion
            (cube-org-pull-meeting-notes "alex-example")
            (cube-test-wait-until (with-current-buffer (or (find-buffer-visiting file) (current-buffer))
                                    (setq done (string-match-p ":RUN: r-20260901-0700-k1" (buffer-string)))))
            (should done)
            (with-current-buffer (find-buffer-visiting file)
              (should (string-match-p "\\*\\*\\* Agent notes :draft:" (buffer-string)))
              (should (string-match-p "\\*\\*\\*\\* Progress note: Alex Example" (buffer-string)))))
        (when-let* ((buf (find-buffer-visiting file)))
          (with-current-buffer buf (set-buffer-modified-p nil))
          (kill-buffer buf))
        (delete-file file)))))

(provide 'cube-org-test)
;;; cube-org-test.el ends here
