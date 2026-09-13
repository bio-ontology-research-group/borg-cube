;;; cube-review-test.el --- Tests for cube-review  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(defun cube-test-approvals ()
  "Return the approvals of the fixture."
  (cube-get (cube-test-read-fixture "approvals.json") 'approvals))

(defmacro cube-test-with-review (&rest body)
  "Run BODY with isolated review state and no *cube-review* buffer."
  (declare (indent 0))
  `(let ((cube-review--approvals nil) (cube-review--bodies nil)
         (cube-review--details nil) (cube-review--generated nil)
         (cube-review--error nil) (cube-review-confirm nil)
         ;; never reach a real Gnus from the tests, even if a stub fails
         (cube-review-gnus-server "cube-test-no-such-server")
         (cube-review-local-draft-directory (make-temp-file "cube-drafts" t)))
     (when (get-buffer "*cube-review*") (kill-buffer "*cube-review*"))
     (unwind-protect
         (progn ,@body)
       (when (get-buffer "*cube-review*") (kill-buffer "*cube-review*"))
       (ignore-errors (delete-directory cube-review-local-draft-directory t)))))

(ert-deftest cube-review-heading ()
  (let* ((now (encode-time (iso8601-parse "2026-09-02T09:15:00+03:00")))
         (email (cube-review--heading (car (cube-test-approvals)) now))
         (git (cube-review--heading (cadr (cube-test-approvals)) now)))
    (should (string-match-p "\\`cube-301 +outbound +email +-> alex-example +Milestone reminder" email))
    (should (string-match-p "20m\\'" email))
    (should (string-match-p "\\`cube-302 +write +git +- +Push meeting note" git))
    (should (string-match-p "14m\\'" git))))

(ert-deftest cube-review-body-mode-and-kind ()
  (let ((email (car (cube-test-approvals))) (git (cadr (cube-test-approvals))))
    (should (cube-review--email-p email))
    (should-not (cube-review--email-p git))
    (should (eq (cube-review--body-mode email) 'markdown-mode))
    (should (eq (cube-review--body-mode git) 'diff-mode))
    (should (equal (cube-review--body-file email) "state/drafts/cube-301.md"))
    (should (equal (cube-review--body-file '((body_file . "x.md") (draft_file . "y.md"))) "x.md"))
    (should (eq (cube-review--body-mode '((channel . "mattermost"))) 'markdown-mode))))

(ert-deftest cube-review-fontify-keeps-text ()
  (let ((diff "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"))
    (should (equal (substring-no-properties (cube-review--fontify diff 'diff-mode)) diff))
    (should (equal (substring-no-properties (cube-review--fontify "# T\n\ntext" 'markdown-mode))
                   "# T\n\ntext"))
    (should (equal (substring-no-properties (cube-review--fontify "x" 'no-such-mode)) "x"))))

(ert-deftest cube-review-email-form ()
  (let* ((show (cube-test-read-fixture "approval-show.json"))
         (form (cube-review--email-form show "~/.cache/cube/drafts/cube-301.md")))
    (should (equal (car form) 'claude-email-compose))
    (should (equal (nth 1 form) "alex.example@example.org"))
    (should (equal (nth 2 form) "Proposal defense: 74 days to go"))
    (should (equal (nth 3 form) (expand-file-name "~/.cache/cube/drafts/cube-301.md")))
    (should (= (length form) 4))
    ;; without address and subject the slug and the summary stand in
    (let ((plain (cube-review--email-form (car (cube-test-approvals)) "/tmp/x.md")))
      (should (equal (nth 1 plain) "alex-example"))
      (should (equal (nth 2 plain) "Milestone reminder: proposal defense in 74 days")))
    ;; details from `approvals show' win over the queue entry
    (let ((merged (cube-review--merged (car (cube-test-approvals)) show)))
      (should (equal (cube-get merged 'to) "alex.example@example.org"))
      (should (equal (cube-get merged 'kind) "outbound")))))

(ert-deftest cube-review-args ()
  (should (equal (cube-review--approve-args "cube-301") '("approve" "cube-301")))
  (should (equal (cube-review--approve-args "cube-301" "state/drafts/cube-301.edited.md")
                 '("approve" "cube-301" "--body-file" "state/drafts/cube-301.edited.md")))
  (should (equal (cube-review--reject-args "cube-302" "wrong file")
                 '("reject" "cube-302" "--reason" "wrong file")))
  (should (equal (cube-review--reject-args "cube-302" "") '("reject" "cube-302")))
  (should (equal (cube-review--edited-body-path "cube-301") "state/drafts/cube-301.edited.md"))
  (should (equal (cube-review--result-message
                  '((ok . t) (id . "cube-301") (action . "approve") (result . "draft_opened")
                    (message . "handed to Gnus")))
                 "cube: approve cube-301: draft_opened (handed to Gnus)")))

(ert-deftest cube-review-render-from-fixture ()
  (cube-test-with-review
    (setq cube-review--approvals (cube-test-approvals)
          cube-review--generated "2026-09-02T09:15:00+03:00")
    (push (cons "cube-302" "--- a/gus.org\n+++ b/gus.org\n@@ -1 +1,2 @@\n+** 2 September 2026\n")
          cube-review--bodies)
    (with-current-buffer (cube-review--render)
      (should (derived-mode-p 'cube-review-mode))
      (let ((text (buffer-string)))
        (should (string-match-p "^Approvals (2), as of" text))
        (should (string-match-p "^cube-301 +outbound" text))
        (should (string-match-p "(press RET to load the body)" text))
        (should (string-match-p "bead cube-103, run r-20260902-0850-adv" text))
        (should (string-match-p "\\+\\*\\* 2 September 2026" text)))
      (goto-char (point-min))
      (re-search-forward "^cube-302")
      (let ((approval (cube-review--current)))
        (should (equal (cube-get approval 'id) "cube-302"))
        (should (equal (cube-get approval 'channel) "git")))
      (should (cube-review--goto "cube-301"))
      (should (equal (cube-get (cube-review--current) 'id) "cube-301"))
      (should-not (cube-review--goto "cube-999")))))

(ert-deftest cube-review-render-empty-and-error ()
  (cube-test-with-review
    (setq cube-review--error "approvals failed (7): fake failure")
    (with-current-buffer (cube-review--render)
      (should (string-match-p "^Approvals (0)  \\[approvals failed" (buffer-string)))
      (should (string-match-p "nothing waiting" (buffer-string)))
      (should-error (cube-review--current) :type 'user-error))))

(ert-deftest cube-review-fetch-body-with-fake ()
  (cube-test-with-local
    (cube-test-with-review
      (let ((body 'pending))
        (cube-review--fetch-body (car (cube-test-approvals)) (lambda (b) (setq body b)))
        (cube-test-wait-until (not (eq body 'pending)))
        (should (string-prefix-p "Dear Alex," body))
        (should (equal (cdr (assoc "cube-301" cube-review--bodies)) body))
        (should (equal (cube-get (cdr (assoc "cube-301" cube-review--details)) 'to)
                       "alex.example@example.org"))))))

(ert-deftest cube-review-fetch-body-falls-back-to-host-file ()
  (cube-test-with-local
    (cube-test-with-review
      (let* ((cube-program "false")
             (file (cube-test-temp-file "cube-draft" "draft text" ".md"))
             (body 'pending))
        (cube-review--fetch-body (list (cons 'id "x-1") (cons 'draft_file file))
                                 (lambda (b) (setq body b)))
        (cube-test-wait-until (not (eq body 'pending)))
        (should (equal body "draft text"))
        (delete-file file)
        (setq body 'pending)
        (cube-review--fetch-body (list (cons 'id "x-2") (cons 'draft_file "/nonexistent/f.md"))
                                 (lambda (b) (setq body b)))
        (cube-test-wait-until (not (eq body 'pending)))
        (should (equal body "(body unavailable)"))))))

(ert-deftest cube-review-queue-with-fake ()
  (cube-test-with-local
    (cube-test-with-review
      (save-window-excursion
        (cube-review-queue)
        (cube-test-wait-until (= (length cube-review--approvals) 2))
        (with-current-buffer "*cube-review*"
          (cube-test-wait-until (string-match-p "cube-302" (buffer-string)))
          (should (string-match-p "^Approvals (2)" (buffer-string))))))))

(ert-deftest cube-review-approve-write-runs-cube-approve ()
  (cube-test-with-local
    (cube-test-with-review
      (let* ((out (cube-test-temp-file "cube-approve-out"))
             (process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment)))
        (cube-review-approve (cadr (cube-test-approvals)))
        (cube-test-wait-until (> (file-attribute-size (file-attributes out)) 0))
        (should (string-match-p "^cube approve cube-302 --json$"
                                (with-temp-buffer (insert-file-contents out) (buffer-string))))
        (delete-file out)))))

(ert-deftest cube-review-reject-runs-cube-reject ()
  (cube-test-with-local
    (cube-test-with-review
      (let* ((out (cube-test-temp-file "cube-reject-out"))
             (process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment)))
        (cube-review-reject (cadr (cube-test-approvals)) "not now")
        (cube-test-wait-until (> (file-attribute-size (file-attributes out)) 0))
        (should (string-match-p "^cube reject cube-302 --reason not now --json$"
                                (with-temp-buffer (insert-file-contents out) (buffer-string))))
        (delete-file out)))))

(ert-deftest cube-review-approve-email-hands-draft-to-gnus ()
  (cube-test-with-local
    (cube-test-with-review
      (let* ((out (cube-test-temp-file "cube-email-out"))
             (process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment))
             (evaluated nil))
        (cl-letf (((symbol-function 'server-eval-at)
                   (lambda (server form) (setq evaluated (list server form)) "*claude-mail-1*")))
          (cube-review-approve (car (cube-test-approvals)))
          (cube-test-wait-until (> (file-attribute-size (file-attributes out)) 0))
          ;; the Gnus side got a compose form, never a send
          (should (equal (car evaluated) "cube-test-no-such-server"))
          (let ((form (cadr evaluated)))
            (should (eq (car form) 'claude-email-compose))
            (should (equal (nth 1 form) "alex.example@example.org"))
            (should (equal (nth 2 form) "Proposal defense: 74 days to go"))
            (should (file-readable-p (nth 3 form)))
            (should (string-prefix-p "Dear Alex,"
                                     (with-temp-buffer (insert-file-contents (nth 3 form))
                                                       (buffer-string)))))
          ;; and the approval was recorded through the single trigger
          (should (string-match-p "^cube approve cube-301 --json$"
                                  (with-temp-buffer (insert-file-contents out) (buffer-string)))))
        (delete-file out)))))

(ert-deftest cube-review-approve-email-aborts-without-gnus ()
  (cube-test-with-local
    (cube-test-with-review
      (let* ((out (cube-test-temp-file "cube-email-fail-out"))
             (process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment))
             (failed nil))
        (cl-letf (((symbol-function 'server-eval-at)
                   (lambda (&rest _) (error "No such server: gnus"))))
          (cube-review--fetch-body (car (cube-test-approvals)) #'ignore)
          (cube-test-wait-until (assoc "cube-301" cube-review--bodies))
          (condition-case err
              (cube-review-approve (car (cube-test-approvals)))
            (user-error (setq failed (error-message-string err))))
          (should (string-match-p "Gnus server .* unreachable" failed))
          (accept-process-output nil 0.3)
          (should-not (string-match-p "cube approve"
                                      (with-temp-buffer (insert-file-contents out) (buffer-string)))))
        (delete-file out)))))

(ert-deftest cube-review-edit-finish-writes-body-file ()
  (cube-test-with-local
    (cube-test-with-review
      (let* ((out (cube-test-temp-file "cube-edit-out"))
             (root (make-temp-file "cube-root" t))
             (cube-root root)
             (process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment))
             (approval (cadr (cube-test-approvals))))
        (unwind-protect
            (with-current-buffer (get-buffer-create "*cube-review-edit: cube-302*")
              (erase-buffer)
              (insert "edited diff\n")
              (setq cube-review-edit--approval approval)
              (cube-review-edit-mode 1)
              (save-window-excursion
                (pop-to-buffer (current-buffer))
                (cube-review-edit-finish))
              (cube-test-wait-until (> (file-attribute-size (file-attributes out)) 0))
              (should (equal (with-temp-buffer
                               (insert-file-contents
                                (expand-file-name "state/drafts/cube-302.edited.md" root))
                               (buffer-string))
                             "edited diff\n"))
              (should (string-match-p
                       "^cube approve cube-302 --body-file state/drafts/cube-302.edited.md --json$"
                       (with-temp-buffer (insert-file-contents out) (buffer-string)))))
          (when (get-buffer "*cube-review-edit: cube-302*")
            (kill-buffer "*cube-review-edit: cube-302*"))
          (delete-directory root t)
          (delete-file out))))))

(ert-deftest cube-review-keys ()
  (dolist (pair '(("a" . cube-review-approve) ("x" . cube-review-reject) ("r" . cube-review-reject)
                  ("e" . cube-review-edit) ("RET" . cube-review-show-body)
                  ("j" . cube-review-jump-session) ("o" . cube-review-open-target)
                  ("g" . cube-review-refresh) ("q" . quit-window)
                  ("n" . magit-section-forward) ("p" . magit-section-backward)))
    (should (eq (lookup-key cube-review-mode-map (kbd (car pair))) (cdr pair))))
  (should (eq (lookup-key cube-review-edit-mode-map (kbd "C-c C-c")) #'cube-review-edit-finish)))

(defconst cube-test-forbidden-commands
  '("hermes send" "gog gmail send" "curl -X POST" "claude-email-send-buffer"
    "message-send-and-exit" "message-send" "smtpmail-send" "sendmail" "mattermost.*post")
  "Command fragments that must not appear in the cockpit sources.")

(ert-deftest cube-review-only-outbound-trigger-is-cube-approve ()
  "No source file sends anything itself; only cube-review.el calls `cube approve'."
  (let* ((dir (expand-file-name ".." cube-test-dir))
         (sources (directory-files dir t "\\`\\(cube-[a-z]+\\|borg-cube\\)\\.el\\'"))
         (approvers nil))
    (should (>= (length sources) 9))
    (dolist (file sources)
      (with-temp-buffer
        (insert-file-contents file)
        (dolist (forbidden cube-test-forbidden-commands)
          (goto-char (point-min))
          (should-not (and (re-search-forward forbidden nil t)
                           (format "%s contains %S" (file-name-nondirectory file) forbidden))))
        (goto-char (point-min))
        (when (re-search-forward "\"approve\"" nil t)
          (push (file-name-nondirectory file) approvers))))
    (should (equal approvers '("cube-review.el")))))

(provide 'cube-review-test)
;;; cube-review-test.el ends here
