;;; cube-org.el --- Org files of the group: people, meeting notes, papers  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, outlines

;;; Commentary:

;; Robert's knowledge about the group lives in ~/org: one file per person
;; with dated meeting headings (newest first), staff.org with the roster
;; and papers.org with a custom TODO sequence.  This file opens those
;; files (through TRAMP in remote mode), inserts dated meeting headings at
;; the right place, pulls agent-written notes in as a `:draft:' subtree,
;; and reconciles paper states between `cube papers' and papers.org.
;;
;; The text manipulation is in pure functions (`cube-org--insert-position',
;; `cube-org-md->org', `cube-org--papers-diff', `cube-org--parse-staff')
;; so it can be tested on samples without a host.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'tabulated-list)
(require 'org)
(require 'diff-mode)
(require 'transient)
(require 'cube-core)

(declare-function cube-beads-show "cube-beads" (id))

(defcustom cube-org-directory "~/org"
  "Directory of the org files, on the host in remote mode."
  :type 'string
  :group 'borg-cube)

(defcustom cube-org-papers-file "papers.org"
  "Papers file inside `cube-org-directory'."
  :type 'string
  :group 'borg-cube)

(defcustom cube-org-staff-file "staff.org"
  "Roster file inside `cube-org-directory', parsed when `cube people' fails."
  :type 'string
  :group 'borg-cube)

(defcustom cube-org-meeting-heading-format "%-d %B %Y"
  "Format of the dated meeting headings, for `format-time-string'."
  :type 'string
  :group 'borg-cube)

(defvar cube-org--people nil
  "Cached people list (alists as returned by `cube people').")

(defcustom cube-org-confirm-writes t
  "When non-nil ask before applying an org edit planned by `cube'."
  :type 'boolean
  :group 'borg-cube)

;;;; Files

(defun cube-org-file (name)
  "Return NAME inside `cube-org-directory' as a file name Emacs can open.
TRAMP in remote mode, local otherwise.  NAME may already be a path."
  (let ((path (cond ((or (file-name-absolute-p name) (string-prefix-p "~" name)) name)
                    (t (concat (directory-file-name cube-org-directory) "/" name)))))
    (if cube-remote-host
        (if (file-remote-p path) path (cube-remote-file-name path))
      (expand-file-name path))))

(defun cube-org--file-text (file)
  "Return the contents of FILE (already a full name) or nil."
  (when (ignore-errors (file-readable-p file))
    (with-temp-buffer (insert-file-contents file) (buffer-string))))

;;;; People

(defun cube-org--slugify (name)
  "Return NAME as a lowercase hyphenated slug."
  (string-trim (replace-regexp-in-string "[^a-z0-9]+" "-" (downcase name)) "-" "-"))

(defun cube-org--staff-role (section note)
  "Return the role for a roster line in SECTION with parenthesised NOTE."
  (let ((note (downcase (or note ""))))
    (cond ((string-match-p "postdoc" note) "postdoc")
          ((string-match-p "msc" note) "msc")
          ((string-match-p "intern\\|visit" note) "visitor")
          ((string-match-p "student" note) "phd")
          ((string-match-p "student" (downcase section)) "phd")
          (t "staff"))))

(defun cube-org--parse-staff (text)
  "Parse the roster TEXT (staff.org) into people alists.
Only list items under headings called Staff or Students are used.  Each
person gets slug, name, role and org_file (~/org/<first name>.org)."
  (let ((section nil) (people nil) (seen nil))
    (dolist (line (split-string text "\n"))
      (cond
       ((string-match "\\`\\*+[ \t]+\\(.*\\)\\'" line)
        (let ((title (string-trim (match-string 1 line))))
          (setq section (and (string-match-p "\\`\\(Staff\\|Students\\)\\b" title) title))))
       ((and section
             (string-match "\\`[ \t]*[-+*][ \t]+\\([^(]+?\\)[ \t]*\\(?:(\\([^)]*\\))\\)?[ \t]*\\'" line))
        (let* ((name (string-trim (match-string 1 line)))
               (note (match-string 2 line))
               (slug (cube-org--slugify name))
               (first (downcase (car (split-string name "[ \t]+" t)))))
          (unless (or (string-empty-p name) (member slug seen))
            (push slug seen)
            (push (list (cons 'slug slug) (cons 'name name)
                        (cons 'role (cube-org--staff-role section note))
                        (cons 'org_file (format "~/org/%s.org" first)))
                  people))))))
    (nreverse people)))

(defun cube-org-people (&optional refresh)
  "Return the people of the group as alists (see INTERFACE.md `people').
Uses the cache unless REFRESH; fetches `cube people --json' and falls
back to parsing staff.org when the backend is unavailable."
  (when (or refresh (null cube-org--people))
    (setq cube-org--people
          (condition-case err
              (cube-get (cube--call-json '("people")) 'people)
            (error
             (cube-log "cube people failed (%s); parsing %s"
                       (error-message-string err) cube-org-staff-file)
             (cube-org--parse-staff
              (or (cube-org--file-text (cube-org-file cube-org-staff-file)) ""))))))
  cube-org--people)

(defun cube-org-people-refresh ()
  "Refresh the people cache asynchronously."
  (cube--call-json-async
   '("people")
   (lambda (json) (setq cube-org--people (cube-get json 'people)))
   (lambda (code err) (cube-log "people refresh failed (%s): %s" code err))))

(defun cube-org--person (slug-or-name &optional people)
  "Return the person alist whose slug or name is SLUG-OR-NAME in PEOPLE."
  (let ((key (downcase (string-trim slug-or-name))))
    (seq-find (lambda (p)
                (or (equal (downcase (cube--string (cube-get p 'slug))) key)
                    (equal (downcase (cube--string (cube-get p 'name))) key)))
              (or people (cube-org-people)))))

(defun cube-org--person-file (person)
  "Return the org file name of PERSON (alist), on the host in remote mode.
Falls back to <first name of the slug>.org in `cube-org-directory'."
  (let ((file (cube-get person 'org_file)))
    (cube-org-file
     (if (and file (not (string-empty-p file)))
         file
       (format "%s.org" (car (split-string (cube--string (cube-get person 'slug)) "-")))))))

(defun cube-org--read-person (prompt)
  "Read a person with PROMPT and return the slug."
  (let* ((people (cube-org-people))
         (table (mapcar (lambda (p)
                          (cons (format "%s (%s)" (cube-get p 'name) (cube-get p 'slug))
                                (cube-get p 'slug)))
                        people))
         (choice (completing-read prompt table nil nil)))
    (or (cdr (assoc choice table))
        (and (cube-org--person choice people)
             (cube-get (cube-org--person choice people) 'slug))
        choice)))

(defun cube-org-open-person (slug)
  "Open the org file of the person SLUG."
  (interactive (list (cube-org--read-person "Person: ")))
  (let ((person (or (cube-org--person slug)
                    (list (cons 'slug slug)))))
    (find-file (cube-org--person-file person))))

;;;; Cube org command arguments and write gate

(defun cube-org--write-flag (flag)
  "Return FLAG, defaulting to `--dry-run'."
  (or flag "--dry-run"))

(defun cube-org--append-args (target heading date &optional items body flag)
  "Return `cube org append' ARGS for TARGET, HEADING and DATE.
ITEMS is a list of item strings, BODY is a body file or `-', and FLAG
is `--dry-run' or `--apply'."
  (append (list "org" "append" target "--heading" heading)
          (when date (list "--date" date))
          (apply #'append (mapcar (lambda (item) (list "--item" item)) items))
          (when body (list "--body" body))
          (list (cube-org--write-flag flag))))

(defun cube-org--todo-args (file heading item done &optional flag)
  "Return `cube org todo' ARGS for FILE, HEADING, ITEM and DONE."
  (append (list "org" "todo" file "--heading-match" heading "--item" item)
          (when done (list "--done"))
          (list (cube-org--write-flag flag))))

(defun cube-org--property-args (file heading property value &optional flag)
  "Return `cube org property' ARGS setting PROPERTY to VALUE."
  (list "org" "property" file "--heading-match" heading
        "--set" (format "%s=%s" property value) (cube-org--write-flag flag)))

(defun cube-org--status-args (person)
  "Return read-only `cube org status' ARGS for PERSON."
  (list "org" "status" "--person" person))

(defun cube-org--show-diff (label diff)
  "Show LABEL and DIFF in the standard org diff buffer."
  (with-current-buffer (get-buffer-create "*cube-org-diff*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert label "\n\n" (or diff "(no changes reported)\n"))
      (goto-char (point-min)))
    (diff-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-org--backend-path (file)
  "Return FILE in the backend's path namespace."
  (if-let* ((remote (file-remote-p file)))
      (string-remove-prefix remote file)
    file))

(defun cube-org--write (args label fallback &optional callback)
  "Dry-run org ARGS, show LABEL's diff, and apply after confirmation.
FALLBACK is called only for a local backend failure.  CALLBACK is called
after a successful apply."
  (let* ((base (seq-remove (lambda (arg) (member arg '("--dry-run" "--apply"))) args))
         (dry (append base '("--dry-run"))))
    (cube--call-json-async
     dry
     (lambda (json)
       (cube-org--show-diff label (cube-get json 'diff))
       (when (or (not cube-org-confirm-writes)
                 (y-or-n-p (format "Apply org change for %s? " label)))
         (cube--call-json-async
          (append base '("--apply"))
          (lambda (result)
            (message "cube: org change applied for %s" label)
            (when callback (funcall callback result)))
          (lambda (code err)
            (message "cube: org apply failed (%s): %s" code err)))))
     (lambda (code err)
       (if (and (null cube-remote-host) fallback)
           (progn
             (message "cube: backend unavailable; using local direct-buffer fallback")
             (when (or (not cube-org-confirm-writes)
                       (y-or-n-p (format "Use local direct-buffer fallback for %s? " label)))
               (funcall fallback)))
         (message "cube: org %s dry-run failed (%s): %s" label code err))))))

;;;; Dated headings

(defconst cube-org-months
  '(("january" . 1) ("february" . 2) ("march" . 3) ("april" . 4) ("may" . 5)
    ("june" . 6) ("july" . 7) ("august" . 8) ("september" . 9) ("october" . 10)
    ("november" . 11) ("december" . 12))
  "Month names and numbers.")

(defconst cube-org-month-regexp
  (concat "\\(?:"
          (mapconcat (lambda (m)
                       (let ((name (capitalize (car m))))
                         (format "%s\\|%s" name (substring name 0 3))))
                     cube-org-months "\\|")
          "\\|Sept\\)")
  "Regexp matching a full or abbreviated month name.")

(defconst cube-org-date-heading-regexp
  (concat "^\\(\\*+\\)[ \t]+\\(?:.*?[ \t]\\)?\\([0-9]\\{1,2\\}\\)\\(?:st\\|nd\\|rd\\|th\\)?[ \t]+\\("
          cube-org-month-regexp
          "\\)\\.?\\(?:[ \t]*,?[ \t]*\\([0-9]\\{4\\}\\)\\)?\\(?:[^0-9a-z\n]\\|$\\)")
  "Regexp matching a heading that carries a date like \"27 January 2025\".
Groups: 1 stars, 2 day, 3 month name, 4 year (may be missing).")

(defun cube-org--month-number (name)
  "Return the month number for NAME (full, three letter or Sept), or nil."
  (let ((key (downcase name)))
    (cdr (seq-find (lambda (m) (string-prefix-p (substring key 0 (min 3 (length key)))
                                                (car m)))
                   cube-org-months))))

(defun cube-org--heading-date (line)
  "Parse the dated heading LINE.
Return (LEVEL DAY MONTH YEAR) with YEAR nil when absent, or nil."
  (when (string-match cube-org-date-heading-regexp line)
    (list (length (match-string 1 line))
          (string-to-number (match-string 2 line))
          (cube-org--month-number (match-string 3 line))
          (and (match-string 4 line) (string-to-number (match-string 4 line))))))

(defun cube-org--date-key (date)
  "Return a sortable number for DATE (LEVEL DAY MONTH YEAR), or nil without a year."
  (pcase-let ((`(,_ ,day ,month ,year) date))
    (and year month (+ (* year 10000) (* month 100) day))))

(defun cube-org--dated-headings ()
  "Return (POS LEVEL DAY MONTH YEAR) for every dated heading in the buffer."
  (save-excursion
    (goto-char (point-min))
    (let ((found nil))
      (while (re-search-forward cube-org-date-heading-regexp nil t)
        (let* ((start (match-beginning 0))
               (line (buffer-substring-no-properties
                      start (save-excursion (goto-char start) (line-end-position)))))
          (when-let* ((date (cube-org--heading-date line)))
            (push (cons start date) found))
          (goto-char start)
          (forward-line 1)))
      (nreverse found))))

(defun cube-org--subtree-end (pos)
  "Return the position after the subtree of the heading at POS."
  (save-excursion
    (goto-char pos)
    (let ((level (progn (looking-at "\\*+") (length (match-string 0)))))
      (forward-line 1)
      (if (re-search-forward (format "^\\*\\{1,%d\\}[ \t]" level) nil t)
          (line-beginning-position)
        (point-max)))))

(defun cube-org--note-level-headings (dated)
  "Return the entries of DATED at the level that holds the meeting notes.
That is the level with the most dated headings; ties go to the deeper
level, so a single dated todo heading at the top does not win."
  (let ((counts nil))
    (dolist (d dated)
      (let ((level (cadr d)))
        (setf (alist-get level counts 0) (1+ (alist-get level counts 0)))))
    (let ((best (car (sort counts (lambda (a b)
                                    (or (> (cdr a) (cdr b))
                                        (and (= (cdr a) (cdr b)) (> (car a) (car b)))))))))
      (seq-filter (lambda (d) (= (cadr d) (car best))) dated))))

(defun cube-org--insert-position ()
  "Return (POS . LEVEL) where a new dated heading belongs in this buffer.
Dated headings are kept newest first: the new one goes before the first
dated heading at the level the notes use (see
`cube-org--note-level-headings').  When those headings are in ascending
order (oldest first) it goes after the last one instead.  Without dated
headings the position is right after a heading called Notes or Meetings
\(one level deeper), else the end of the buffer at level 2."
  (let ((dated (cube-org--dated-headings)))
    (cond
     ((null dated)
      (save-excursion
        (goto-char (point-min))
        (if (re-search-forward "^\\(\\*+\\)[ \t]+\\(Notes\\|Meetings\\|Meeting notes\\)\\b" nil t)
            (let ((level (length (match-string 1))))
              (forward-line 1)
              (cons (point) (1+ level)))
          (cons (point-max) 2))))
     (t
      (let* ((notes (cube-org--note-level-headings dated))
             (first (car notes))
             (second (cadr notes))
             (k1 (cube-org--date-key (cdr first)))
             (k2 (and second (cube-org--date-key (cdr second))))
             (ascending (and k1 k2 (< k1 k2))))
        (if ascending
            (let ((last (car (last notes))))
              (cons (cube-org--subtree-end (car last)) (cadr last)))
          (cons (car first) (cadr first))))))))

(defun cube-org--today-title (&optional time)
  "Return the heading text for a meeting at TIME (default now)."
  (format-time-string cube-org-meeting-heading-format time))

(defun cube-org--find-heading (title)
  "Return the position of the heading whose text ends with TITLE, or nil."
  (save-excursion
    (goto-char (point-min))
    (let ((re (concat "^\\*+[ \t]+\\(?:.*[ \t]\\)?" (regexp-quote title) "[ \t]*$")))
      (and (re-search-forward re nil t) (line-beginning-position)))))

(defun cube-org--insert-heading-at (pos level title)
  "Insert a heading TITLE of LEVEL at POS and return the position after it.
Keeps a blank line before the heading and leaves point after \"- \" on
the following line ready for the first item."
  (goto-char pos)
  (unless (bolp) (insert "\n"))
  (when (and (> (point) (point-min))
             (not (save-excursion (forward-line -1) (looking-at-p "[ \t]*$"))))
    (insert "\n"))
  (let ((start (point)))
    (insert (make-string level ?*) " " title "\n- \n")
    (when (and (< (point) (point-max))
               (not (looking-at-p "[ \t]*$")))
      (insert "\n"))
    (goto-char start)
    (forward-line 1)
    (end-of-line)
    (point)))

(defun cube-org--ensure-today-heading (&optional time)
  "Make sure the current buffer has a heading for TIME (default today).
Return (POS . LEVEL) of that heading."
  (let* ((title (cube-org--today-title time))
         (existing (cube-org--find-heading title)))
    (if existing
        (cons existing (save-excursion (goto-char existing) (looking-at "\\*+")
                                       (length (match-string 0))))
      (let ((where (cube-org--insert-position)))
        (cube-org--insert-heading-at (car where) (cdr where) title)
        (cons (cube-org--find-heading title) (cdr where))))))

(defun cube-org--meeting-note-direct (slug)
  "Insert a dated meeting heading directly in the org file of SLUG.
The heading goes where the file keeps its newest note (see
`cube-org--insert-position'); point ends on the first item line."
  (cube-org-open-person slug)
  (let* ((title (cube-org--today-title))
         (existing (cube-org--find-heading title)))
    (if existing
        (progn (goto-char (cube-org--subtree-end existing))
               (skip-chars-backward " \t\n")
               (insert "\n- "))
      (let ((where (cube-org--insert-position)))
        (cube-org--insert-heading-at (car where) (cdr where) title)))
    (when (fboundp 'org-fold-show-context) (org-fold-show-context))))

(defun cube-org--org-target-for-person (slug)
  "Return the backend path for SLUG's org file."
  (or (cube-get (cube-org--person slug) 'org_file) slug))

(defun cube-org--current-item ()
  "Return (HEADING ITEM DONE) for the org item at point, or nil."
  (when (derived-mode-p 'org-mode)
    (save-excursion
      (beginning-of-line)
      (when (looking-at "^[ \t]*-[ \t]*\\(\\[.\\][ \t]*\\)?\\(.*?\\)[ \t]*$")
        (list (org-get-heading t t t t)
              (string-trim (match-string 2))
              (equal (match-string 1) "[X] "))))))

(defun cube-org--current-edit-context ()
  "Return (FILE HEADING ITEM DONE) from the current org buffer."
  (unless (and (derived-mode-p 'org-mode) buffer-file-name)
    (user-error "cube: put point in an org file"))
  (let* ((item (cube-org--current-item))
         (heading (or (and item (car item)) (org-get-heading t t t t)))
         (item-text (or (and item (cadr item)) (read-string "Todo item: "))))
    (when (string-empty-p item-text) (user-error "cube: todo item is empty"))
    (list (cube-org--backend-path buffer-file-name) heading item-text
          (and item (nth 2 item)))))

(defun cube-org--direct-find-item (heading item)
  "Move to ITEM under HEADING in the current org buffer, or signal."
  (cube-org--goto-heading heading)
  (unless (re-search-forward
           (concat "^[ \\t]*-[ \\t]*\\(?:\\[.\\][ \\t]*\\)?"
                   (regexp-quote item) "[ \\t]*$")
           (cube-org--subtree-end (line-beginning-position)) t)
    (user-error "cube: item %S not found" item))
  (beginning-of-line))

(defun cube-org--direct-todo (file heading item done)
  "Toggle ITEM directly in FILE under HEADING as a fallback."
  (with-current-buffer (find-file-noselect file)
    (save-excursion
      (cube-org--direct-find-item heading item)
      (let ((line (buffer-substring-no-properties (line-beginning-position)
                                                 (line-end-position))))
        (if (string-match "\\[.\\]" line)
            (progn
              (delete-region (line-beginning-position) (line-end-position))
              (insert (replace-regexp-in-string "\\[.\\]"
                                                (if done "[X]" "[ ]") line)))
          (end-of-line)
          (insert (if done " [X]" " [ ]"))))
      (save-buffer))))

(defun cube-org--direct-property (file heading property value)
  "Set PROPERTY to VALUE directly in FILE under HEADING as a fallback."
  (with-current-buffer (find-file-noselect file)
    (save-excursion
      (cube-org--goto-heading heading)
      (org-set-property property value))
    (save-buffer)))

(defun cube-org-meeting-note (slug)
  "Append today's meeting heading for SLUG through the backend."
  (interactive (list (cube-org--read-person "Meeting with: ")))
  (let* ((person (cube-org--person slug))
         (target (or (cube-get person 'org_file) slug))
         (title (cube-org--today-title))
         (date (format-time-string "%F")))
    (cube-org--write
     (cube-org--append-args target title date)
     (format "meeting note for %s" slug)
     (lambda () (cube-org--meeting-note-direct slug))
     (lambda (_result) (cube-org-open-person slug)))))

(defun cube-org-edit-toggle-todo ()
  "Toggle the org todo item at point through the backend."
  (interactive)
  (pcase-let ((`(,file ,heading ,item ,done) (cube-org--current-edit-context)))
    (cube-org--write
     (cube-org--todo-args file heading item (not done))
     (format "todo %s" item)
     (lambda () (cube-org--direct-todo file heading item (not done))))))

(defun cube-org-edit-set-property ()
  "Set an org property at point through the backend."
  (interactive)
  (unless (and (derived-mode-p 'org-mode) buffer-file-name)
    (user-error "cube: put point in an org file"))
  (let ((file (cube-org--backend-path buffer-file-name))
        (heading (org-get-heading t t t t))
        (property (read-string "Property: "))
        (value nil))
    (setq value (read-string (format "%s value: " property)))
    (when (string-empty-p property) (user-error "cube: property name is empty"))
    (cube-org--write
     (cube-org--property-args file heading property value)
     (format "property %s" property)
     (lambda () (cube-org--direct-property file heading property value)))))

(defun cube-org--show-status (slug json)
  "Show the org STATUS JSON for SLUG."
  (with-current-buffer (get-buffer-create (format "*cube-org-status: %s*" slug))
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (format "Org status: %s\n\n" slug))
      (dolist (key '(file last_dated_heading open_items milestones))
        (when-let* ((value (cube-get json key)))
          (insert (format "%s: %s\n" (symbol-name key) (cube--string value)))))
      (unless (or (cube-get json 'file) (cube-get json 'last_dated_heading)
                  (cube-get json 'open_items) (cube-get json 'milestones))
        (insert (pp-to-string json)))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-org-edit-status ()
  "Show backend org status for a selected person."
  (interactive)
  (let ((slug (cube-org--read-person "Person: ")))
    (cube--call-json-async
     (cube-org--status-args slug)
     (lambda (json) (cube-org--show-status slug json))
     (lambda (code err) (message "cube: org status failed (%s): %s" code err)))))

(transient-define-prefix cube-org-menu ()
  "Edit org files through lock-aware cube operations."
  ["Org edits"
   ("m" "Meeting note" cube-org-meeting-note)
   ("t" "Toggle todo" cube-org-edit-toggle-todo)
   ("s" "Set property" cube-org-edit-set-property)
   ("S" "Status" cube-org-edit-status)
   ("q" "Quit" transient-quit-one)])

(defun cube-org-edit ()
  "Open the org editing transient."
  (interactive)
  (transient-setup 'cube-org-menu))

;;;; Markdown to org (pure)

(defun cube-org--md-inline->org (line)
  "Convert inline markdown in LINE to org markup."
  (let ((s line))
    (setq s (replace-regexp-in-string "\\[\\([^]]+\\)\\](\\([^)]+\\))" "[[\\2][\\1]]" s))
    (setq s (replace-regexp-in-string "\\*\\*\\([^*\n]+\\)\\*\\*" "*\\1*" s))
    (setq s (replace-regexp-in-string "__\\([^_\n]+\\)__" "*\\1*" s))
    (setq s (replace-regexp-in-string "`\\([^`\n]+\\)`" "=\\1=" s))
    (setq s (replace-regexp-in-string "\\(\\`\\|[ (]\\)_\\([^_\n]+\\)_\\([ ).,;:]\\|\\'\\)"
                                      "\\1/\\2/\\3" s))
    s))

(defun cube-org-md->org (markdown &optional base-level)
  "Convert MARKDOWN text to org text.
Headings start at BASE-LEVEL (default 1); fenced code becomes source
blocks; emphasis, code spans and links are translated; list bullets
become dashes.  Return the org text."
  (let ((base (or base-level 1))
        (in-fence nil)
        (out nil))
    (dolist (line (split-string (or markdown "") "\n"))
      (cond
       ((string-match "\\`[ \t]*```[ \t]*\\([A-Za-z0-9_+-]*\\)" line)
        (if in-fence
            (progn (setq in-fence nil) (push "#+end_src" out))
          (setq in-fence t)
          (let ((lang (match-string 1 line)))
            (push (if (string-empty-p lang) "#+begin_src" (concat "#+begin_src " lang)) out))))
       (in-fence (push line out))
       ((string-match "\\`\\(#+\\)[ \t]+\\(.*?\\)[ \t]*#*[ \t]*\\'" line)
        (push (concat (make-string (+ base (1- (length (match-string 1 line)))) ?*)
                      " " (cube-org--md-inline->org (match-string 2 line)))
              out))
       ((string-match "\\`\\([ \t]*\\)[*+][ \t]+\\(.*\\)\\'" line)
        (push (concat (match-string 1 line) "- " (cube-org--md-inline->org (match-string 2 line)))
              out))
       ((string-match "\\`[ \t]*\\(?:---+\\|\\*\\*\\*+\\)[ \t]*\\'" line)
        (push "-----" out))
       ((string-match "\\`>[ \t]?\\(.*\\)\\'" line)
        (push (cube-org--md-inline->org (match-string 1 line)) out))
       ((string-prefix-p "*" line)
        (push (concat " " (cube-org--md-inline->org line)) out))
       (t (push (cube-org--md-inline->org line) out))))
    (string-join (nreverse out) "\n")))

(defun cube-org--min-heading-level (org-text)
  "Return the smallest heading level in ORG-TEXT, or nil."
  (let ((min nil))
    (dolist (line (split-string org-text "\n"))
      (when (string-match "\\`\\(\\*+\\)[ \t]" line)
        (let ((n (length (match-string 1 line))))
          (when (or (null min) (< n min)) (setq min n)))))
    min))

(defun cube-org--demote (org-text level)
  "Return ORG-TEXT with headings shifted so the top level is LEVEL."
  (let ((min (cube-org--min-heading-level org-text)))
    (if (or (null min) (= min level))
        org-text
      (let ((delta (- level min)))
        (mapconcat (lambda (line)
                     (if (string-match "\\`\\(\\*+\\)\\([ \t]\\)" line)
                         (concat (make-string (max 1 (+ (length (match-string 1 line)) delta)) ?*)
                                 (substring line (match-end 1)))
                       line))
                   (split-string org-text "\n") "\n")))))

(defun cube-org--agent-notes-block (run-id org-text level)
  "Return the `Agent notes' subtree at LEVEL for RUN-ID wrapping ORG-TEXT.
ORG-TEXT headings are demoted below the block heading."
  (concat (make-string level ?*) " Agent notes :draft:\n"
          ":PROPERTIES:\n:RUN: " (or run-id "unknown") "\n:END:\n"
          (string-trim-right (cube-org--demote org-text (1+ level)))
          "\n"))

;;;; Pulling agent notes

(defun cube-org--fetch-run-notes (run-id notes-file callback)
  "Fetch the notes of RUN-ID and call CALLBACK with the markdown text.
Tries `cube runs show RUN-ID --json' (key `notes') and falls back to
reading NOTES-FILE from the host."
  (let ((fallback (lambda ()
                    (funcall callback
                             (or (and notes-file (cube-host-file-contents notes-file))
                                 (user-error "cube: no notes for run %s" run-id))))))
    (if (null run-id)
        (funcall fallback)
      (cube--call-json-async
       (list "runs" "show" run-id)
       (lambda (json)
         (let ((notes (cube-get json 'notes)))
           (if (and notes (not (string-empty-p notes)))
               (funcall callback notes)
             (funcall fallback))))
       (lambda (_code _err) (funcall fallback))))))

(defun cube-org--insert-agent-notes (run-id markdown)
  "Insert MARKDOWN from RUN-ID as an Agent notes block under today's heading."
  (let* ((today (cube-org--ensure-today-heading))
         (level (cdr today))
         (end (cube-org--subtree-end (car today)))
         (block (cube-org--agent-notes-block
                 run-id (cube-org-md->org markdown (+ level 2)) (1+ level))))
    (goto-char end)
    (unless (bolp) (insert "\n"))
    (let ((start (point)))
      (insert block)
      (unless (or (eobp) (looking-at-p "\n")) (insert "\n"))
      (goto-char start))
    (when (fboundp 'org-fold-show-context) (org-fold-show-context))))

(defun cube-org-pull-meeting-notes (slug)
  "Pull the latest advisor notes for SLUG into their org file.
Reads runs/<id>/notes.md of the student's `advisor_run' (through `cube
runs show' or the host file), converts it to org and inserts it as
`** Agent notes :draft:' with a :RUN: property under today's heading."
  (interactive (list (cube-org--read-person "Pull agent notes for: ")))
  (message "cube: fetching dossier of %s..." slug)
  (cube--call-json-async
   (list "student" slug)
   (lambda (json)
     (let ((run-id (cube-get json 'advisor_run 'run_id))
           (notes-file (cube-get json 'advisor_run 'notes_file)))
       (if (not (or run-id notes-file))
           (message "cube: %s has no advisor run yet" slug)
         (cube-org--fetch-run-notes
          run-id notes-file
          (lambda (markdown)
            (cube-org-open-person slug)
            (cube-org--insert-agent-notes run-id markdown)
            (message "cube: inserted agent notes from %s (marked :draft:)" run-id))))))
   (lambda (code err) (message "cube: student %s failed (%s): %s" slug code err))))

(defalias 'cube-org-pull-notes #'cube-org-pull-meeting-notes)

;;;; Papers

(defun cube-org--todo-keywords (text)
  "Return the TODO keywords declared by #+TODO lines in TEXT (without the bar)."
  (let ((keywords nil))
    (dolist (line (split-string text "\n"))
      (when (string-match "\\`#\\+\\(?:TODO\\|SEQ_TODO\\|TYP_TODO\\):[ \t]*\\(.*\\)\\'" line)
        (dolist (word (split-string (match-string 1 line) "[ \t]+" t))
          (unless (string= word "|")
            (push (replace-regexp-in-string "(.*)\\'" "" word) keywords)))))
    (nreverse keywords)))

(defun cube-org--paper-states (text &optional keywords)
  "Return (TITLE . KEYWORD) for every heading of level 2 or deeper in TEXT.
KEYWORD is nil when the heading carries none of KEYWORDS (default: the
keywords declared in TEXT)."
  (let ((keywords (or keywords (cube-org--todo-keywords text)))
        (states nil))
    (dolist (line (split-string text "\n"))
      (when (string-match "\\`\\*\\*+[ \t]+\\(.*?\\)[ \t]*\\(?::[[:alnum:]_@#%:]+:\\)?[ \t]*\\'" line)
        (let* ((rest (match-string 1 line))
               (words (split-string rest "[ \t]+" t))
               (kw (and words (member (car words) keywords) (car words)))
               (title (string-trim (if kw (substring rest (length kw)) rest))))
          (setq title (replace-regexp-in-string "\\`\\[#[A-Z0-9]\\][ \t]*" "" title))
          (push (cons title kw) states))))
    (nreverse states)))

(defun cube-org--heading-title (org-heading)
  "Return the heading text of ORG-HEADING like \"papers.org::*Genome-scale PFP\"."
  (when org-heading
    (let ((s org-heading))
      (when (string-match "::\\(.*\\)\\'" s) (setq s (match-string 1 s)))
      (string-trim (replace-regexp-in-string "\\`\\*+[ \t]*" "" s)))))

(defun cube-org--match-state (title states)
  "Return the (TITLE . KEYWORD) entry of STATES matching TITLE, or nil."
  (when (and title (not (string-empty-p title)))
    (let ((key (downcase title)))
      (or (seq-find (lambda (s) (equal (downcase (car s)) key)) states)
          (seq-find (lambda (s)
                      (let ((h (downcase (car s))))
                        (or (string-prefix-p key h) (string-prefix-p h key))))
                    states)))))

(defun cube-org--papers-diff (papers states)
  "Compare PAPERS (from `cube papers') with STATES (from papers.org).
Return a list of plists (:id :title :heading :backend :org :found) for
papers whose backend state differs from the org keyword, or whose
heading was not found in the file."
  (let ((diff nil))
    (dolist (paper papers)
      (let* ((heading (or (cube-org--heading-title (cube-get paper 'org_heading))
                          (cube-get paper 'title)))
             (backend (cube--string (cube-get paper 'state)))
             (match (or (cube-org--match-state heading states)
                        (cube-org--match-state (cube-get paper 'title) states)))
             (org-state (cdr match)))
        (when (or (null match) (not (equal backend (cube--string org-state))))
          (push (list :id (cube-get paper 'id) :title (cube-get paper 'title)
                      :heading (if match (car match) heading)
                      :backend backend :org org-state :found (and match t))
                diff))))
    (nreverse diff)))

(defun cube-org--goto-heading (title)
  "Move to the heading TITLE (any keyword or priority allowed) or signal."
  (goto-char (point-min))
  (let ((re (concat "^\\*+[ \t]+\\(?:[A-Z_]+[ \t]+\\)?\\(?:\\[#[A-Z0-9]\\][ \t]+\\)?"
                    (regexp-quote title))))
    (unless (re-search-forward re nil t)
      (user-error "cube: heading %S not found" title))
    (beginning-of-line)
    (point)))

(defun cube-org--apply-paper-state (file title state)
  "Set the TODO keyword of heading TITLE in FILE to STATE with `org-todo'.
The file's own #+TODO sequence stays in charge of what is a valid state."
  (with-current-buffer (find-file-noselect file)
    (save-excursion
      (cube-org--goto-heading title)
      (org-todo state))
    (save-buffer)))

(defvar cube-papers-sync-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "a") #'cube-papers-sync-apply)
    (define-key map (kbd "A") #'cube-papers-sync-apply-all)
    (define-key map (kbd "RET") #'cube-papers-sync-open)
    map)
  "Keymap of `cube-papers-sync-mode'.")

(define-derived-mode cube-papers-sync-mode tabulated-list-mode "cube-papers-sync"
  "Differences between `cube papers' and papers.org."
  (setq tabulated-list-format
        [("Id" 9 t) ("Backend" 16 t) ("Org" 16 t) ("Heading" 0 t)])
  (setq tabulated-list-padding 1)
  (add-hook 'tabulated-list-revert-hook #'cube-org-papers-sync nil t)
  (tabulated-list-init-header))

(defun cube-org--papers-sync-entry (d)
  "Return the tabulated-list entry for diff plist D."
  (list d (vector (cube--string (plist-get d :id))
                  (cube--string (plist-get d :backend))
                  (if (plist-get d :found) (or (plist-get d :org) "(none)") "(heading missing)")
                  (cube--string (plist-get d :heading)))))

(defun cube-org-papers-sync ()
  "Show paper states that differ between `cube papers' and papers.org."
  (interactive)
  (cube--call-json-async
   '("papers")
   (lambda (json)
     (let* ((file (cube-org-file cube-org-papers-file))
            (text (or (cube-org--file-text file)
                      (user-error "cube: cannot read %s" file)))
            (diff (cube-org--papers-diff (cube-get json 'papers)
                                         (cube-org--paper-states text))))
       (with-current-buffer (get-buffer-create "*cube-papers-sync*")
         (unless (derived-mode-p 'cube-papers-sync-mode) (cube-papers-sync-mode))
         (setq tabulated-list-entries (mapcar #'cube-org--papers-sync-entry diff))
         (tabulated-list-print t)
         (pop-to-buffer (current-buffer)))
       (message "cube: %d paper state difference(s)" (length diff))))
   (lambda (code err) (message "cube: papers failed (%s): %s" code err))))

(defun cube-papers-sync-apply ()
  "Set the org keyword of the paper at point to the backend state."
  (interactive)
  (let ((d (or (tabulated-list-get-id) (user-error "cube: nothing at point"))))
    (unless (plist-get d :found)
      (user-error "cube: heading %S is not in papers.org" (plist-get d :heading)))
    (when (y-or-n-p (format "Set %S to %s? " (plist-get d :heading) (plist-get d :backend)))
      (cube-org--apply-paper-state (cube-org-file cube-org-papers-file)
                                   (plist-get d :heading) (plist-get d :backend))
      (cube-org-papers-sync))))

(defun cube-papers-sync-apply-all ()
  "Apply every backend state to papers.org."
  (interactive)
  (let ((entries (seq-filter (lambda (e) (plist-get (car e) :found)) tabulated-list-entries)))
    (when (y-or-n-p (format "Apply %d state change(s) to papers.org? " (length entries)))
      (dolist (e entries)
        (cube-org--apply-paper-state (cube-org-file cube-org-papers-file)
                                     (plist-get (car e) :heading) (plist-get (car e) :backend)))
      (cube-org-papers-sync))))

(defun cube-papers-sync-open ()
  "Open papers.org at the heading at point."
  (interactive)
  (let ((d (or (tabulated-list-get-id) (user-error "cube: nothing at point"))))
    (find-file (cube-org-file cube-org-papers-file))
    (ignore-errors (cube-org--goto-heading (plist-get d :heading)))))

(defun cube-org-open-paper (paper)
  "Open PAPER (alist from `cube papers'): its org heading, else its directory."
  (let ((heading (cube-org--heading-title (cube-get paper 'org_heading)))
        (path (cube-get paper 'path)))
    (cond
     (heading
      (find-file (cube-org-file cube-org-papers-file))
      (condition-case nil
          (progn (cube-org--goto-heading heading)
                 (when (fboundp 'org-fold-show-context) (org-fold-show-context)))
        (user-error (message "cube: heading %S not found in papers.org" heading))))
     (path (dired (cube-host-file-name path)))
     (t (user-error "cube: paper has neither org heading nor path")))))

(defvar cube-papers-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'cube-papers-open)
    (define-key map (kbd "d") #'cube-papers-dired)
    (define-key map (kbd "s") #'cube-org-papers-sync)
    (define-key map (kbd "b") #'cube-papers-bead)
    map)
  "Keymap of `cube-papers-mode'.")

(define-derived-mode cube-papers-mode tabulated-list-mode "cube-papers"
  "Papers tracked by the backend."
  (setq tabulated-list-format
        [("Id" 9 t) ("State" 16 t) ("Venue" 16 t) ("Deadline" 11 t) ("Lead" 10 t)
         ("Title" 0 t)])
  (setq tabulated-list-padding 1)
  (add-hook 'tabulated-list-revert-hook #'cube-papers--refresh nil t)
  (tabulated-list-init-header))

(defun cube-papers--entry (paper)
  "Return the tabulated-list entry for PAPER."
  (list paper (vector (cube--string (cube-get paper 'id))
                      (cube--string (cube-get paper 'state))
                      (cube--string (cube-get paper 'venue))
                      (cube--string (cube-get paper 'deadline))
                      (cube--string (cube-get paper 'lead))
                      (cube--string (cube-get paper 'title)))))

(defun cube-papers--refresh ()
  "Refetch the papers into *cube-papers*."
  (cube--call-json-async
   '("papers")
   (lambda (json)
     (with-current-buffer (get-buffer-create "*cube-papers*")
       (unless (derived-mode-p 'cube-papers-mode) (cube-papers-mode))
       (setq tabulated-list-entries (mapcar #'cube-papers--entry (cube-get json 'papers)))
       (tabulated-list-print t)))
   (lambda (code err) (message "cube: papers failed (%s): %s" code err))))

(defun cube-papers ()
  "List the papers in *cube-papers*."
  (interactive)
  (with-current-buffer (get-buffer-create "*cube-papers*")
    (unless (derived-mode-p 'cube-papers-mode) (cube-papers-mode))
    (pop-to-buffer (current-buffer)))
  (cube-papers--refresh))

(defun cube-papers-open ()
  "Open the paper at point (org heading, else directory)."
  (interactive)
  (cube-org-open-paper (or (tabulated-list-get-id) (user-error "cube: no paper at point"))))

(defun cube-papers-dired ()
  "Open the directory of the paper at point."
  (interactive)
  (let ((paper (or (tabulated-list-get-id) (user-error "cube: no paper at point"))))
    (if-let* ((path (cube-get paper 'path)))
        (dired (cube-host-file-name path))
      (user-error "cube: paper has no path"))))

(defun cube-papers-bead ()
  "Show the bead of the paper at point."
  (interactive)
  (let ((paper (or (tabulated-list-get-id) (user-error "cube: no paper at point"))))
    (if-let* ((id (or (cube-get paper 'review_bead) (cube-get paper 'id))))
        (cube-beads-show id)
      (user-error "cube: paper has no bead"))))

;;;; Student context

(defun cube-org--student-context-org (json &optional person)
  "Render the `cube student' payload JSON as an org dossier."
  (let ((name (cube--string (or (cube-get json 'name) (cube-get json 'slug))))
        (program (cube-get json 'program)))
    (with-temp-buffer
      (insert (format "#+title: %s\n\n" name))
      (insert (format "* %s (%s)\n" name (cube--string (cube-get json 'role))))
      (when program
        (insert (format "- Program: %s, %s to %s\n"
                        (if (consp program)
                            (format "[[bead:%s][%s]]" (cube-get program 'bead)
                                    (cube--string (cube-get program 'title)))
                          (cube--string program))
                        (cube--string (and (consp program) (cube-get program 'started)))
                        (cube--string (and (consp program) (cube-get program 'expected_end))))))
      (when-let* ((file (cube-get json 'org_file)))
        (insert (format "- Notes: [[file:%s]]\n" (cube-org-file file))))
      (insert "\n** Milestones\n")
      (dolist (m (cube-get json 'milestones))
        (insert (format "- %s %s, due %s%s%s\n"
                        (if (equal (cube-get m 'state) "done") "[X]" "[ ]")
                        (cube--string (cube-get m 'name))
                        (cube--string (cube-get m 'due))
                        (if-let* ((days (cube-get m 'days))) (format " (%s days)" days) "")
                        (if-let* ((bead (cube-get m 'bead))) (format " [[bead:%s]]" bead) ""))))
      (when-let* ((ev (cube-get json 'evidence)))
        (insert "\n** Evidence\n")
        (insert (format "- Commits (7 days): %s\n" (cube--string (cube-get ev 'commits_7d))))
        (when-let* ((repos (cube-get ev 'repos)))
          (insert (format "- Repos: %s\n" (string-join (mapcar #'cube--string repos) ", "))))
        (dolist (d (cube-get ev 'drafts))
          (insert (format "- Draft %s, modified %s\n" (cube--string (cube-get d 'path))
                          (cube--string (cube-get d 'modified)))))
        (when-let* ((last (cube-get ev 'org_notes_last)))
          (insert (format "- Last org note: %s\n" last))))
      (when-let* ((agenda (cube-get json 'agenda_draft)))
        (insert "\n** Agenda draft :draft:\n")
        (dolist (item agenda) (insert (format "- %s\n" item))))
      (when person
        (when-let* ((goals (cube-get person 'goals)))
          (insert "\n** Goals\n")
          (dolist (goal goals) (insert (format "- %s\n" (cube--string goal)))))
        (insert "\n** Owed items\n")
        (if-let* ((owed (cube-get person 'owed)))
            (dolist (item owed)
              (insert (format "- %s%s%s\n"
                              (if-let* ((bead (cube-get item 'bead)))
                                  (format "[[bead:%s][%s]] " bead bead) "")
                              (cube--string (cube-get item 'title))
                              (if-let* ((due (cube-get item 'due)))
                                  (format " (due %s)" due) ""))))
          (insert "- none\n"))
        (insert "\n** Next meeting agenda\n")
        (if-let* ((next (cube-get person 'next_meeting_agenda)))
            (dolist (item next) (insert (format "- %s\n" item)))
          (insert "- none\n")))
      (when-let* ((beads (cube-get json 'beads)))
        (insert "\n** Beads\n")
        (dolist (b beads) (insert (format "- [[bead:%s]]\n" (cube--string b)))))
      (when-let* ((concerns (cube-get json 'concerns)))
        (insert "\n** Concerns\n")
        (dolist (c concerns) (insert (format "- %s\n" (cube--string c)))))
      (when-let* ((run (cube-get json 'advisor_run)))
        (insert (format "\n** Advisor run\n- %s at %s, notes %s\n"
                        (cube--string (cube-get run 'run_id))
                        (cube--string (cube-get run 'ts))
                        (cube--string (cube-get run 'notes_file)))))
      (buffer-string))))

(defun cube-org-student-context (slug)
  "Show the dossier of the student SLUG as org text in *cube-student: SLUG*."
  (interactive (list (cube-org--read-person "Student: ")))
  (message "cube: fetching dossier of %s..." slug)
  (cube--call-json-async
   (list "student" slug)
   (lambda (json)
     (with-current-buffer (get-buffer-create (format "*cube-student: %s*" slug))
       (let ((inhibit-read-only t))
         (erase-buffer)
         (insert (cube-org--student-context-org json (cube-org--person slug)))
         (goto-char (point-min)))
       (unless (derived-mode-p 'org-mode) (org-mode))
       (view-mode 1)
       (when (fboundp 'org-fold-show-all) (org-fold-show-all))
       (pop-to-buffer (current-buffer))))
   (lambda (code err) (message "cube: student %s failed (%s): %s" slug code err))))

(defun cube-org--generic-person-context (person)
  "Build a minimal dossier JSON for PERSON when cube student is unavailable."
  (list (cons 'slug (cube-get person 'slug))
        (cons 'name (cube-get person 'name))
        (cons 'role (cube-get person 'role))
        (cons 'org_file (cube-get person 'org_file))))

(defun cube-org--show-person-context (slug json person)
  "Display JSON as the existing dossier buffer for SLUG, extended by PERSON."
  (with-current-buffer (get-buffer-create (format "*cube-student: %s*" slug))
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (cube-org--student-context-org json person))
      (goto-char (point-min)))
    (unless (derived-mode-p 'org-mode) (org-mode))
    (view-mode 1)
    (when (fboundp 'org-fold-show-all) (org-fold-show-all))
    (pop-to-buffer (current-buffer))))

(defun cube-org-person-context (slug &optional person)
  "Show the existing dossier for SLUG, including owed items and agenda."
  (let ((person (or person (cube-org--person slug))))
    (message "cube: fetching dossier of %s..." slug)
    (cube--call-json-async
     (list "student" slug)
     (lambda (json) (cube-org--show-person-context slug json person))
     (lambda (_code _err)
       (cube-org--show-person-context
        slug (cube-org--generic-person-context
              (or person (list (cons 'slug slug) (cons 'name slug))))
        person)))))

(defalias 'cube-student-dossier #'cube-org-student-context)

(provide 'cube-org)
;;; cube-org.el ends here
