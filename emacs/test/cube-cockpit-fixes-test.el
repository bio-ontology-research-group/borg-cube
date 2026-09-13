;;; cube-cockpit-fixes-test.el --- Goals, roles and roster reach the backend  -*- lexical-binding: t; -*-

;;; Commentary:
;; Robert, 2026-09-04: "I do not get goals in the cockpit; I should be able to
;; set goals, too.  Roles in the list to run do not match the roles in the
;; fleet.  roster also does not seem to work."  These tests pin each fix.

;;; Code:

(require 'ert)
(require 'cube-test-helper)
(require 'cube-rolodex)
(require 'cube-roster)
(require 'cube-goals)
(require 'cube-dashboard)

(defun cube-fixes-test--shipped-roles ()
  "Return the role names shipped in roles/*.yaml."
  (let ((dir (expand-file-name "../roles" (expand-file-name ".." cube-test-dir))))
    (sort (mapcar #'file-name-sans-extension
                  (seq-remove (lambda (name) (string-prefix-p "_" name))
                                  (directory-files dir nil "\\.yaml\\'")))
          #'string<)))

(ert-deftest cube-run-role-list-matches-the-shipped-role-catalog ()
  "The fallback list is the roles/*.yaml catalog: no stale `leader' entry."
  (should (equal (sort (copy-sequence cube-rolodex-roles-fallback) #'string<)
                 (cube-fixes-test--shipped-roles)))
  (should (equal (sort (copy-sequence cube-beads--role-fallback) #'string<)
                 (cube-fixes-test--shipped-roles)))
  (should-not (member "leader" cube-rolodex-roles-fallback)))

(ert-deftest cube-run-role-list-refreshes-from-cube-roles-json ()
  "`cube roles --json' replaces the fallback, wrapped or bare, names or objects."
  (should (equal (cube-rolodex--roles-from-json
                  '((roles . (((name . "senior")) ((name . "programmer"))))))
                 '("senior" "programmer")))
  (should (equal (cube-rolodex--roles-from-json ["auditor" "editor"]) nil))
  (should (equal (cube-rolodex--roles-from-json '("auditor" "editor")) '("auditor" "editor")))
  (let ((cube-rolodex-roles cube-rolodex-roles-fallback)
        (asked nil))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error)
                 (setq asked args)
                 (funcall callback '((roles . (((name . "senior")) ((name . "marshal")))))))))
      (cube-rolodex-roles-refresh)
      (should (equal asked '("roles")))
      (should (equal cube-rolodex-roles '("senior" "marshal"))))
    (cl-letf (((symbol-function 'cube--call-json) (lambda (_args) '((roles . ())))))
      ;; An empty answer keeps the current list rather than emptying completion.
      (should (equal (cube-rolodex-roles-now) '("senior" "marshal"))))))

(ert-deftest cube-roster-is-fetched-from-the-roster-host-not-the-backend-host ()
  "The roster reads ~/org on the laptop even when the backend is ws."
  (let ((seen nil))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error)
                 (push (cons cube-remote-host args) seen)
                 (funcall callback '((people . ()))))))
      (cube-test-with-remote
        (let ((cube-roster-host nil))
          (cube-roster--fetch #'ignore)
          (cube-roster--sync nil))
        (let ((cube-roster-host "laptop"))
          (cube-roster--fetch #'ignore))))
    (should (equal (nreverse seen)
                   '((nil "roster") (nil "roster" "sync" "--dry-run") ("laptop" "roster"))))))

(ert-deftest cube-dashboard-goals-section-lists-fixture-goals ()
  "The goals fixture renders one dashboard item per active goal."
  (let ((cube-dashboard--data nil))
    (cube-dashboard--store 'goals (cube-test-read-fixture "goals.json") nil)
    (let ((items (cube-dashboard--goal-items)))
      (should items)
      (should (cl-every (lambda (item) (eq (plist-get item :type) 'goal)) items)))))

(ert-deftest cube-goal-new-execute-runs-the-write-gate-with-apply ()
  "Setting a goal goes dry-run, then --apply after confirmation."
  (let ((calls nil)
        (cube-goal--new-plist (list :title "Ship it" :target "2026-12-01"
                                    :success (list "paper submitted")
                                    :provenance (list "mail:1"))))
    (cl-letf (((symbol-function 'cube--call-json-async)
               (lambda (args callback &optional _error)
                 (push args calls)
                 (funcall callback '((id . "cube-1")))))
              ((symbol-function 'cube-goal--show-plan) (lambda (&rest _) nil))
              ((symbol-function 'cube-goals-refresh) (lambda (&rest _) nil))
              ((symbol-function 'y-or-n-p) (lambda (_prompt) t)))
      (cube-goal-new-execute)
      (should (equal (mapcar (lambda (args) (car (last args))) (nreverse calls))
                     '("--dry-run" "--apply"))))))

(provide 'cube-cockpit-fixes-test)
;;; cube-cockpit-fixes-test.el ends here
