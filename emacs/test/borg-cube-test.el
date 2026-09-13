;;; borg-cube-test.el --- Tests for the entry point  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(defconst cube-test-expected-keys
  '(("d" . cube-dashboard) ("!" . cube-attention)
    ("1" . cube-attention-1) ("2" . cube-attention-2)
    ("3" . cube-attention-3) ("n" . cube-rolodex-next)
    ("p" . cube-roster) ("a" . cube-beads-assign) ("o" . cube-org-edit)
    ("j" . cube-rolodex-jump) ("l" . cube-fleet-list)
    ("b" . cube-rolodex-toggle) ("c" . cube-rolodex-new-claude)
    ("x" . cube-rolodex-new-codex) ("h" . cube-rolodex-new-hermes)
    ("$" . cube-rolodex-new-shell) ("r" . cube-run-role) ("s" . cube-student-session)
    ("S" . cube-student-dossier) ("m" . cube-org-meeting-note)
    ("M" . cube-org-pull-notes) ("P p" . cube-papers)
    ("P n" . cube-pipeline-new) ("P l" . cube-pipeline-list)
    ("P s" . cube-pipeline-show) ("P a" . cube-pipeline-advance)
    ("P r" . cube-pipeline-rehearse) ("w" . cube-beads-ready)
    ("W" . cube-beads-create) ("v" . cube-review-queue) ("k" . cube-rolodex-kill)
    ("R" . cube-rolodex-restart) ("y" . cube-send) ("g" . cube-refresh)
    ("B" . cube-brief) ("H" . cube-doctor) ("A" . cube-org-papers-sync)
    ("D" . cube-decisions)
    ("i" . cube-beads-from-heading) ("," . cube-ask-coordinator)
    ("T" . cube-tier-menu) ("C" . cube-cockpit)
    ("?" . cube-menu))
  "Keymap from the plan.")

(ert-deftest borg-cube-keymap-complete ()
  (dolist (pair cube-test-expected-keys)
    (let ((cmd (lookup-key cube-command-map (kbd (car pair)))))
      (should (eq cmd (cdr pair)))
      (should (commandp cmd)))))

(ert-deftest borg-cube-prefix-installed-by-mode ()
  (let ((cube-prefix-key "C-c b")
        (cube-refresh-interval nil))
    (cube--install-prefix)
    (should (eq (lookup-key cube-mode-map (kbd "C-c b")) cube-command-map))
    (should (eq (lookup-key cube-mode-map (kbd "C-c b n")) #'cube-rolodex-next))
    ;; the user's own C-c bindings are untouched
    (should-not (lookup-key cube-mode-map (kbd "C-c l")))))

(ert-deftest borg-cube-repeat-map ()
  (should (eq (get 'cube-rolodex-next 'repeat-map) 'cube-repeat-map))
  (should (eq (lookup-key cube-repeat-map (kbd "n")) #'cube-rolodex-next))
  (should (eq (lookup-key cube-repeat-map (kbd "p")) #'cube-rolodex-prev))
  (should (eq (lookup-key cube-repeat-map (kbd "!")) #'cube-attention)))

(ert-deftest borg-cube-menu-is-transient-prefix ()
  (should (fboundp 'cube-menu))
  (should (commandp 'cube-menu))
  (should (get 'cube-menu 'transient--prefix))
  (should (get 'cube-menu 'transient--layout))
  ;; make sure we run against the intended transient (0.4 API works on both)
  (should (fboundp 'transient-define-prefix)))

(ert-deftest borg-cube-former-stubs-are-real-commands ()
  "The v0 stubs are gone: every command is defined by its module."
  (dolist (pair '((cube-dashboard . cube-dashboard) (cube-student-dossier . cube-org)
                  (cube-org-meeting-note . cube-org) (cube-org-pull-notes . cube-org)
                  (cube-papers . cube-org) (cube-beads-ready . cube-beads)
                  (cube-beads-create . cube-beads) (cube-review-queue . cube-review)
                  (cube-brief . cube-dashboard) (cube-attention . cube-dashboard)
                  (cube-attention-nth . cube-dashboard)))
    (should (commandp (car pair)))
    (should (featurep (cdr pair))))
  (should-not (fboundp 'cube--define-stub)))

(ert-deftest borg-cube-mode-line-counts-cached-attention ()
  (cube-test-with-clean-rolodex
    (cube-attention-set-items (cube-test-read-fixture "attention.json"))
    (should (= (length cube--attention-items) 3))
    (should (equal (substring-no-properties (cube-mode-line-string)) "⚠3 ●0"))
    (cube-attention-set-items nil)
    (should (equal (cube-mode-line-string) ""))))

(ert-deftest borg-cube-mode-line-string ()
  (cube-test-with-clean-rolodex
    (should (equal (cube-mode-line-string) ""))
    (let ((b1 (generate-new-buffer " *cube-ml-1*"))
          (b2 (generate-new-buffer " *cube-ml-2*")))
      (unwind-protect
          (progn
            (let ((s1 (cube-session-create :name "a" :kind 'claude :state 'attention :buffer b1))
                  (s2 (cube-session-create :name "b" :kind 'codex :state 'running :buffer b2)))
              (cube-rolodex--register s1)
              (cube-rolodex--register s2))
            (should (equal (substring-no-properties (cube-mode-line-string)) "⚠1 ●1"))
            (let ((cube--attention-items '(1 2)))
              (should (equal (substring-no-properties (cube-mode-line-string)) "⚠3 ●1"))))
        (kill-buffer b1)
        (kill-buffer b2)))))

(ert-deftest borg-cube-mode-line-banner-leads ()
  (cube-test-with-clean-rolodex
    (cube-status-set-json (cube-test-read-fixture "status.json"))
    (should (string-prefix-p "P0 " (substring-no-properties (cube-mode-line-string))))))

(ert-deftest borg-cube-mode-toggles-cleanly ()
  (let ((cube-refresh-interval nil)
        (was cube-mode))
    (unwind-protect
        (progn
          (cube-mode 1)
          (should (member cube--mode-line-construct global-mode-string))
          (cube-mode -1)
          (should-not (member cube--mode-line-construct global-mode-string)))
      (when was (cube-mode 1)))))

(ert-deftest borg-cube-laptop-worker-runs-locally ()
  (let ((call nil))
    (cl-letf (((symbol-function 'cube--call-json-async-on)
               (lambda (host args callback &optional _error)
                 (setq call (list host args))
                 (funcall callback '((result . "finished"))))))
      (cube-laptop-worker-run-once))
    (should (equal call '(nil ("worker" "--once" "--host" "laptop"))))))

(provide 'borg-cube-test)
;;; borg-cube-test.el ends here
