;;; cube-people.el --- People board for the borg-cube cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;;; Commentary:

;; The roster checks source consistency.  This board is the operational view of
;; current people: their active goals, owed work, meeting cadence, and milestone.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'tabulated-list)
(require 'cube-core)
(require 'cube-org)

(declare-function cube-menu--context-items "cube-menu" (type))

(defvar-local cube-people--people nil
  "People currently displayed by cube-people-mode.")

(defun cube-people--current-p (person)
  "Return non-nil when PERSON is a current member."
  (not (member (cube-get person 'status) '("former" "alumni" "dropped"))))

(defun cube-people--last-meeting-text (person &optional now)
  "Return the age of PERSON's last meeting, using NOW when supplied."
  (let* ((meeting (cube-get person 'last_meeting))
         (stamp (if (and (stringp meeting) (= (length meeting) 10))
                    (concat meeting "T00:00:00+03:00")
                  meeting))
         (age (cube--age-string stamp now)))
    (if (string-empty-p age) "never" (concat age " ago"))))

(defun cube-people--milestone-text (person)
  "Return a compact next-milestone description for PERSON."
  (if-let* ((milestone (cube-get person 'next_milestone)))
      (format "%s%s" (cube--string (cube-get milestone 'name))
              (if-let* ((days (cube-get milestone 'days))) (format " (%sd)" days) ""))
    "-"))

(defun cube-people--entry (person &optional now)
  "Return one pure tabulated-list entry for PERSON."
  (list (cube--string (cube-get person 'slug))
        (vector (cube--string (cube-get person 'name))
                (cube--string (cube-get person 'role))
                (number-to-string (length (cube-get person 'goals)))
                (number-to-string (length (cube-get person 'owed)))
                (cube-people--last-meeting-text person now)
                (cube-people--milestone-text person))))

(defun cube-people--entries (people &optional now)
  "Return People board rows for current PEOPLE, using NOW for ages."
  (mapcar (lambda (person) (cube-people--entry person now))
          (seq-filter #'cube-people--current-p people)))

(defvar cube-people--row-map
  (let ((map (make-sparse-keymap)))
    (define-key map [mouse-1] #'cube-people-mouse-visit)
    (define-key map [mouse-3] #'cube-people-mouse-context)
    map)
  "Mouse map applied to People board rows.")

(defun cube-people--install-mouse-actions ()
  "Attach shared row mouse actions after the tabulated list has rendered."
  (save-excursion
    (goto-char (point-min))
    (forward-line 2)
    (while (not (eobp))
      (add-text-properties (line-beginning-position) (line-end-position)
                           '(mouse-face highlight keymap cube-people--row-map
                             help-echo "RET opens dossier; mouse-3 shows actions"))
      (forward-line 1))))

(defun cube-people--render ()
  "Render the People board from the current people cache."
  (setq tabulated-list-entries (cube-people--entries cube-people--people))
  (tabulated-list-print t)
  (cube-people--install-mouse-actions))

(defun cube-people-refresh ()
  "Refresh the People board from cube people."
  (interactive)
  (let ((buffer (current-buffer)))
    (cube--call-json-async
     '("people")
     (lambda (json)
       (when (buffer-live-p buffer)
         (with-current-buffer buffer
           (setq cube-people--people (cube-get json 'people)
                 cube-org--people cube-people--people)
           (cube-people--render))))
     (lambda (code err) (message "cube: people failed (%s): %s" code err)))))

(defun cube-people--current-person ()
  "Return the person at point, or signal a user error."
  (let ((slug (tabulated-list-get-id)))
    (or (seq-find (lambda (person) (equal (cube-get person 'slug) slug))
                  cube-people--people)
        (user-error "cube: no person at point"))))

(defun cube-people-visit ()
  "Open the extended existing dossier for the person at point."
  (interactive)
  (let ((person (cube-people--current-person)))
    (cube-org-person-context (cube-get person 'slug) person)))

(defun cube-people-open-org ()
  "Open the person's notes file."
  (interactive)
  (cube-org-open-person (cube-get (cube-people--current-person) 'slug)))

(defun cube-people-meeting-note ()
  "Add a dated meeting heading for the person at point."
  (interactive)
  (cube-org-meeting-note (cube-get (cube-people--current-person) 'slug)))

(defun cube-people--mouse-position (event)
  "Return the buffer and point represented by mouse EVENT."
  (let* ((posn (event-end event)) (window (posn-window posn)) (point (posn-point posn)))
    (when (and (windowp window) (integer-or-marker-p point))
      (list (window-buffer window) point))))

(defun cube-people-mouse-visit (event)
  "Open the person row clicked by mouse-1 EVENT."
  (interactive "e")
  (when-let* ((position (cube-people--mouse-position event))
              (buffer (nth 0 position))
              (point (nth 1 position)))
    (with-current-buffer buffer
      (goto-char point)
      (cube-people-visit))))

(defun cube-people-mouse-context (event)
  "Show the command-table context actions for the person row in EVENT."
  (interactive "e")
  (when-let* ((position (cube-people--mouse-position event))
              (buffer (nth 0 position))
              (point (nth 1 position)))
    (with-current-buffer buffer
      (goto-char point)
      (when-let* ((items (cube-menu--context-items 'person))
                  (choice (popup-menu (cons "Person" items))))
        (call-interactively choice)))))

(defvar cube-people-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map tabulated-list-mode-map)
    (define-key map (kbd "g") #'cube-people-refresh)
    (define-key map (kbd "RET") #'cube-people-visit)
    (define-key map (kbd "o") #'cube-people-open-org)
    (define-key map (kbd "m") #'cube-people-meeting-note)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap of cube-people-mode.")

(define-derived-mode cube-people-mode tabulated-list-mode "cube-people"
  "Operational board for current people."
  (setq tabulated-list-format
        [("Person" 28 t) ("Role" 14 t) ("Goals" 7 t) ("Owed" 6 t)
         ("Last meeting" 14 t) ("Next milestone" 34 t)])
  (setq tabulated-list-padding 2)
  (tabulated-list-init-header))

(defun cube-people ()
  "Show one operational row per current group member."
  (interactive)
  (let ((buffer (get-buffer-create "*cube-people*")))
    (with-current-buffer buffer
      (unless (derived-mode-p 'cube-people-mode) (cube-people-mode))
      (setq cube-people--people (or cube-org--people nil))
      (cube-people--render))
    (pop-to-buffer buffer)
    (with-current-buffer buffer (cube-people-refresh))))

(provide 'cube-people)
;;; cube-people.el ends here
