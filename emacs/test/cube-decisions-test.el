;;; cube-decisions-test.el --- Tests for cube-decisions  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(defun cube-test-decisions ()
  "Return the pending decisions of the fixture."
  (append (cube-get (cube-test-read-fixture "decisions.json") 'decisions) nil))

(defmacro cube-test-with-decisions (&rest body)
  "Run BODY with the fixture decisions cached and a fresh buffer."
  (declare (indent 0))
  `(let ((cube-decisions--items (cube-test-decisions))
         (cube-decisions--answered
          (append (cube-get (cube-test-read-fixture "decisions.json") 'answered) nil))
         (cube-decisions--generated "2026-09-04T09:00:00+03:00")
         (cube-decisions--error nil)
         (cube-decisions-confirm nil)
         (cube-decisions-update-hook nil))
     (when (get-buffer cube-decisions-buffer) (kill-buffer cube-decisions-buffer))
     (unwind-protect
         (progn ,@body)
       (when (get-buffer cube-decisions-buffer) (kill-buffer cube-decisions-buffer)))))

(defun cube-test-decision (id)
  "Return the fixture decision with ID."
  (seq-find (lambda (item) (equal (cube-decisions--id item) id)) (cube-test-decisions)))

(defun cube-test-fake-out (&optional name)
  "Return a temporary file that records the fake cube invocations, named NAME."
  (cube-test-temp-file (or name "cube-decide-out")))

(defun cube-test-recorded (file)
  "Return the recorded fake cube invocations in FILE."
  (with-temp-buffer (insert-file-contents file) (buffer-string)))

;;;; Pure helpers

(ert-deftest cube-decisions-kinds-options-and-sections ()
  (let ((permission (cube-test-decision "cube-401"))
        (question (cube-test-decision "cube-402"))
        (proposal (cube-test-decision "cube-403"))
        (approval (cube-test-decision "apr-20260904-085500-ab")))
    (should (equal (cube-decisions--section permission) "Permissions"))
    (should (equal (cube-decisions--section question) "Questions"))
    (should (equal (cube-decisions--section approval) "Approvals"))
    (should (equal (cube-decisions--section proposal) "Other"))
    (should (equal (cube-decisions--affirm permission) "yes"))
    (should (equal (cube-decisions--deny permission) "no"))
    (should (cube-decisions--free-p question))
    (should (cube-decisions--approval-p approval))
    (should (equal (cube-decisions--host question) "laptop"))
    (should-not (cube-decisions--host approval))
    (should (equal (cube-decisions--bead approval) "cube-301"))
    (should (equal (cube-decisions--evidence question) "runs/r-77#result.json"))))

(ert-deftest cube-decisions-button-labels-follow-the-backend-options ()
  (should (equal (cube-decisions--button-labels (cube-test-decision "cube-401"))
                 '(("Yes" . "yes") ("No" . "no"))))
  (should (equal (cube-decisions--button-labels (cube-test-decision "apr-20260904-085500-ab"))
                 '(("Approve" . "approve") ("Reject" . "reject"))))
  (should (equal (cube-decisions--button-labels (cube-test-decision "cube-403"))
                 '(("Accept" . "accept") ("Reject" . "reject") ("Answer" . nil))))
  (should (equal (cube-decisions--button-labels (cube-test-decision "cube-402"))
                 '(("Answer" . nil)))))

(ert-deftest cube-decisions-row-text-and-decide-args ()
  (let ((row (cube-decisions--row-text (cube-test-decision "cube-401"))))
    (should (string-match-p "\\`agent:ontology " row))
    (should (string-match-p " 1h " row))
    (should (string-match-p "run the IBEX benchmark\\'" row)))
  (should (equal (cube-decisions--decide-args "cube-401" "yes")
                 '("decide" "cube-401" "--choice" "yes" "--apply")))
  (should (equal (cube-decisions--decide-args "cube-402" nil "the KAUST one")
                 '("decide" "cube-402" "--text" "the KAUST one" "--apply")))
  (should (equal (cube-decisions-relay-args (cube-test-decision "cube-402") "the KAUST one")
                 '("agent" "tell" "liaison" "Robert answered: the KAUST one"
                   "--from" "robert" "--apply"))))

;;;; Rendering

(ert-deftest cube-decisions-render-from-fixture ()
  (cube-test-with-decisions
    (with-current-buffer (cube-decisions--render)
      (let ((text (buffer-string)))
        (should (string-match-p "^Decisions (4)" text))
        (should (string-match-p "Permissions (1)" text))
        (should (string-match-p "Questions (1)" text))
        (should (string-match-p "Approvals (1)" text))
        (should (string-match-p "Other (1)" text))
        (should (string-match-p "Answered (2)" text))
        (should (string-match-p "\\[Yes\\] \\[No\\]" text))
        (should (string-match-p "\\[Approve\\] \\[Reject\\]" text))
        (should (string-match-p "\\[Accept\\] \\[Reject\\] \\[Answer\\]" text))
        (should (string-match-p "Which mailbox should I read" text))
        (should (string-match-p "Use the 2026 release" text)))
      ;; the buttons are real buttons and answer their own decision
      (goto-char (point-min))
      (search-forward "[Yes]")
      (let ((button (button-at (1- (point)))))
        (should button)
        (should (equal (button-get button 'cube-decision-id) "cube-401"))
        (should (equal (button-get button 'cube-decision-choice) "yes"))
        (should (eq (lookup-key (button-get button 'keymap) [mouse-1]) #'push-button))
        (should (eq (lookup-key (button-get button 'keymap) (kbd "RET")) #'push-button))))))

(ert-deftest cube-decisions-render-empty-and-error ()
  (let ((cube-decisions--items nil)
        (cube-decisions--answered nil)
        (cube-decisions--generated nil)
        (cube-decisions--error "decisions failed (7): boom"))
    (when (get-buffer cube-decisions-buffer) (kill-buffer cube-decisions-buffer))
    (with-current-buffer (cube-decisions--render)
      (should (string-match-p "^Decisions (0)" (buffer-string)))
      (should (string-match-p "decisions failed (7)" (buffer-string)))
      (should (string-match-p "nothing answered yet" (buffer-string))))
    (kill-buffer cube-decisions-buffer)))

;;;; Answering

(ert-deftest cube-decisions-yes-and-no-run-cube-decide ()
  (cube-test-with-local
    (cube-test-with-decisions
      (let ((out (cube-test-fake-out)))
        (let ((process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment)))
          (with-current-buffer (cube-decisions--render)
            (goto-char (point-min))
            (search-forward "run the IBEX benchmark")
            (cube-decisions-yes)
            (cube-test-wait-until (string-match-p "decide" (cube-test-recorded out)))
            (should (string-match-p
                     "^cube decide cube-401 --choice yes --apply --json$"
                     (cube-test-recorded out)))
            (goto-char (point-min))
            (search-forward "Use the new embedding model")
            (cube-decisions-no)
            (cube-test-wait-until
             (string-match-p "--choice reject" (cube-test-recorded out)))
            (should (string-match-p
                     "^cube decide cube-403 --choice reject --apply --json$"
                     (cube-test-recorded out)))))
        (delete-file out)))))

(ert-deftest cube-decisions-answer-opens-a-compose-buffer-that-submits-text ()
  (cube-test-with-local
    (cube-test-with-decisions
      (let ((out (cube-test-fake-out "cube-answer-out")))
        (let ((process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment)))
          (save-window-excursion
            (with-current-buffer (cube-decisions--render)
              (goto-char (point-min))
              (search-forward "which mailbox")
              (cube-decisions-answer))
            (with-current-buffer "*cube-answer: cube-402*"
              (should (derived-mode-p 'cube-decision-compose-mode))
              (should (string-match-p "asks: Which mailbox" (buffer-string)))
              (should (string-match-p "C-c C-c submits" header-line-format))
              (goto-char (point-max))
              (insert "the KAUST one")
              (should (equal (cube-decision-compose-text) "the KAUST one"))
              (cube-decision-compose-finish))
            (cube-test-wait-until (string-match-p "decide" (cube-test-recorded out)))
            (should (string-match-p
                     "^cube decide cube-402 --text the KAUST one --apply --json$"
                     (cube-test-recorded out)))))
        (delete-file out)))))

(ert-deftest cube-decisions-an-approval-still-goes-through-the-review-queue ()
  (cube-test-with-decisions
    (let ((approved nil) (rejected nil))
      (cl-letf (((symbol-function 'cube-review-approve-id) (lambda (id) (setq approved id)))
                ((symbol-function 'cube-review-reject-id) (lambda (id) (setq rejected id))))
        (let ((item (cube-test-decision "apr-20260904-085500-ab")))
          (cube-decisions-answer-item item "approve")
          (should (equal approved "apr-20260904-085500-ab"))
          (cube-decisions-answer-item item "reject")
          (should (equal rejected "apr-20260904-085500-ab")))))))

(ert-deftest cube-decisions-relay-payload-is-redispatched-on-the-named-host ()
  (cube-test-with-local
    (cube-test-with-decisions
      (let* ((out (cube-test-fake-out "cube-relay-out"))
             (process-environment (append (list (concat "CUBE_FAKE_OUT=" out)
                                                "CUBE_FAKE_RELAY=laptop")
                                          process-environment))
             (relayed nil))
        (cl-letf (((symbol-function 'cube--call-json-async-on)
                   (lambda (host args &rest _) (setq relayed (cons host args)))))
          (cube-decisions-answer-item (cube-test-decision "cube-402") nil "the KAUST one")
          (cube-test-wait-until relayed)
          ;; the answer was recorded on the backend host and delivered on the laptop
          (should (string-match-p "^cube decide cube-402 --text the KAUST one --apply --json$"
                                  (cube-test-recorded out)))
          (should (equal (car relayed) "laptop"))
          (should (equal (cdr relayed)
                         '("agent" "tell" "liaison" "Robert answered: the KAUST one"
                           "--from" "robert" "--apply"))))
        (delete-file out)))))

;;;; Dashboard and mode line

(ert-deftest cube-decisions-dashboard-section-shows-rows-and-the-total ()
  (cube-test-with-decisions
    (let ((cube-decisions-count 2))
      (let ((items (cube-dashboard--decision-items)))
        (should (= (length items) 2))
        (should (equal (mapcar (lambda (i) (plist-get i :type)) items) '(decision decision)))
        (should (equal (plist-get (car items) :id) "cube-401"))
        (should (string-match-p "\\[Yes\\] \\[No\\]" (plist-get (car items) :label)))))
    (let ((cube-dashboard--data nil)
          (cube-dashboard--pending nil)
          (cube-dashboard-auto-refresh nil))
      (when (get-buffer "*cube*") (kill-buffer "*cube*"))
      (unwind-protect
          (progn
            (setf (alist-get 'decisions cube-dashboard--data)
                  (list :json (cube-test-read-fixture "decisions.json")
                        :time (current-time) :error nil))
            (with-current-buffer (get-buffer-create "*cube*")
              (cube-dashboard-mode)
              (cube-dashboard--render)
              (let ((text (buffer-string)))
                (should (string-match-p "Decisions (4)" text))
                (should (string-match-p "\\[Yes\\] \\[No\\]" text))
                (should (string-match-p "agent:ontology" text)))))
        (when (get-buffer "*cube*") (kill-buffer "*cube*"))))))

(ert-deftest cube-decisions-mode-line-counts-them ()
  (cube-test-with-clean-rolodex
    (cube-test-with-decisions
      (should (= (cube-decisions-pending-count) 4))
      (should (string-match-p "?4" (cube-mode-line-string)))
      (let ((cube-decisions--items nil))
        (should (equal (cube-mode-line-string) ""))))))

(ert-deftest cube-decisions-set-json-updates-the-cache-and-runs-the-hook ()
  (let ((cube-decisions--items nil)
        (cube-decisions--answered nil)
        (ran 0))
    (let ((cube-decisions-update-hook (list (lambda () (setq ran (1+ ran))))))
      (cube-decisions-set-json (cube-test-read-fixture "decisions.json")))
    (should (= ran 1))
    (should (= (length cube-decisions--items) 4))
    (should (= (length cube-decisions--answered) 2))))

(ert-deftest cube-decisions-fetch-with-fake ()
  (cube-test-with-local
    (let ((cube-decisions--items nil)
          (cube-decisions-update-hook nil))
      (cube-decisions--fetch)
      (cube-test-wait-until cube-decisions--items)
      (should (= (length cube-decisions--items) 4))
      (should (equal (cube-decisions--id (car cube-decisions--items)) "cube-401")))))

(ert-deftest cube-decisions-policy-preview-tags-the-row ()
  "A decision the policy would answer says so, dimly, and `P' runs the gate."
  (let ((auto (cube-test-decision "cube-401"))
        (manual (cube-test-decision "cube-402")))
    (should (cube-decisions--policy auto))
    (should-not (cube-decisions--policy manual))
    (should (equal (substring-no-properties (cube-decisions--policy-tag auto))
                   "auto: yes at next tick"))
    (should-not (cube-decisions--policy-tag manual)))
  (cube-test-with-decisions
    (with-current-buffer (cube-decisions--render)
      (should (string-match-p "auto: yes at next tick" (buffer-string)))))
  (should (string-match-p "cube-401 +yes +compute inside"
                          (cube-decisions--policy-plan-text
                           (cube-test-read-fixture "decisions-policy.json")))))

(ert-deftest cube-decisions-apply-policy-runs-the-dry-run-first ()
  (cube-test-with-local
    (cube-test-with-decisions
      (let ((out (cube-test-fake-out "cube-policy-out")))
        (let ((process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment)))
          (cl-letf (((symbol-function 'y-or-n-p) (lambda (&rest _) nil)))
            (cube-decisions-apply-policy)
            (cube-test-wait-until (string-match-p "apply-policy" (cube-test-recorded out)))
            ;; the dry run happened; nothing was applied because the gate said no
            (should (string-match-p
                     "^cube decisions apply-policy --dry-run --json$"
                     (cube-test-recorded out)))
            (should-not (string-match-p "--apply" (cube-test-recorded out)))))
        (delete-file out)))))

(ert-deftest cube-decisions-keys ()
  (dolist (pair '(("y" . cube-decisions-yes) ("n" . cube-decisions-no)
                  ("a" . cube-decisions-answer) ("P" . cube-decisions-apply-policy)
                  ("RET" . cube-decisions-visit)
                  ("o" . cube-decisions-open-evidence) ("g" . cube-decisions-refresh)
                  ("q" . quit-window)))
    (should (eq (lookup-key cube-decisions-mode-map (kbd (car pair))) (cdr pair))))
  (should (eq (lookup-key cube-decision-compose-mode-map (kbd "C-c C-c"))
              #'cube-decision-compose-finish))
  (should (eq (lookup-key cube-decision-compose-mode-map (kbd "C-c C-k"))
              #'cube-decision-compose-abort)))

(provide 'cube-decisions-test)
;;; cube-decisions-test.el ends here


(ert-deftest cube-decisions-rows-show-the-request-text-and-duplicates ()
  "Robert sees what he is deciding: the body under the row, capped, and duplicates."
  (let* ((item (cube-test-decision "cube-401"))
         (cube-decisions-body-lines 2))
    (should (equal (cube-decisions--body-lines item)
                   '("Rationale: the benchmark needs IBEX."
                     "Resources requested: 4 node hours.")))
    (let ((cube-decisions-body-lines 1))
      (should (equal (cube-decisions--body-lines item)
                     '("Rationale: the benchmark needs IBEX."
                       "[more: RET opens the full request]"))))
    (should (string-match-p "same request 1 more time (cube-999)"
                            (cube-decisions--duplicates-text item)))
    (cube-test-with-decisions
      (with-current-buffer (cube-decisions--render)
        (should (string-match-p "Rationale: the benchmark needs IBEX" (buffer-string)))
        (should (string-match-p "one answer closes all" (buffer-string)))))
    (let ((cube-decisions-body-lines 0))
      (should (equal (cube-decisions--body-lines item) '("[more: RET opens the full request]"))))))
