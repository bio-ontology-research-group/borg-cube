;;; cube-project.el --- Projects in the borg-cube cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, outlines

;;; Commentary:

;; Projects are deliberately read from the single `cube projects' payload.
;; The dashboard uses the pure row normaliser below; the project buffer adds
;; the people and ready-bead views that can be derived without inventing a
;; second backend contract.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'magit-section)
(require 'cube-core)
(require 'cube-beads)
(require 'cube-org)
(require 'cube-rolodex)

(defvar cube-fleet--cache)

(defvar cube-project--cache nil
  "Projects from the last successful `cube projects' call.")

;;;; Pure project rendering

(defun cube-project--status-glyph (status)
  "Return the display glyph for project STATUS."
  (pcase status
    ("active" "●")
    ("ending" "◐")
    ("ended" "○")
    (_ "?")))

(defun cube-project--count (project key)
  "Return PROJECT's numeric count at nested BEADS or zero."
  (let ((value (cube-get project 'beads key)))
    (if (numberp value) value 0)))

(defun cube-project--person-name (slug people)
  "Return the display name for SLUG in PEOPLE, or SLUG itself."
  (or (and slug
           (cube-get (seq-find (lambda (person)
                                 (equal (cube--string (cube-get person 'slug))
                                        (cube--string slug)))
                               people)
                    'name))
      (cube--string slug)))

(defun cube-project--last-activity-number (project)
  "Return PROJECT's last activity as a sortable number, or -1."
  (let ((stamp (cube-get project 'last_activity)))
    (if (and (stringp stamp) (not (string-empty-p stamp)))
        (condition-case nil
            (float-time (encode-time (iso8601-parse stamp)))
          (error -1))
      -1)))

(defun cube-project--sort (projects)
  "Return a copy of PROJECTS sorted by latest activity, newest first."
  (cl-stable-sort (copy-sequence projects)
                  (lambda (a b)
                    (> (cube-project--last-activity-number a)
                       (cube-project--last-activity-number b)))))

(defun cube-project--row (project &optional people now)
  "Return a dashboard item for PROJECT, using PEOPLE and NOW when given."
  (let* ((slug (cube-get project 'slug))
         (lead (cube-project--person-name (cube-get project 'lead) people))
         (last (cube-get project 'last_activity))
         (age (cube--age-string last now))
         (detail (format "lead %s  %d open/%d in progress  %d papers  %d software%s"
                         (if (string-empty-p lead) "-" lead)
                         (cube-project--count project 'open)
                         (cube-project--count project 'in_progress)
                         (or (cube-get project 'papers 'count) 0)
                         (or (cube-get project 'software 'count) 0)
                         (if (string-empty-p age) "" (concat "  " age)))))
    (list :type 'project :id (cube--string slug)
          :label (format "%s %s" (cube-project--status-glyph (cube-get project 'status))
                         (cube--string (cube-get project 'name)))
          :detail detail :data project)))

(defun cube-project--row-items (json &optional people now)
  "Return sorted dashboard rows from parsed PROJECTS JSON."
  (mapcar (lambda (project) (cube-project--row project people now))
          (cube-project--sort (cube-get json 'projects))))

(defun cube-project--bead-project-p (bead slug)
  "Return non-nil when BEAD has the project SLUG label."
  (member (concat "project:" slug) (cube-get bead 'labels)))

(defun cube-project--beads-for (slug beads)
  "Return ready BEADS belonging to project SLUG."
  (seq-filter (lambda (bead) (cube-project--bead-project-p bead slug)) beads))

(defun cube-project--bead-item (bead)
  "Return a visitable section item for normalised BEAD."
  (list :type 'bead :id (cube--string (alist-get 'id bead)) :data bead
        :label (format "  %s %s"
                       (if (equal (alist-get 'status bead) "closed") "○" "•")
                       (cube--string (alist-get 'title bead)))
        :detail (string-join
                 (delq nil (list (alist-get 'stage bead)
                                 (and (alist-get 'assignee bead)
                                      (cube--string (alist-get 'assignee bead)))
                                 (and (alist-get 'deadline bead)
                                      (concat "due " (cube--string
                                                      (alist-get 'deadline bead))))))
                 "  ")))

(defun cube-project--runner-profile (project)
  "Return PROJECT's configured runner profile, if the backend supplied one."
  (cube-get project 'runner_profile))

(defun cube-project--runner-profile-text (project)
  "Return a readable runner profile group for PROJECT."
  (let* ((profile (cube-project--runner-profile project))
         (path (or (cube-get profile 'path) (cube-get profile 'effective_cwd)))
         (runner (cube-get profile 'runner))
         (sandbox (cube-get profile 'sandbox))
         (pre (or (cube-get profile 'pre_steps) (cube-get profile 'pre))))
    (with-temp-buffer
      (insert "Runner profile\n")
      (if profile
          (progn
            (insert (format "- Path: %s\n" (or path "-")))
            (insert (format "- Runner: %s\n" (or runner "-")))
            (insert (format "- Sandbox: %s\n" (or sandbox "-")))
            (insert "- Pre-steps: "
                    (if pre (string-join (mapcar #'cube--string pre) "; ") "none")
                    "\n"))
        (insert "- none\n"))
      (buffer-string))))

(defun cube-project--session-value (session key)
  "Return KEY from raw fleet SESSION or from a local session struct."
  (if (and (fboundp 'cube-session-p) (cube-session-p session))
      (pcase key
        ('name (cube-session-name session))
        ('project (cube-session-project session))
        ('runner (cube-rolodex--kind-string (cube-session-kind session)))
        ('cwd (cube-session-cwd session))
        ('resume_id (cube-session-resume-id session))
        (_ nil))
    (pcase key
      ('name (or (cube-get session 'name) (cube-get session 'session) (cube-get session 'tmux)))
      (_ (cube-get session key)))))

(defun cube-project--adopted-sessions-for (slug sessions)
  "Return SESSIONS associated with project SLUG, preserving their order."
  (seq-filter (lambda (session)
                (equal (cube-project--session-value session 'project) slug))
              sessions))

(defun cube-project--session-item (session)
  "Return a visitable item for an adopted SESSION in a project buffer."
  (let ((name (cube--string (cube-project--session-value session 'name)))
        (runner (cube--string (or (cube-project--session-value session 'runner)
                                  (cube-get session 'kind))))
        (cwd (cube--string (cube-project--session-value session 'cwd)))
        (resume (cube-project--session-value session 'resume_id)))
    (list :type 'session :id name :data session
          :label (format "  %s%s" (if resume "↻ " "") name)
          :detail (string-join (seq-filter (lambda (value) (not (string-empty-p value)))
                                            (list runner cwd)) "  "))))

(defun cube-project--static-text (project people &optional now)
  "Return PROJECT facts that are not visitable dynamic groups."
  (let ((lead (cube-project--person-name (cube-get project 'lead) people)))
    (with-temp-buffer
      (insert (format "Project: %s (%s)\n"
                      (cube--string (cube-get project 'name))
                      (cube--string (cube-get project 'status))))
      (insert (format "Slug: %s\n" (cube--string (cube-get project 'slug))))
      (insert (format "Lead: %s\n" (if (string-empty-p lead) "-" lead)))
      (let ((age (cube--age-string (cube-get project 'last_activity) now)))
        (when (not (string-empty-p age)) (insert (format "Last activity: %s ago\n" age))))
      (insert "\nMembers\n")
      (if-let* ((members (cube-get project 'members)))
          (dolist (member members)
            (insert (format "- %s (%s)\n"
                            (cube-project--person-name member people)
                            (cube--string member))))
        (insert "- none\n"))
      (insert "\nGrants\n")
      (if-let* ((grants (cube-get project 'grants)))
          (dolist (grant grants) (insert (format "- %s\n" (cube--string grant))))
        (insert "- none\n"))
      (insert "\nTopics\n")
      (if-let* ((topics (cube-get project 'topics)))
          (dolist (topic topics) (insert (format "- %s\n" (cube--string topic))))
        (insert "- none\n"))
      (buffer-string))))

(defun cube-project--render-text (project beads people &optional now sessions)
  "Return pure text for PROJECT with BEADS, PEOPLE, and adopted SESSIONS."
  (with-temp-buffer
    (insert (cube-project--static-text project people now) "\n")
    (insert (cube-project--runner-profile-text project) "\n")
    (let ((items (mapcar #'cube-project--session-item
                         (cube-project--adopted-sessions-for (cube-get project 'slug) sessions))))
      (insert (format "Adopted sessions (%d)\n" (length items)))
      (if items
          (dolist (item items)
            (insert (plist-get item :label))
            (unless (string-empty-p (plist-get item :detail))
              (insert "  " (plist-get item :detail)))
            (insert "\n"))
        (insert "- none\n")))
    (insert (format "\nBeads (%d)\n" (length beads)))
      (if beads
          (dolist (bead beads)
            (let ((item (cube-project--bead-item bead)))
              (insert (plist-get item :label))
              (let ((detail (plist-get item :detail)))
                (unless (string-empty-p detail) (insert "  " detail)))
              (insert "\n")))
        (insert "- none\n"))
    (buffer-string)))

;;;; Backend access

(defun cube-projects--fetch (callback &optional error-callback)
  "Fetch projects and call CALLBACK with the parsed JSON."
  (cube--call-json-async
   '("projects")
   (lambda (json) (setq cube-project--cache (cube-get json 'projects))
     (funcall callback json))
   error-callback))

(defun cube-projects (&optional refresh)
  "Return projects synchronously, refreshing when REFRESH is non-nil."
  (when (or refresh (null cube-project--cache))
    (setq cube-project--cache (cube-get (cube--call-json '("projects")) 'projects)))
  cube-project--cache)

(defun cube-project-list ()
  "Show the cached projects list and refresh it asynchronously."
  (interactive)
  (with-current-buffer (get-buffer-create "*cube-projects*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert "Projects\n\n")
      (if cube-project--cache
          (dolist (project (cube-project--sort cube-project--cache))
            (insert (format "%s  %s\n"
                            (cube-project--status-glyph (cube-get project 'status))
                            (cube--string (cube-get project 'name)))))
        (insert "  refreshing...\n"))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer)))
  (cube-projects--fetch
   (lambda (json)
     (when-let* ((buffer (get-buffer "*cube-projects*")))
       (with-current-buffer buffer
         (let ((inhibit-read-only t))
           (erase-buffer)
           (insert "Projects\n\n")
           (dolist (project (cube-project--sort (cube-get json 'projects)))
             (insert (format "%s  %s\n"
                             (cube-project--status-glyph (cube-get project 'status))
                             (cube--string (cube-get project 'name)))))))))
   (lambda (code err) (message "cube: projects failed (%s): %s" code err))))

;;;; Project buffer

(defvar-local cube-project--project nil)
(defvar-local cube-project--beads nil)
(defvar-local cube-project--people nil)
(defvar-local cube-project--sessions nil)

(defun cube-project--insert-items (kind title items empty)
  "Insert a Magit group of visitable ITEMS, or EMPTY when there are none."
  (magit-insert-section (cube-project-group kind)
    (magit-insert-heading (format "%s (%d)" title (length items)))
    (if items
        (dolist (item items)
          (magit-insert-section (cube-item item)
            (let ((detail (plist-get item :detail)))
              (magit-insert-heading
               (concat (plist-get item :label)
                       (if (string-empty-p detail) ""
                         (propertize (concat "  " detail)
                                     'font-lock-face 'shadow)))))))
      (insert "  " empty "\n"))
    (insert "\n")))

(defun cube-project--render ()
  "Render the current project buffer."
  (when (and cube-project--project (derived-mode-p 'cube-project-mode))
    (let ((inhibit-read-only t)
          (line (line-number-at-pos))
          (col (current-column)))
      (erase-buffer)
      (magit-insert-section (cube-project-root)
        (magit-insert-heading
          (format "%s  %s"
                  (cube-project--status-glyph (cube-get cube-project--project 'status))
                  (cube--string (cube-get cube-project--project 'name))))
        (insert (cube-project--static-text cube-project--project cube-project--people) "\n")
        (magit-insert-section (cube-project-runner-profile)
          (magit-insert-heading "Runner profile")
          (insert (replace-regexp-in-string "\\`Runner profile\\n" ""
                                             (cube-project--runner-profile-text cube-project--project)))
          (insert "\n"))
        (cube-project--insert-items
         'adopted-sessions "Adopted sessions"
         (mapcar #'cube-project--session-item
                 (cube-project--adopted-sessions-for (cube-get cube-project--project 'slug)
                                                     cube-project--sessions))
         "none")
        (cube-project--insert-items 'beads "Beads"
                                    (mapcar #'cube-project--bead-item cube-project--beads) "none"))
      (goto-char (point-min))
      (forward-line (1- line))
      (move-to-column col))))

(defun cube-project--visit ()
  "Visit the bead or adopted session at point, or toggle its group."
  (interactive)
  (let* ((section (magit-current-section))
         (value (and section (oref section value))))
    (pcase (plist-get value :type)
      ('bead (cube-beads-show (plist-get value :id)))
      ('session (cube-rolodex-attach (plist-get value :id) (plist-get value :data)))
      (_ (when section (magit-section-toggle section))))))

(defun cube-project-assign ()
  "Assign a new bead to the project shown in the current buffer."
  (interactive)
  (unless cube-project--project (user-error "cube: not a project buffer"))
  (cube-beads-assign nil (cube-get cube-project--project 'slug)))

(defvar cube-project-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map magit-section-mode-map)
    (define-key map (kbd "g") #'cube-project-revert)
    (define-key map (kbd "RET") #'cube-project--visit)
    (define-key map (kbd "a") #'cube-project-assign)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap of `cube-project-mode'.")

(define-derived-mode cube-project-mode magit-section-mode "cube-project"
  "Project details and project beads."
  (setq-local revert-buffer-function (lambda (&rest _) (cube-project-revert))))

(defun cube-project-revert ()
  "Refresh the project, its ready beads, and its adopted sessions."
  (interactive)
  (when cube-project--project
    (let ((buffer (current-buffer))
          (slug (cube-get cube-project--project 'slug)))
      (cube-project--render)
      (cube-beads--fetch-ready
       (lambda (beads)
         (when (buffer-live-p buffer)
           (with-current-buffer buffer
             (setq cube-project--beads (cube-project--beads-for slug beads))
             (cube-project--render))))
       (lambda (_code _err) (message "cube: project beads unavailable")))
      (cube--call-json-async
       '("fleet")
       (lambda (json)
         (when (buffer-live-p buffer)
           (with-current-buffer buffer
             (setq cube-fleet--cache (cube-get json 'sessions)
                   cube-project--sessions cube-fleet--cache)
             (cube-project--render))))
       (lambda (_code _err) (message "cube: project adopted sessions unavailable"))))))

(defun cube-project-open (slug &optional project)
  "Open project SLUG, using PROJECT when already available."
  (interactive (list (completing-read "Project: "
                                      (mapcar (lambda (p) (cube-get p 'slug))
                                              (cube-projects)))))
  (let ((buffer (get-buffer-create (format "*cube-project: %s*" slug))))
    (if project
        (with-current-buffer buffer
          (unless (derived-mode-p 'cube-project-mode) (cube-project-mode))
          (setq cube-project--project project
                cube-project--people (ignore-errors (cube-org-people))
                cube-project--sessions (or cube-fleet--cache nil))
          (cube-project--render)
          (pop-to-buffer buffer)
          (cube-project-revert))
      (cube-projects--fetch
       (lambda (json)
         (if-let* ((found (seq-find (lambda (p) (equal (cube-get p 'slug) slug))
                                    (cube-get json 'projects))))
             (cube-project-open slug found)
           (message "cube: project %s not found" slug)))
       (lambda (code err) (message "cube: projects failed (%s): %s" code err))))))

(provide 'cube-project)
;;; cube-project.el ends here
