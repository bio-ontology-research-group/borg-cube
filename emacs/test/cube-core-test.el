;;; cube-core-test.el --- Tests for cube-core  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(ert-deftest cube-core-shell-quote-keeps-tilde ()
  (should (equal (cube--shell-quote "~/Public/borg cube/x") "~/Public/borg\\ cube/x"))
  (should (equal (cube--shell-quote "~") "~"))
  (should (equal (cube--shell-quote "~/") "~/"))
  (should (equal (cube--shell-quote "~robert/a b") "~robert/a\\ b"))
  (should (equal (cube--shell-quote "plain") "plain"))
  (should (equal (cube--shell-quote "{\"tui\":\"inline\"}")
                 (shell-quote-argument "{\"tui\":\"inline\"}"))))

(ert-deftest cube-core-shell-join-round-trips ()
  (let ((words '("claude" "--settings" "{\"tui\":\"inline\"}" "a b" "it's")))
    (should (equal (split-string-shell-command (cube--shell-join words)) words))))

(ert-deftest cube-core-ssh-args-local-passthrough ()
  (cube-test-with-local
    (should (equal (cube--ssh-args '("cube" "status" "--json"))
                   '("cube" "status" "--json")))))

(ert-deftest cube-core-ssh-args-remote-batch ()
  (cube-test-with-remote
    (let* ((cube-ssh-multiplex nil)
           (argv (cube--ssh-args '("cube" "status" "--json"))))
      (should (equal (butlast argv)
                     '("ssh" "-o" "ConnectTimeout=5" "-o" "BatchMode=yes" "ws" "--")))
      (should (equal (split-string-shell-command (car (last argv)))
                     '("cube" "status" "--json"))))))

(ert-deftest cube-core-ssh-args-remote-tty ()
  (cube-test-with-remote
    (let* ((cube-ssh-multiplex nil)
           (argv (cube--ssh-args '("tmux" "ls") t)))
      (should (equal (butlast argv)
                     '("ssh" "-t" "-o" "ConnectTimeout=5" "-o" "BatchMode=yes" "ws" "--")))
      (should (equal (car (last argv)) "tmux ls")))))

(ert-deftest cube-core-command-appends-json-once ()
  (cube-test-with-local
    (should (equal (cube--command '("status")) '("cube" "status" "--json")))
    (should (equal (cube--command '("status" "--json")) '("cube" "status" "--json")))
    (should (equal (cube--command '("tmux") t) '("cube" "tmux")))))

(ert-deftest cube-core-program-args-fallback ()
  (cube-test-with-local
    (let ((cube-program "definitely-not-a-program-xyz"))
      (should (equal (cube--program-args) cube-program-fallback))))
  (cube-test-with-remote
    (let ((cube-program "definitely-not-a-program-xyz"))
      (should (equal (cube--program-args) '("definitely-not-a-program-xyz"))))))

(ert-deftest cube-core-root-file ()
  (cube-test-with-remote
    (should (equal (cube-root-file "state/events.jsonl")
                   "~/Public/software/borg-cube/state/events.jsonl")))
  (cube-test-with-local
    (should (file-name-absolute-p (cube-root-file "state/events.jsonl")))
    (should-not (string-prefix-p "~" (cube-root-file "state/events.jsonl")))))

(ert-deftest cube-core-remote-file-name ()
  (cube-test-with-remote
    (should (equal (cube-remote-file-name "~/org/alex.org") "/ssh:ws:~/org/alex.org"))))

(ert-deftest cube-core-age-string ()
  (should (equal (cube--age-string nil) ""))
  (should (equal (cube--age-string "") ""))
  (should (equal (cube--age-string 0) "0s"))
  (should (equal (cube--age-string 59) "59s"))
  (should (equal (cube--age-string 61) "1m"))
  (should (equal (cube--age-string 3599) "59m"))
  (should (equal (cube--age-string 7200) "2h"))
  (should (equal (cube--age-string (* 3 86400)) "3d"))
  (should (equal (cube--age-string (* 21 86400)) "3w"))
  (let ((now (encode-time (iso8601-parse "2026-09-02T09:15:00+03:00"))))
    (should (equal (cube--age-string "2026-09-02T09:10:30+03:00" now) "4m"))
    (should (equal (cube--age-string "2026-09-01T09:15:00+03:00" now) "1d"))
    (should (equal (cube--age-string "not a date" now) ""))
    ;; Lisp time values (as stored in cube-session-last-activity)
    ;; (integers always mean seconds, so use the list form as `current-time' does)
    (should (equal (cube--age-string (time-convert (time-subtract now 120) 'list) now) "2m"))))

(ert-deftest cube-core-json-conventions ()
  (let ((obj (cube--parse-json-string
              "{\"a\": [1, 2, {\"b\": null, \"c\": false, \"d\": true}]}")))
    (should (equal (cube-get obj 'a 0) 1))
    (should (equal (cube-get obj 'a 2 'b) nil))
    (should (eq (cube-get obj 'a 2 'c) :false))
    (should (eq (cube-get obj 'a 2 'd) t))
    (should (null (cube-get obj 'missing 'deeper)))
    (should-not (cube-true-p :false))
    (should (cube-true-p t))))

(ert-deftest cube-core-fixtures-parse ()
  (dolist (spec '(("status.json" ok counts runs sessions)
                  ("attention.json" items)
                  ("ready.json" beads)
                  ("people.json" people)
                  ("student-alex.json" slug milestones evidence agenda_draft)
                  ("papers.json" papers)
                  ("literature.json" entries counts path)
                  ("projects.json" projects)
                  ("roster.json" people)
                  ("assign.json" id)
                  ("create.json" id)
                  ("repos.json" repos)
                  ("approvals.json" approvals)
                  ("run.json" ok run_id role)
                  ("doctor.json" ok checks)
                  ("agent-liaison-show.json" name host requests)
                  ("hook-stop.json" session_id hook_event_name)
                  ("hook-notification.json" session_id hook_event_name message)
                  ("codex-notify.json" type thread-id last-assistant-message)))
    (let ((obj (cube-test-read-fixture (car spec))))
      (dolist (key (cdr spec))
        (should (assq key obj))))))

(ert-deftest cube-core-attention-items-shape ()
  (let ((items (cube-get (cube-test-read-fixture "attention.json") 'items)))
    (should (= (length items) 3))
    (dolist (item items)
      (dolist (key '(id kind severity title since age target actions))
        (should (assq key item)))
      (should (listp (cube-get item 'actions)))
      (should (cube-get item 'target 'type)))))

(ert-deftest cube-core-call-json-sync-with-fake ()
  (cube-test-with-local
    (should (executable-find "cube"))
    (let ((status (cube--call-json '("status"))))
      (should (cube-true-p (cube-get status 'ok)))
      (should (= (cube-get status 'counts 'ready) 4)))
    (should (equal (cube-get (cube--call-json '("student" "alex-example")) 'slug) "alex-example"))
    (should-error (cube--call-json '("fail")) :type 'cube-error)
    (should-error (cube--call-json '("nonexistent")) :type 'cube-error)))

(ert-deftest cube-core-call-json-async-with-fake ()
  (cube-test-with-local
    (let ((result 'pending) (err nil))
      (cube--call-json-async '("attention")
                             (lambda (json) (setq result json))
                             (lambda (code msg) (setq err (list code msg))))
      (with-timeout (10 (ert-fail "async call timed out"))
        (while (eq result 'pending) (accept-process-output nil 0.05)))
      (should-not err)
      (should (= (length (cube-get result 'items)) 3)))
    (let ((err 'pending))
      (cube--call-json-async '("fail") #'ignore
                             (lambda (code msg) (setq err (list code msg))))
      (with-timeout (10 (ert-fail "async error timed out"))
        (while (eq err 'pending) (accept-process-output nil 0.05)))
      (should (= (car err) 7))
      (should (string-match-p "fake failure" (cadr err))))))

(ert-deftest cube-core-call-json-async-on-selects-its-explicit-host ()
  "An explicit nil host stays local while a named host receives ssh wrapping."
  (cube-test-with-local
    (let ((commands nil))
      (cl-letf (((symbol-function 'cube--call-async)
                 (lambda (command callback &optional _error)
                   (push command commands)
                   (funcall callback "{\"ok\": true}"))))
        (let ((cube-remote-host "ws"))
          (cube--call-json-async-on nil '("agent" "tell" "liaison" "hello") #'ignore)
          (cube--call-json-async-on "ws" '("agent" "tell" "coordinator" "hello") #'ignore)))
      (let ((remote (car commands))
            (local (cadr commands)))
        (should (equal (car local) "cube"))
        (should (equal (seq-take remote 5)
                       '("ssh" "-o" "ConnectTimeout=5" "-o" "BatchMode=yes")))
        (should (equal (last (butlast remote) 2) '("ws" "--")))
        (should (equal (split-string-shell-command (car (last remote)))
                       '("cube" "agent" "tell" "coordinator" "hello" "--json")))))))

(ert-deftest cube-core-log-appends ()
  (let ((cube-log-buffer-name " *cube-test-log*"))
    (when (get-buffer cube-log-buffer-name) (kill-buffer cube-log-buffer-name))
    (cube-log "hello %d" 42)
    (with-current-buffer cube-log-buffer-name
      (should (string-match-p "hello 42\n\\'" (buffer-string))))
    (kill-buffer cube-log-buffer-name)))

(provide 'cube-core-test)
;;; cube-core-test.el ends here


(ert-deftest cube-core-ssh-shares-one-master-connection-by-default ()
  "A dozen parallel dashboard calls must not open a dozen TCP connections."
  (cube-test-with-remote
    (let* ((cube-ssh-multiplex t)
           (cube-ssh-control-persist "10m")
           (argv (cube--ssh-args '("cube" "status" "--json"))))
      (should (member "ControlMaster=auto" argv))
      (should (member "ControlPersist=10m" argv))
      (should (seq-some (lambda (arg) (string-prefix-p "ControlPath=" arg)) argv))
      (should (equal (last (butlast argv) 2) '("ws" "--"))))))
