;;; cube-watch-test.el --- Watch one task from the cockpit  -*- lexical-binding: t; -*-

;;; Commentary:
;; Robert, 2026-09-13: "I need to be able to run this from the cockpit, and
;; WATCH how the task is being solved through the cockpit."  These tests pin
;; the pure parts of `cube-watch': event selection, trail lines, run choice,
;; create arguments and the rendered text.

;;; Code:

(require 'ert)
(require 'cube-test-helper)
(require 'cube-watch)

(defun cube-watch-test--bead ()
  '((id . "cube-142") (title . "Audit the Protégé plugin for release readiness")
    (status . "open")
    (labels . ("kind:audit" "stage:design" "privacy:public" "role:auditor"
               "project:kobayashi-marust" "repo:bio-ontology-research-group/kobayashi-marust"))
    (description . "---\nxid: manual:audit:1\nprovenance:\n- source: BH26 demo\nprivacy: public\n---\nAcceptance:\n- report with file:line findings")
    (acceptance_criteria . "report with file:line findings\nno outbound action")))

(ert-deftest cube-watch-event-relevance-by-bead-run-or-session ()
  (should (cube-watch--event-relevant-p "cube-142" nil "x" '(:bead "cube-142")))
  (should (cube-watch--event-relevant-p "cube-142" "r-1" "run-r-1" '(:bead nil)))
  (should (cube-watch--event-relevant-p "cube-142" "r-1" "other" '(:run-id "r-1")))
  (should-not (cube-watch--event-relevant-p "cube-142" "r-1" "other" '(:bead "cube-9" :run-id "r-2")))
  (should-not (cube-watch--event-relevant-p "cube-142" nil "run-r-1" '())))

(ert-deftest cube-watch-trail-lines-show-tool-calls-and-outcomes ()
  (let* ((pre (cube-watch--entry "run-r-1" "tool" "Read README.md"
                                 '(:ts "2026-09-13T10:15:02+03:00" :seq 7 :run-id "r-1"
                                   :data ((tool . "Read") (phase . "pre")))))
         (post (cube-watch--entry "run-r-1" "tool" "Read README.md"
                                  '(:ts "2026-09-13T10:15:03+03:00" :seq 8
                                    :data ((tool . "Read") (phase . "post")))))
         (done (cube-watch--entry "run-r-1" 'finished "audit filed" '(:ts nil :seq 9))))
    (should (equal (plist-get pre :tool) "Read"))
    (should (string-match-p "\\`10:15:02 · tool +Read README.md\\'" (cube-watch--trail-line pre)))
    (should (string-match-p "done: Read README.md" (cube-watch--trail-line post)))
    (should (string-match-p "✓ finished +audit filed" (cube-watch--trail-line done)))
    (should (equal (plist-get done :event) "finished"))))

