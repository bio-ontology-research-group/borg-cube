;;; cube-roster.el --- Roster reconciliation in the cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, outlines

;;; Commentary:

;; The roster view is a read-only comparison of the sources known by the
;; backend.  Sync remains an explicit dry-run/apply operation, and conflicts
;; are shown with every source value rather than being silently resolved.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'diff-mode)
(require 'tabulated-list)
(require 'cube-core)
(require 'cube-org)

(defcustom cube-roster-confirm t
  "When non-nil ask before applying a roster sync."
  :type 'boolean
  :group 'borg-cube)

(defcustom cube-roster-host nil
  "Host that answers `cube roster', or nil for this machine.
The roster reads `~/org/staff.org' and `~/pa'; those live on the laptop,
where Emacs runs, and the ws copy lags behind uncommitted edits.  So the
roster deliberately does not follow `cube-remote-host'."
  :type '(choice (const :tag "Local" nil) (string :tag "ssh host"))
  :group 'borg-cube)

(defvar cube-roster--json nil
  "Roster payload from the last successful fetch.")

(defconst cube-roster--sources
  '((staff_org . "staff") (website . "web") (roster_md . "roster")
    (kg . "KG") (people_yaml . "people"))
  "Source keys and compact table headings.")

;;;; Pure rendering

(defun cube-roster--check (value)
  "Return a check mark when VALUE is true, otherwise a blank."
  (if (cube-true-p value) "✓" ""))

(defun cube-roster--conflict-count (person)
  "Return the number of field conflicts in PERSON."
  (length (cube-get person 'conflicts)))

(defun cube-roster--row (person)
  "Return a display row for PERSON as (ID VECTOR)."
  (let ((inside (cube-get person 'in)))
    (list person
          (vconcat
           (list (cube--string (cube-get person 'name))
                 (cube--string (cube-get person 'role)))
           (mapcar (lambda (source) (cube-roster--check
                                      (cube-get inside (car source))))
                   cube-roster--sources)
           (list (cube--string (cube-get person 'status))
                 (if (> (cube-roster--conflict-count person) 0)
                     (format "%d conflict%s" (cube-roster--conflict-count person)
                             (if (= (cube-roster--conflict-count person) 1) "" "s"))
                   ""))))))

(defun cube-roster--table-text (json)
  "Return a plain, pure rendering of the parsed roster JSON."
  (with-temp-buffer
    (insert "Roster\n\n")
    (insert (format "%-24s %-18s %5s %3s %6s %3s %6s %-10s %s\n"
                    "Name" "Role" "staff" "web" "roster" "KG" "people" "Status"
                    "Conflicts"))
    (insert (make-string 100 ?-) "\n")
    (dolist (person (cube-get json 'people))
      (let* ((row (cube-roster--row person))
             (vector (cadr row)))
        (insert (format "%-24s %-18s %5s %3s %6s %3s %6s %-10s %s\n"
                        (aref vector 0) (aref vector 1) (aref vector 2) (aref vector 3)
                        (aref vector 4) (aref vector 5) (aref vector 6) (aref vector 7)
                        (aref vector 8)))))
    (buffer-string)))

(defun cube-roster--conflict-text (person)
  "Return source values for every conflict in PERSON."
  (with-temp-buffer
    (insert (format "Roster conflict: %s (%s)\n\n"
                    (cube--string (cube-get person 'name))
                    (cube--string (cube-get person 'slug))))
    (dolist (conflict (cube-get person 'conflicts))
      (insert (format "%s:\n" (cube--string (cube-get conflict 'field))))
      (dolist (pair (cube-get conflict 'values))
        (insert (format "  %s: %s\n" (cube--string (car pair))
                        (cube--string (cdr pair))))))
    (buffer-string)))

;;;; Backend access and buffers

(defun cube-roster--fetch (callback)
  "Fetch the roster from `cube-roster-host' and call CALLBACK with parsed JSON."
  (cube--call-json-async-on
   cube-roster-host
   '("roster")
   (lambda (json) (setq cube-roster--json json) (funcall callback json))
   (lambda (code err) (message "cube: roster failed (%s): %s" code err))))

(defvar cube-roster-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map tabulated-list-mode-map)
    (define-key map (kbd "g") #'cube-roster-refresh)
    (define-key map (kbd "RET") #'cube-roster-visit)
    (define-key map (kbd "s") #'cube-roster-sync-dry-run)
    (define-key map (kbd "S") #'cube-roster-sync-apply)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap of `cube-roster-mode'.")

(define-derived-mode cube-roster-mode tabulated-list-mode "cube-roster"
  "People and source agreement from `cube roster'."
  (setq tabulated-list-format
        [("Name" 24 t) ("Role" 18 t) ("staff" 5 t) ("web" 3 t)
         ("roster" 6 t) ("KG" 3 t) ("people" 6 t) ("Status" 10 t)
         ("Conflicts" 0 t)])
  (setq tabulated-list-padding 1)
  (add-hook 'tabulated-list-revert-hook #'cube-roster-refresh nil t)
  (tabulated-list-init-header))

(defun cube-roster--render (json)
  "Render JSON in the *cube-roster* table and return its buffer."
  (with-current-buffer (get-buffer-create "*cube-roster*")
    (unless (derived-mode-p 'cube-roster-mode) (cube-roster-mode))
    (let ((inhibit-read-only t))
      (setq tabulated-list-entries
            (mapcar #'cube-roster--row (cube-get json 'people)))
      (tabulated-list-print t))
    (current-buffer)))

(defun cube-roster-refresh ()
  "Fetch and redraw the roster."
  (interactive)
  (cube-roster--fetch (lambda (json) (cube-roster--render json))))

(defun cube-roster ()
  "Show the roster and source agreement."
  (interactive)
  (pop-to-buffer (cube-roster--render (or cube-roster--json '((people)))))
  (cube-roster-refresh))

(defun cube-roster--current ()
  "Return the person at point, or signal a user error."
  (or (tabulated-list-get-id) (user-error "cube: no person at point")))

(defun cube-roster-visit ()
  "Show source values for a conflict, or open the person's org file."
  (interactive)
  (let ((person (cube-roster--current)))
    (if (cube-get person 'conflicts)
        (with-current-buffer
            (get-buffer-create (format "*cube-roster-conflict: %s*"
                                       (cube-get person 'slug)))
          (let ((inhibit-read-only t))
            (erase-buffer)
            (insert (cube-roster--conflict-text person))
            (goto-char (point-min)))
          (special-mode)
          (pop-to-buffer (current-buffer)))
      (cube-org-open-person (cube-get person 'slug)))))

;;;; Sync

(defun cube-roster--sync-args (&optional flag)
  "Return `cube roster sync' ARGS with FLAG, defaulting to dry-run."
  (list "roster" "sync" (or flag "--dry-run")))

(defun cube-roster--show-plan (json args)
  "Show the people.yaml diff from JSON for ARGS."
  (with-current-buffer (get-buffer-create "*cube-roster-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert "cube roster sync dry-run\n\n"
              (cube--shell-join (append (cube--program-args) args)) "\n\n"
              (or (cube-get json 'diff) "(no people.yaml changes reported)\n"))
      (goto-char (point-min)))
    (diff-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-roster--sync (&optional apply)
  "Run roster sync's dry-run, applying only when APPLY is confirmed."
  (let ((dry (cube-roster--sync-args)))
    (cube--call-json-async-on
     cube-roster-host
     dry
     (lambda (json)
       (cube-roster--show-plan json dry)
       (when (and apply
                  (or (not cube-roster-confirm)
                      (y-or-n-p "Apply roster sync to people.yaml? ")))
         (cube--call-json-async-on
          cube-roster-host
          (cube-roster--sync-args "--apply")
          (lambda (_result) (message "cube: roster sync applied")
            (cube-roster-refresh))
          (lambda (code err) (message "cube: roster apply failed (%s): %s" code err)))))
     (lambda (code err) (message "cube: roster dry-run failed (%s): %s" code err)))))

(defun cube-roster-sync-dry-run ()
  "Show the people.yaml diff without applying it."
  (interactive)
  (cube-roster--sync nil))

(defun cube-roster-sync-apply ()
  "Show the people.yaml diff and apply it after confirmation."
  (interactive)
  (cube-roster--sync t))

(provide 'cube-roster)
;;; cube-roster.el ends here
