;;; cube-rolodex-test.el --- Tests for cube-rolodex  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(defun cube-test-session (name state &optional pinned kind)
  "Make a session NAME in STATE, optionally PINNED, of KIND."
  (cube-session-create :name name :kind (or kind 'claude) :state state :pinned pinned))

(ert-deftest cube-rolodex-buffer-naming ()
  (should (equal (cube-rolodex-buffer-name 'claude "alex-plan") "*cube:claude:alex-plan*"))
  (should (equal (cube-rolodex-buffer-name "run" "programmer-cube-142")
                 "*cube:run:programmer-cube-142*"))
  (should (equal (cube-rolodex--tmux-name "alex-plan") "cube/alex-plan")))

(ert-deftest cube-rolodex-command-local-claude ()
  (cube-test-with-local
    (let ((cube-claude-tui 'inherit))
      (should (equal (cube-rolodex--command-for 'claude '(:name "plan"))
                     (list "env" "CUBE_SESSION=plan" "claude" "--settings"
                           (expand-file-name "emacs/claude-hooks.json" cube-root)))))
    (let ((cube-claude-tui 'inline))
      (should (equal (seq-drop (cube-rolodex--command-for 'claude '(:name "plan" :resume "abc"))
                               5)
                     '("--settings" "{\"tui\":\"inline\"}" "--resume" "abc"))))
    (let ((cube-claude-tui 'fullscreen))
      (should (member "{\"tui\":\"fullscreen\"}"
                      (cube-rolodex--command-for 'claude '(:name "plan")))))))

(ert-deftest cube-rolodex-command-local-other-kinds ()
  (cube-test-with-local
    (should (equal (cube-rolodex--command-for 'codex '(:name "fix"))
                   '("env" "CUBE_SESSION=fix" "codex")))
    (should (equal (cube-rolodex--command-for 'codex '(:name "fix" :resume "t1"))
                   '("env" "CUBE_SESSION=fix" "codex" "resume" "t1")))
    (should (equal (cube-rolodex--command-for 'hermes '(:name "adv" :profile "advisor"))
                   '("env" "CUBE_SESSION=adv" "hermes" "-p" "advisor" "chat")))
    (should (equal (cube-rolodex--command-for 'hermes '(:name "adv"))
                   '("env" "CUBE_SESSION=adv" "hermes" "-p" "advisor" "chat")))
    (let ((process-environment (cons "SHELL=/bin/zsh" process-environment)))
      (should (equal (cube-rolodex--command-for 'shell '(:name "sh1"))
                     '("env" "CUBE_SESSION=sh1" "/bin/zsh" "-l"))))
    (should (equal (cube-rolodex--command-for 'run '(:name "prog" :role "programmer" :bead "cube-142"))
                   '("env" "CUBE_SESSION=prog" "cube" "run" "programmer" "--bead" "cube-142" "--attach")))
    (should (equal (cube-rolodex--command-for 'run '(:name "prog" :role "programmer"))
                   '("env" "CUBE_SESSION=prog" "cube" "run" "programmer" "--attach")))
    (should-error (cube-rolodex--command-for 'run '(:name "prog")))
    (should-error (cube-rolodex--command-for 'attach '(:name "x")))
    (should-error (cube-rolodex--command-for 'bogus '(:name "x")))))

(ert-deftest cube-rolodex-command-remote-tmux-wrapping ()
  (cube-test-with-remote
    (let* ((cube-claude-tui 'inline)
           (cube-ssh-multiplex nil)
           (argv (cube-rolodex--command-for 'claude '(:name "alex-plan" :resume "8f1c")))
           (remote (split-string-shell-command (car (last argv))))
           (inner (split-string-shell-command (car (last remote)))))
      (should (equal (butlast argv)
                     '("ssh" "-t" "-o" "ConnectTimeout=5" "-o" "BatchMode=yes" "ws" "--")))
      (should (equal (butlast remote)
                     '("tmux" "new-session" "-A" "-s" "cube/alex-plan")))
      (should (equal inner
                     '("env" "CUBE_SESSION=alex-plan" "claude"
                       "--settings" "~/Public/software/borg-cube/emacs/claude-hooks.json"
                       "--settings" "{\"tui\":\"inline\"}" "--resume" "8f1c")))
      ;; The tilde must reach tmux's shell unquoted so it expands there.
      (should (string-match-p "--settings ~/Public" (car (last remote))))
      (should-not (string-match-p "\\\\~" (car (last remote)))))))

(ert-deftest cube-rolodex-command-remote-shell-and-attach ()
  (cube-test-with-remote
    (let* ((argv (cube-rolodex--command-for 'shell '(:name "ibex")))
           (remote (split-string-shell-command (car (last argv))))
           (inner (split-string-shell-command (car (last remote)))))
      (should (equal (seq-take inner 4) '("env" "CUBE_SESSION=ibex" "sh" "-c")))
      (should (string-match-p "SHELL" (nth 4 inner))))
    (let* ((argv (cube-rolodex--command-for 'attach '(:name "old")))
           (remote (split-string-shell-command (car (last argv)))))
      (should (equal remote '("tmux" "new-session" "-A" "-s" "cube/old"))))
    (let* ((argv (cube-rolodex--command-for 'run '(:name "r" :role "auditor")))
           (remote (split-string-shell-command (car (last argv))))
           (inner (split-string-shell-command (car (last remote)))))
      (should (equal inner '("env" "CUBE_SESSION=r" "cube" "run" "auditor" "--attach"))))))

(ert-deftest cube-rolodex-ordering ()
  (let* ((a (cube-test-session "a" 'running))
         (b (cube-test-session "b" 'idle))
         (c (cube-test-session "c" 'attention))
         (d (cube-test-session "d" 'running t))
         (e (cube-test-session "e" 'attention))
         (f (cube-test-session "f" 'idle t))
         (g (cube-test-session "g" 'exited))
         (h (cube-test-session "h" 'error))
         (input (list a b c d e f g h))
         (ordered (cube-rolodex--ordered input)))
    (should (equal (mapcar #'cube-session-name ordered)
                   '("c" "e" "h" "f" "b" "d" "a" "g")))
    ;; pure: input untouched
    (should (equal (mapcar #'cube-session-name input)
                   '("a" "b" "c" "d" "e" "f" "g" "h")))
    ;; stable among equals
    (let ((many (mapcar (lambda (n) (cube-test-session (number-to-string n) 'running))
                        (number-sequence 1 20))))
      (should (equal (cube-rolodex--ordered many) many)))))

(ert-deftest cube-rolodex-header-line ()
  (let* ((now (current-time))
         (s1 (cube-test-session "alex-plan" 'running nil 'claude))
         (s2 (cube-test-session "fix-tests" 'attention nil 'codex))
         (s3 (cube-test-session "adv" 'attention nil 'hermes))
         (s4 (cube-test-session "x" 'error nil 'shell))
         (s5 (cube-test-session "y" 'attention nil 'claude))
         (ordered (cube-rolodex--ordered (list s1 s2 s3 s4 s5)))
         (cube-attention-count 3))
    (setf (cube-session-last-activity s1) (time-convert (time-subtract now 120) 'list))
    (let ((line (cube-rolodex--header-line s1 ordered now)))
      (should (string-prefix-p "[5/5] claude:alex-plan ●running 2m" line))
      (should (string-match-p "⚠ codex:fix-tests" line))
      (should (string-match-p "⚠ hermes:adv" line))
      (should (string-match-p "⚠ shell:x" line))
      ;; only cube-attention-count others are listed
      (should-not (string-match-p "claude:y" line)))
    (setf (cube-session-reason s2) "needs approval")
    (let ((line (cube-rolodex--header-line s2 ordered now)))
      (should (string-prefix-p "[1/5] codex:fix-tests ⚠attention" line))
      (should (string-match-p "(needs approval)" line))
      (should-not (string-match-p "codex:fix-tests  " line)))))

(ert-deftest cube-rolodex-parse-tmux-list ()
  (should (equal (cube-rolodex--parse-tmux-list "cube/alex-plan\nmain\ncube/fix-tests\n")
                 '("alex-plan" "fix-tests")))
  (should (equal (cube-rolodex--parse-tmux-list "") nil)))

(ert-deftest cube-rolodex-guess-kind ()
  (should (eq (cube-rolodex--guess-kind "advisor/alex") 'claude))
  (should (eq (cube-rolodex--guess-kind "codex-2") 'codex))
  (should (null (cube-rolodex--guess-kind "alex-plan"))))

(ert-deftest cube-rolodex-registry-and-state ()
  (cube-test-with-clean-rolodex
    (let ((s (cube-rolodex--register (cube-test-session "one" 'running))))
      (should (eq (cube-rolodex-find "one") s))
      (cube-rolodex--register (cube-test-session "one" 'idle))
      (should (= (length cube-rolodex--sessions) 1))
      (should (eq (cube-session-state (cube-rolodex-find "one")) 'idle))
      (let* ((seen nil)
             (cube-rolodex-state-change-hook
             (list (lambda (session) (setq seen (cube-session-state session))))))
        (cube-rolodex-set-state (cube-rolodex-find "one") 'attention "why")
        (should (eq seen 'attention))
        (should (equal (cube-session-reason (cube-rolodex-find "one")) "why"))))))

(ert-deftest cube-rolodex-session-mode-keys ()
  (should (eq (lookup-key cube-session-mode-map [escape]) #'cube-session-send-escape))
  (should (eq (lookup-key cube-session-mode-map [backtab]) #'cube-session-send-backtab))
  (should (eq (lookup-key cube-session-mode-map (kbd "C-c C-o")) #'cube-session-open-context))
  (should-not (lookup-key cube-session-mode-map (kbd "C-c b"))))

(ert-deftest cube-rolodex-attention-sessions ()
  (cube-test-with-clean-rolodex
    (let ((buf (generate-new-buffer " *cube-test*")))
      (unwind-protect
          (progn
            (cube-rolodex--register (cube-test-session "quiet" 'running))
            (let ((loud (cube-test-session "loud" 'attention)))
              (setf (cube-session-buffer loud) buf)
              (cube-rolodex--register loud))
            ;; only sessions with live buffers count
            (should (equal (mapcar #'cube-session-name (cube-rolodex-attention-sessions))
                           '("loud"))))
        (kill-buffer buf)))))

(provide 'cube-rolodex-test)
;;; cube-rolodex-test.el ends here