(ert-deftest cube-watch-trail-dedupes-by-seq-and-flags-state-changes ()
  (let* ((a (cube-watch--entry "s" "tool" "x" '(:seq 1)))
         (b (cube-watch--entry "s" "tool" "y" '(:seq 2)))
         (trail (cube-watch--append-entry (cube-watch--append-entry nil a) b)))
    (should (equal (length (cube-watch--append-entry trail a)) 2))
    (should (equal (length (cube-watch--append-entry trail (cube-watch--entry "s" "tool" "z" '(:seq nil)))) 3))
    (should (cube-watch--state-changing-p "finished"))
    (should (cube-watch--state-changing-p "attention"))
    (should-not (cube-watch--state-changing-p "tool"))))

(ert-deftest cube-watch-entry-from-events-jsonl-line ()
  (let ((entry (cube-watch--entry-from-line
                '((ts . "2026-09-13T10:15:02+03:00") (seq . 41) (source . "claude")
                  (session . "run-r-20260913-1015-ab") (event . "tool")
                  (title . "Grep secret") (run_id . "r-20260913-1015-ab") (bead . "cube-142")
                  (data . ((hook . "PreToolUse") (tool . "Grep") (phase . "pre")))))))
    (should (equal (plist-get entry :bead) "cube-142"))
    (should (equal (plist-get entry :run-id) "r-20260913-1015-ab"))
    (should (equal (plist-get entry :tool) "Grep"))
    (should (equal (plist-get entry :seq) 41))))

(ert-deftest cube-watch-picks-the-newest-run-for-the-bead ()
  (let ((status '((runs . (((run_id . "r-1") (bead . "cube-142") (started . "2026-09-13T09:00:00+03:00"))
                           ((run_id . "r-2") (bead . "cube-9") (started . "2026-09-13T09:30:00+03:00"))
                           ((run_id . "r-3") (bead . "cube-142") (started . "2026-09-13T10:00:00+03:00")))))))
    (should (equal (cube-watch--latest-run-id "cube-142" status nil) "r-3"))
    (should (equal (cube-watch--latest-run-id "cube-7" status
                                              (list (cube-watch--entry "s" "start" "x" '(:run-id "r-9"))))
                   "r-9"))
    (should-not (cube-watch--latest-run-id "cube-7" nil nil))))

(ert-deftest cube-watch-create-args-carry-labels-and-stay-dry-run ()
  (let ((args (cube-watch--create-args
               '(:title "Audit the Protégé plugin" :kind "audit" :role "auditor"
                 :project "kobayashi-marust" :privacy "public"
                 :acceptance "report with file:line findings" :provenance ("BH26 demo")
                 :labels ("repo:bio-ontology-research-group/kobayashi-marust" "")))))
    (should (equal (car args) "create"))
    (should (member "--dry-run" args))
    (should (equal (cdr (member "--label" args)) '("repo:bio-ontology-research-group/kobayashi-marust")))
    (should (equal (length (seq-filter (lambda (a) (equal a "--label")) args)) 1))
    (should (member "--privacy" args))))

(ert-deftest cube-watch-render-text-has-task-run-trail-and-result ()
  (let* ((bead (cube-watch-test--bead))
         (run '((run_id . "r-1") (runner . "claude@openrouter") (model . "z-ai/glm-5.3-flash")
                (state . "finished") (started . "2026-09-13T10:00:00+03:00")
                (finished . "2026-09-13T10:04:00+03:00") (summary . "12 findings, 3 high")))
         (trail (list (cube-watch--entry "run-r-1" "start" "auditor" '(:ts "2026-09-13T10:00:00+03:00" :seq 1))
                      (cube-watch--entry "run-r-1" "tool" "Read README.md" '(:ts "2026-09-13T10:00:05+03:00" :seq 2))))
         (text (cube-watch--render-text bead run trail)))
    (should (string-match-p "Task cube-142: Audit the Protégé plugin" text))
    (should (string-match-p "role:auditor" text))
    (should (string-match-p "source: BH26 demo" text))
    (should (string-match-p " - report with file:line findings" text))
    (should (string-match-p "r-1  claude@openrouter/z-ai/glm-5.3-flash  finished  4m" text))
    (should (string-match-p "Trail (2)" text))
    (should (string-match-p "Read README.md" text))
    (should (string-match-p "12 findings, 3 high" text))
    (should (string-match-p "no run yet" (cube-watch--render-text bead nil nil)))))

(ert-deftest cube-watch-buffer-renders-and-routes-live-events ()
  (cube-test-with-remote
    (cube-test-with-clean-rolodex
      (let ((buffer (get-buffer-create (cube-watch--buffer-name "cube-142"))))
        (unwind-protect
            (with-current-buffer buffer
              (cube-watch-mode)
              (setq cube-watch--bead "cube-142"
                    cube-watch--bead-json (cube-watch-test--bead))
              (cube-watch--render)
              (should (string-match-p "Task cube-142" (buffer-string)))
              (should (string-match-p "Run: none yet" (buffer-string)))
              (cl-letf (((symbol-function 'cube-watch--schedule-refresh) #'ignore))
                (cube-watch--on-notify "run-r-5" "start" "auditor started" nil
                                       '(:bead "cube-142" :run-id "r-5" :seq 1 :ts "2026-09-13T10:00:00+03:00"))
                (cube-watch--on-notify "run-r-5" "tool" "Bash python3 audit_collect.py" nil
                                       '(:run-id "r-5" :seq 2 :data ((tool . "Bash") (phase . "pre"))))
                (cube-watch--on-notify "other" "tool" "unrelated" nil '(:bead "cube-9" :seq 3)))
              (should (equal cube-watch--run "r-5"))
              (should (equal (length cube-watch--trail) 2))
              (should (string-match-p "Trail (2 events)" (buffer-string)))
              (should (string-match-p "audit_collect.py" (buffer-string)))
              (should-not (string-match-p "unrelated" (buffer-string))))
          (kill-buffer buffer))))))

(ert-deftest cube-watch-role-and-session-name-come-from-labels ()
  (should (equal (cube-watch--role (cube-watch-test--bead)) "auditor"))
  (should (equal (cube-watch--label-values (cube-watch-test--bead) "repo")
                 '("bio-ontology-research-group/kobayashi-marust")))
  (should (equal (cube-watch--session-name "auditor" "cube-142") "auditor-cube-142")))

(provide 'cube-watch-test)
;;; cube-watch-test.el ends here
