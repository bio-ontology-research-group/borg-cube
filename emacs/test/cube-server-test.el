;;; cube-server-test.el --- Tests for cube-server  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(ert-deftest cube-server-hook-event-names ()
  (should (equal (cube-hooks-event-name "Stop") "stop"))
  (should (equal (cube-hooks-event-name "Notification") "notification"))
  (should (equal (cube-hooks-event-name "SessionStart") "start"))
  (should (equal (cube-hooks-event-name "UserPromptSubmit") "prompt"))
  (should (equal (cube-hooks-event-name "SessionEnd") "end"))
  (should (equal (cube-hooks-event-name "Weird") "weird"))
  (should (equal (cube-hooks-event-name nil) "unknown")))

(ert-deftest cube-server-map-claude-stop ()
  (let* ((payload (cube-test-read-fixture "hook-stop.json"))
         (args (cube-hooks-claude->notify payload "alex-plan")))
    (should (equal (nth 0 args) "alex-plan"))
    (should (equal (nth 1 args) "stop"))
    (should (equal (nth 2 args) "Claude finished its turn"))
    (should (string-match-p "12 tests pass" (nth 3 args)))
    (should (equal (plist-get (nth 4 args) :source) "claude"))
    (should (equal (plist-get (nth 4 args) :hook) "Stop"))
    (should (equal (plist-get (nth 4 args) :resume-id)
                   "8f1c2a7e-3b1d-4c55-9c1e-1d2f3a4b5c6d"))
    ;; without CUBE_SESSION the claude session id names the session
    (should (equal (car (cube-hooks-claude->notify payload))
                   "8f1c2a7e-3b1d-4c55-9c1e-1d2f3a4b5c6d"))))

