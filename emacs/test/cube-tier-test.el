;;; cube-tier-test.el --- Tests for cube-tier  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(ert-deftest cube-tier-table-renders-contract-payload ()
  (let ((text (cube-tier--tier-table-text (cube-test-read-fixture "tier.json"))))
    (should (string-match-p "^Cube tiers" text))
    (should (string-match-p "plan +\\*claude +fable +preferred" text))
    (should (string-match-p "codex +gpt-5-codex +exhausted +until 21:00" text))
    (should (string-match-p "local +local +- +backoff +until 10:00" text))))

(ert-deftest cube-tier-write-args-are-explicitly-gated ()
  (should (equal (cube-tier--disable-args "codex" "5h" "maintenance")
                 '("tier" "disable" "codex" "--dry-run" "--for" "5h"
                   "--reason" "maintenance")))
  (should (equal (cube-tier--enable-args "codex" "--apply")
                 '("tier" "enable" "codex" "--apply")))
  (should (equal (cube-tier--prefer-args "plan" "claude" "--apply")
                 '("tier" "prefer" "plan" "claude" "--apply")))
  (should (equal (cube-tier--reset-args) '("tier" "reset" "--dry-run"))))

(ert-deftest cube-tier-fetches-and-applies-through-fake ()
  (cube-test-with-local
    (let* ((cube-tier--json nil)
           (out (cube-test-temp-file "cube-tier-out"))
           (process-environment (cons (concat "CUBE_FAKE_OUT=" out) process-environment))
           (json nil))
      (unwind-protect
          (progn
            (cube-tier--fetch (lambda (value) (setq json value)))
            (cube-test-wait-until json)
            (should (cube-get json 'tiers))
            (let ((cube-tier-confirm nil))
              (cube-tier--write (cube-tier--enable-args "codex"))
              (cube-test-wait-until
               (with-temp-buffer
                 (insert-file-contents out)
                 (string-match-p "cube tier enable codex --apply --json" (buffer-string))))
              (with-temp-buffer
                (insert-file-contents out)
                (should (string-match-p "cube tier enable codex --dry-run --json" (buffer-string)))))
        (when (get-buffer "*cube-tier*") (kill-buffer "*cube-tier*"))
        (when (get-buffer "*cube-tier-plan*") (kill-buffer "*cube-tier-plan*"))
        (delete-file out))))))

(ert-deftest cube-tier-menu-is-transient-prefix ()
  (should (commandp #'cube-tier-menu))
  (should (get 'cube-tier-menu 'transient--prefix))
  (let ((layout (prin1-to-string (get 'cube-tier-menu 'transient--layout))))
    (dolist (command '(cube-tier-disable cube-tier-enable cube-tier-prefer cube-tier-reset))
      (should (string-match-p (symbol-name command) layout)))))

(provide 'cube-tier-test)
;;; cube-tier-test.el ends here