(ert-deftest cube-server-map-claude-notification ()
  (let* ((payload (cube-test-read-fixture "hook-notification.json"))
         (args (cube-hooks-claude->notify payload "alex-plan")))
    (should (equal (nth 1 args) "notification"))
    (should (equal (nth 2 args) "Claude needs your permission to use Bash"))
    (should (equal (nth 3 args) "Claude needs your permission to use Bash"))
    (should (equal (plist-get (nth 4 args) :notification-type) "permission_prompt"))
    (should (eq (cube-server--event-state (nth 1 args)) 'attention))))

(ert-deftest cube-server-map-codex ()
  (let* ((payload (cube-test-read-fixture "codex-notify.json"))
         (args (cube-hooks-codex->notify payload "fix-tests")))
    (should (equal (nth 0 args) "fix-tests"))
    (should (equal (nth 1 args) "stop"))
    (should (equal (nth 2 args) "Codex finished its turn"))
    (should (string-match-p "off-by-one" (nth 3 args)))
    (should (equal (plist-get (nth 4 args) :source) "codex"))
    (should (equal (plist-get (nth 4 args) :turn-id) "t-7"))
    (should (equal (car (cube-hooks-codex->notify payload))
                   "b3c2d1e0-9f8e-4d7c-b6a5-4c3d2e1f0a9b")))
  ;; underscore variant of older Codex builds
  (let ((args (cube-hooks-codex->notify
               (cube--parse-json-string
                "{\"type\":\"agent-turn-complete\",\"thread_id\":\"t\",\"last_assistant_message\":\"m\"}"))))
    (should (equal (nth 0 args) "t"))
    (should (equal (nth 3 args) "m"))))

(ert-deftest cube-server-event-states ()
  (should (eq (cube-server--event-state "stop") 'idle))
  (should (eq (cube-server--event-state "notification") 'attention))
  (should (eq (cube-server--event-state "error") 'error))
  (should (eq (cube-server--event-state "end") 'exited))
  (should (eq (cube-server--event-state "start") 'running))
  (should (null (cube-server--event-state "heartbeat"))))

(ert-deftest cube-server-notify-updates-rolodex ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (let* ((seen nil)
             (cube-notify-hook (list (lambda (&rest args) (push args seen)))))
        ;; unknown session gets registered
        (let ((s (cube-notify "alex-plan" "notification" "needs permission" nil
                              '(:source "claude" :resume-id "8f1c" :kind "claude"))))
          (should (eq (cube-rolodex-find "alex-plan") s))
          (should (eq (cube-session-kind s) 'claude))
          (should (eq (cube-session-state s) 'attention))
          (should (equal (cube-session-reason s) "needs permission"))
          (should (equal (cube-session-resume-id s) "8f1c")))
        (cube-notify "alex-plan" 'prompt "asked something")
        (should (eq (cube-session-state (cube-rolodex-find "alex-plan")) 'running))
        (should (null (cube-session-reason (cube-rolodex-find "alex-plan"))))
        (cube-notify "alex-plan" "STOP" "done")
        (should (eq (cube-session-state (cube-rolodex-find "alex-plan")) 'idle))
        (cube-notify "alex-plan" "heartbeat")
        (should (eq (cube-session-state (cube-rolodex-find "alex-plan")) 'idle))
        (should (= (length seen) 4))
        (should (equal (nth 1 (car (last seen))) "notification"))))))

(ert-deftest cube-server-p0-notifies-when-session-is-selected ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (let ((buffer (get-buffer-create " *cube-p0-session*"))
            (notifications nil))
        (unwind-protect
            (progn
              (cube-rolodex--register
               (cube-session-create :name "fix-tests" :kind 'codex :buffer buffer))
              (save-window-excursion
                (switch-to-buffer buffer)
                (cl-letf (((symbol-function 'cube--notify-desktop)
                           (lambda (&rest args) (push args notifications))))
                  (cube-server-dispatch-event
                   (cube-test-read-fixture "p0-event.json"))))
              (should notifications)
              (should (eq (nth 2 (car notifications)) 'critical)))
          (kill-buffer buffer))))))

(ert-deftest cube-server-dispatch-event-lines ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (let ((calls nil))
        (cl-letf (((symbol-function 'cube-notify)
                   (lambda (&rest args) (push args calls) nil)))
          (with-temp-buffer
            (insert-file-contents (cube-test-fixture "events.jsonl"))
            (let ((rest (cube-server--dispatch-lines (buffer-string))))
              (should (equal rest "")))))
        (setq calls (nreverse calls))
        (should (= (length calls) 5))
        (pcase-let ((`(,session ,event ,title ,body ,plist) (nth 0 calls)))
          (should (equal session "alex-plan"))
          (should (equal event "stop"))
          (should (equal title "Claude finished its turn"))
          (should (string-suffix-p "state/bodies/1041.md" body))
          (should (file-name-absolute-p body))
          (should (equal (plist-get plist :source) "claude"))
          (should (equal (plist-get plist :resume-id) "8f1c2a7e-3b1d-4c55-9c1e-1d2f3a4b5c6d"))
          (should (= (plist-get plist :seq) 1041)))
        (pcase-let ((`(,session ,event ,_ ,body ,plist) (nth 1 calls)))
          (should (equal session "fix-tests"))
          (should (equal event "notification"))
          (should (null body))
          (should (equal (plist-get plist :bead) "cube-142")))
        ;; run without a session name is keyed by run_id
        (pcase-let ((`(,session ,event ,_ ,_ ,plist) (nth 2 calls)))
          (should (equal session "r-20260902-0912-a1"))
          (should (equal event "finished"))
          (should (equal (cube-get (plist-get plist :data) 'exit) 0)))
        (should (equal (nth 1 (nth 4 calls)) "error"))))))

(ert-deftest cube-server-dispatch-partial-lines ()
  (let ((calls nil))
    (cl-letf (((symbol-function 'cube-notify)
               (lambda (&rest args) (push args calls) nil)))
      (let ((rest (cube-server--dispatch-lines
                   "{\"session\":\"a\",\"event\":\"stop\"}\n{\"session\":\"b\",")))
        (should (equal rest "{\"session\":\"b\","))
        (should (= (length calls) 1))
        (setq rest (cube-server--dispatch-lines (concat rest "\"event\":\"start\"}\n")))
        (should (equal rest ""))
        (should (= (length calls) 2))
        ;; a bad line is logged, not fatal
        (should (equal (cube-server--dispatch-lines "not json\n") ""))
        (should (= (length calls) 2))))))

(ert-deftest cube-server-remote-body-file-is-tramp ()
  (cube-test-with-remote
    (let ((calls nil))
      (cl-letf (((symbol-function 'cube-notify)
                 (lambda (&rest args) (push args calls) nil)))
        (cube-server-dispatch-event
         (cube--parse-json-string
          "{\"session\":\"s\",\"event\":\"stop\",\"body_file\":\"state/bodies/1.md\"}"))
        (should (equal (nth 3 (car calls))
                       "/ssh:ws:~/Public/software/borg-cube/state/bodies/1.md"))))))

(ert-deftest cube-server-local-watch-reads-appended-lines ()
  "The inotify watch starts at the current end of the file and reads
only appended lines.  The change handler is called directly because
file-notify events travel through the keyboard queue, which batch ert
does not pump."
  (skip-unless (bound-and-true-p file-notify--library))
  (let* ((root (make-temp-file "cube-test-root" t))
         (cube-remote-host nil)
         (cube-root root)
         (cube-notify-method nil)
         (cube-server--events-watch nil)
         (cube-server--events-offset 0)
         (cube-server--events-pending "")
         (cube-server--events-enabled nil)
         (file (expand-file-name "state/events.jsonl" root))
         (calls nil))
    (unwind-protect
        (cl-letf (((symbol-function 'cube-notify)
                   (lambda (&rest args) (push args calls) nil)))
          (make-directory (file-name-directory file) t)
          (with-temp-file file (insert "{\"session\":\"old\",\"event\":\"stop\"}\n"))
          (cube-server-watch-events)
          (should cube-server--events-watch)
          (should (> cube-server--events-offset 0))
          ;; nothing new yet
          (cube-server--local-change (list cube-server--events-watch 'changed file))
          (should (null calls))
          ;; append a full line and half of another
          (with-temp-buffer
            (insert "{\"session\":\"new\",\"event\":\"start\"}\n{\"session\":")
            (append-to-file (point-min) (point-max) file))
          (cube-server--local-change (list cube-server--events-watch 'changed file))
          (should (= (length calls) 1))
          (should (equal (car (car calls)) "new"))
          (should (equal cube-server--events-pending "{\"session\":"))
          (with-temp-buffer
            (insert "\"third\",\"event\":\"stop\"}\n")
            (append-to-file (point-min) (point-max) file))
          (cube-server--local-change (list cube-server--events-watch 'changed file))
          (should (= (length calls) 2))
          (should (equal (car (car calls)) "third"))
          ;; events for other files in the directory are ignored
          (cube-server--local-change
           (list cube-server--events-watch 'changed (expand-file-name "state/other" root)))
          (should (= (length calls) 2))
          ;; truncation (rotation) resets the offset
          (with-temp-file file (insert "{\"session\":\"rot\",\"event\":\"stop\"}\n"))
          (cube-server--local-change (list cube-server--events-watch 'changed file))
          (should (equal (car (car calls)) "rot")))
      (cube-server-unwatch-events)
      (delete-directory root t))))

(ert-deftest cube-server-hook-script-claude ()
  (skip-unless (and (executable-find "bash") (executable-find "jq")))
  (let* ((tmp (make-temp-file "cube-hook-tmp" t))
         (process-environment
          (append (list (concat "CUBE_EMACSCLIENT=" (expand-file-name "emacsclient" cube-test-bin))
                        (concat "CUBE_FAKE_OUT=" (expand-file-name "out" tmp))
                        (concat "CUBE_TMPDIR=" tmp)
                        "CUBE_SESSION=alex-plan")
                  process-environment))
         (script (expand-file-name "../bin/cube-emacs-hook" cube-test-dir)))
    (unwind-protect
        (with-temp-buffer
          (let ((code (call-process script (cube-test-fixture "hook-notification.json")
                                    nil nil)))
            (should (eql code 0))
            (insert-file-contents (expand-file-name "out" tmp))
            (let* ((lines (split-string (buffer-string) "\n" t))
                   (form (car (last lines))))
              (should (equal (seq-take lines 3) '("-s" "cube" "--eval")))
              (should (string-prefix-p "(cube-notify " form))
              (let ((sexp (car (read-from-string form))))
                (should (equal (nth 1 sexp) "alex-plan"))
                (should (equal (nth 2 sexp) "notification"))
                (should (equal (nth 3 sexp) "Claude needs your permission to use Bash"))
                (should (stringp (nth 4 sexp)))
                (should (file-exists-p (nth 4 sexp)))
                (should (equal (plist-get (cdr (nth 5 sexp)) :source) "claude"))))))
      (delete-directory tmp t))))

(ert-deftest cube-server-hook-script-codex ()
  (skip-unless (and (executable-find "bash") (executable-find "jq")))
  (let* ((tmp (make-temp-file "cube-hook-tmp" t))
         (process-environment
          (append (list (concat "CUBE_EMACSCLIENT=" (expand-file-name "emacsclient" cube-test-bin))
                        (concat "CUBE_FAKE_OUT=" (expand-file-name "out" tmp))
                        (concat "CUBE_TMPDIR=" tmp))
                  (seq-remove (lambda (e) (string-prefix-p "CUBE_SESSION=" e))
                              process-environment)))
         (script (expand-file-name "../bin/cube-emacs-hook" cube-test-dir))
         (payload (with-temp-buffer
                    (insert-file-contents (cube-test-fixture "codex-notify.json"))
                    (buffer-string))))
    (unwind-protect
        (with-temp-buffer
          (let ((code (call-process script nil nil nil "codex" payload)))
            (should (eql code 0))
            (insert-file-contents (expand-file-name "out" tmp))
            (let* ((form (car (last (split-string (buffer-string) "\n" t))))
                   (sexp (car (read-from-string form))))
              (should (equal (nth 1 sexp) "b3c2d1e0-9f8e-4d7c-b6a5-4c3d2e1f0a9b"))
              (should (equal (nth 2 sexp) "stop"))
              (should (equal (nth 3 sexp) "Codex finished its turn"))
              (with-temp-buffer
                (insert-file-contents (nth 4 sexp))
                (should (string-match-p "off-by-one" (buffer-string))))
              (should (equal (plist-get (cdr (nth 5 sexp)) :source) "codex")))))
      (delete-directory tmp t))))

(ert-deftest cube-server-hook-script-survives-garbage ()
  (skip-unless (executable-find "bash"))
  (let ((script (expand-file-name "../bin/cube-emacs-hook" cube-test-dir))
        (process-environment
         (cons (concat "CUBE_EMACSCLIENT=" (expand-file-name "emacsclient" cube-test-bin))
               process-environment)))
    (with-temp-buffer
      (insert "this is not json")
      (should (eql 0 (call-process-region (point-min) (point-max) script nil nil nil))))
    (should (eql 0 (call-process script nil nil nil "codex")))))

(ert-deftest cube-server-show-markdown ()
  (let ((buf (save-window-excursion (cube-show-markdown "# Hello\n\ntext" "test"))))
    (unwind-protect
        (with-current-buffer buf
          (should (equal (buffer-name) "*cube:markdown:test*"))
          (should (string-prefix-p "# Hello" (buffer-string)))
          (should buffer-read-only))
      (kill-buffer buf))))

(provide 'cube-server-test)
;;; cube-server-test.el ends here

(ert-deftest cube-server-only-important-events-notify-and-never-twice ()
  "Only goal and error events notify, once per window; muted repeats never."
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (let ((notifications nil)
            (cube-server--notified (make-hash-table :test #'equal)))
        (cl-letf (((symbol-function 'cube--notify-desktop)
                   (lambda (&rest args) (push args notifications))))
          (dolist (event '("finished" "stop" "notification" "attention" "approval" "queued"))
            (cube-server-dispatch-event
             (list (cons 'session "agent-x") (cons 'event event) (cons 'title "done"))))
          (should-not notifications)
          (cube-server-dispatch-event
           '((session . "agent-x") (event . "error") (title . "sync failed")))
          (cube-server-dispatch-event
           '((session . "agent-x") (event . "error") (title . "sync failed")))
          (should (= (length notifications) 1))
          (cube-server-dispatch-event
           '((session . "agent-x") (event . "error") (title . "something else") (muted . t)))
          (should (= (length notifications) 1))
          (cube-server-dispatch-event
           '((session . "patrol-goals") (event . "goal") (title . "Goal complete: reports")))
          (should (= (length notifications) 2))
          (should (eq (nth 2 (car notifications)) 'normal))
          (should (eq (cube-server--event-state "queued") 'idle)))))))
