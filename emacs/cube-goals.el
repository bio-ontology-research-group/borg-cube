;;; cube-goals.el --- Goals as the cockpit operating loop  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;;; Commentary:

;; Goals make the cockpit a driver's seat: set a goal, inspect its decomposition,
;; spin agents, put owed items onto a 1:1 agenda, and address blockers.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'org)
(require 'transient)
(require 'magit-section)
(require 'cube-core)
(require 'cube-beads)
(require 'cube-org)
(require 'cube-project)
(require 'cube-review)

(declare-function cube-run-bead "cube-rolodex" (role &optional bead resume-id))

(defvar cube-goals--payload nil
  "Most recently fetched cube goals payload.")
(defvar cube-goals--cache nil
  "Goals from the most recent successful cube goals call.")
(defvar cube-goals-update-hook nil
  "Hook run after the cached goals have changed.")
(defvar cube-goal--new-plist nil
  "Fields collected by the new-goal transient.")
(defvar cube-goal--goal nil
  "Goal object shown in the current goal buffer.")
(make-variable-buffer-local 'cube-goal--goal)

(defcustom cube-goals-confirm-writes t
  "When non-nil ask before applying a goal write plan."
  :type 'boolean
  :group 'borg-cube)

(defun cube-goals--list (json)
  "Return the goal list in JSON, or an empty list."
  (cond ((and (consp json) (assq 'goals json)) (cube-get json 'goals))
        ((and (listp json) (or (null json) (consp (car json)))) json)
        (t nil)))

(defun cube-goal--object (json)
  "Return a goal object from JSON, accepting a wrapped payload."
  (if (and (consp json) (consp (cube-get json 'goal)))
      (cube-get json 'goal)
    json))

(defun cube-goal--id (goal)
  "Return GOAL's identifier as a string."
  (if (stringp goal) goal
    (cube--string (or (cube-get goal 'id) (cube-get goal 'slug)
                      (cube-get goal 'title) (cube-get goal 'name)))))

(defun cube-goal--label (goal)
  "Return a compact menu label for GOAL."
  (format "%s %s"
          (if (member (cube-get goal 'status) '("active" "at-risk")) "●" "○")
          (cube--string (or (cube-get goal 'title) (cube-goal--id goal)))))

(defun cube-goal--active-p (goal)
  "Return non-nil when GOAL belongs in the active dashboard section."
  (member (cube-get goal 'status) '("active" "at-risk")))

(defun cube-goal--on-track-glyph (goal)
  "Return the on-track glyph for GOAL."
  (let ((value (cube-get goal 'on_track)))
    (cond ((eq value :false) "!")
          ((null value) "?")
          (t "✓"))))

(defun cube-goal--progress-bar (goal &optional width)
  "Return a fixed-width text progress bar for GOAL."
  (let* ((width (or width 10))
         (pct (max 0 (min 100 (or (cube-get goal 'progress 'pct) 0))))
         (filled (round (* width (/ (float pct) 100.0)))))
    (format "[%s%s]" (make-string filled ?#) (make-string (- width filled) ?-))))

(defun cube-goal--days-left-text (goal)
  "Return the deadline status text for GOAL."
  (let ((days (cube-get goal 'days_left)))
    (cond ((not (numberp days)) "?d left")
          ((< days 0) (format "%dd overdue" (- days)))
          (t (format "%dd left" days)))))

(defun cube-goal--initials (slug)
  "Return readable initials for person SLUG."
  (let ((parts (split-string (cube--string slug) "[-_ ]+" t)))
    (if parts
        (mapconcat (lambda (part) (upcase (substring part 0 1))) parts "")
      "?")))

(defun cube-goal--people-initials (goal)
  "Return the stakeholders of GOAL as compact initials."
  (let ((people (cube-get goal 'people)))
    (if people (string-join (mapcar #'cube-goal--initials people) ",") "-")))

(defun cube-goal--row-text (goal)
  "Return the pure dashboard line for GOAL."
  (let ((pct (or (cube-get goal 'progress 'pct) 0))
        (blockers (length (cube-get goal 'blockers))))
    (format "%s %-12s %3d%%  %-10s blockers %d  %-8s %s"
            (cube-goal--on-track-glyph goal)
            (cube-goal--progress-bar goal)
            pct (cube-goal--days-left-text goal) blockers
            (cube-goal--people-initials goal)
            (cube--string (cube-get goal 'title)))))

(defun cube-goal--row-item (goal)
  "Return a dashboard item for GOAL."
  (list :type 'goal :id (cube-goal--id goal) :label (cube-goal--row-text goal)
        :detail nil :data goal))

(defun cube-goals--set-cache (json)
  "Store JSON and its goal list in the local cache."
  (setq cube-goals--payload json
        cube-goals--cache (cube-goals--list json))
  (run-hooks 'cube-goals-update-hook)
  cube-goals--cache)

(defun cube-goals-refresh ()
  "Fetch the goals payload asynchronously."
  (interactive)
  (cube--call-json-async
   '("goals")
   (lambda (json)
     (cube-goals--set-cache json)
     (message "cube: %d goal(s) cached" (length cube-goals--cache)))
   (lambda (code err) (message "cube: goals failed (%s): %s" code err))))

(defun cube-goal--agent-items (goal)
  "Return the next ready agent beads of GOAL as items."
  (mapcar
   (lambda (agent)
     (list :type 'agent :id (cube--string (cube-get agent 'bead)) :data agent
           :label (format "%s  %s  ready%s" (cube--string (cube-get agent 'bead))
                          (cube--string (cube-get agent 'role))
                          (if (cube-get agent 'resume_id) "  ↻" ""))))
   (seq-filter (lambda (agent) (cube-true-p (cube-get agent 'ready)))
               (cube-get goal 'next 'agents))))

(defun cube-goal--owed-item (owed)
  "Return a visitable person item for one OWED record."
  (list :type 'person :id (cube--string (cube-get owed 'person)) :data owed
        :label (format "%s  %s%s" (cube--string (cube-get owed 'person))
                       (cube--string (cube-get owed 'title))
                       (if-let* ((due (cube-get owed 'due)))
                           (format "  due %s" due) ""))))

(defun cube-goal--blocker-item (blocker)
  "Return a visitable bead item for BLOCKER."
  (list :type 'bead :id (cube--string (cube-get blocker 'bead)) :data blocker
        :label (format "%s  %s%s" (cube--string (cube-get blocker 'bead))
                       (cube--string (cube-get blocker 'title))
                       (if-let* ((reason (cube-get blocker 'reason)))
                           (format "  %s" reason) ""))))

(defun cube-goal--render-text (goal)
  "Return the pure textual header and groups for GOAL."
  (with-temp-buffer
    (insert (format "Goal: %s\nTarget: %s\nProject: %s\n"
                    (cube--string (cube-get goal 'title))
                    (cube--string (cube-get goal 'target))
                    (or (cube-get goal 'project) "-")))
    (insert "Success criteria\n")
    (if-let* ((success (cube-get goal 'success)))
        (dolist (criterion success) (insert (format "- %s\n" criterion)))
      (insert "- none recorded\n"))
    (dolist (spec '(("Agents" agents) ("People" people) ("Blockers" blockers)))
      (let* ((name (car spec))
             (kind (cadr spec))
             (items (pcase kind
                      ('agents (cube-goal--agent-items goal))
                      ('people (mapcar #'cube-goal--owed-item
                                       (cube-get goal 'next 'people)))
                      ('blockers (mapcar #'cube-goal--blocker-item
                                         (cube-get goal 'blockers))))))
        (insert (format "\n%s\n" name))
        (if items
            (dolist (item items) (insert (format "- %s\n" (plist-get item :label))))
          (insert "- none\n"))))
    (buffer-string)))

(defun cube-goal--show-args (id)
  "Return the arguments to fetch goal ID."
  (list "goal" "show" id))

(defun cube-goal--new-args (plist &optional flag)
  "Construct cube goal new arguments from PLIST.
TITLE, TARGET, a success criterion, and provenance are required."
  (let ((title (string-trim (cube--string (plist-get plist :title))))
        (target (string-trim (cube--string (plist-get plist :target))))
        (success (seq-filter (lambda (item) (not (string-empty-p (string-trim item))))
                             (plist-get plist :success)))
        (provenance (seq-filter (lambda (item) (not (string-empty-p (string-trim item))))
                                (plist-get plist :provenance))))
    (when (string-empty-p title) (user-error "cube: a goal needs a title"))
    (when (string-empty-p target) (user-error "cube: a goal needs a target date"))
    (unless success (user-error "cube: a goal needs a success criterion"))
    (unless provenance (user-error "cube: a goal needs provenance"))
    (append (list "goal" "new" "--title" title "--target" target)
            (apply #'append (mapcar (lambda (item) (list "--success" item)) success))
            (when-let* ((project (plist-get plist :project))) (list "--project" project))
            (apply #'append (mapcar (lambda (item) (list "--person" item))
                                    (plist-get plist :people)))
            (apply #'append (mapcar (lambda (item) (list "--provenance" item)) provenance))
            (list (or flag "--dry-run")))))

(defun cube-goal--spin-args (goal &optional agent flag)
  "Construct a guarded cube goal spin command for GOAL and AGENT."
  (append (list "goal" "spin" (cube-goal--id goal))
          (when-let* ((bead (and agent (cube-get agent 'bead)))) (list "--bead" bead))
          (when-let* ((role (and agent (cube-get agent 'role)))) (list "--role" role))
          (list (or flag "--dry-run"))))

(defun cube-goal--update-supported-p (&optional goal)
  "Return non-nil when GOAL advertises the optional update action."
  (let ((goal (or goal cube-goal--goal)))
    (or (cube-true-p (cube-get goal 'capabilities 'update))
        (member "update" (cube-get goal 'actions)))))

(defun cube-goal--update-args (goal field value &optional flag)
  "Construct cube goal update args for GOAL's FIELD and VALUE."
  (unless (member field '(target success)) (user-error "cube: unknown goal field %s" field))
  (list "goal" "update" (cube-goal--id goal)
        (format "--%s" field) value (or flag "--dry-run")))

;;;; Guarded writes and new-goal transient

(defun cube-goal--show-plan (label args json)
  "Show LABEL's dry-run ARGS and JSON response in a review buffer."
  (with-current-buffer (get-buffer-create "*cube-goal-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (format "Goal plan: %s\n\nCommand\n  cube %s --json\n\nResult\n"
                      label (string-join args " ")))
      (when-let* ((diff (cube-get json 'diff))) (insert "\nDiff\n" diff "\n"))
      (when-let* ((review (cube-get json 'review)))
        (insert (format "\nReview item: %s\n" (cube--string review))))
      (insert (pp-to-string json))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-goal--write (args label &optional callback)
  "Dry-run goal ARGS, show LABEL's plan, then confirm and apply it."
  (let* ((base (seq-remove (lambda (arg) (member arg '("--dry-run" "--apply"))) args))
         (dry (append base '("--dry-run"))))
    (cube--call-json-async
     dry
     (lambda (json)
       (cube-goal--show-plan label dry json)
       (when (or (not cube-goals-confirm-writes)
                 (y-or-n-p (format "Apply goal %s? " label)))
         (cube--call-json-async
          (append base '("--apply"))
          (lambda (result)
            (message "cube: %s applied" label)
            (cube-goals-refresh)
            (when callback (funcall callback result)))
          (lambda (code err) (message "cube: %s apply failed (%s): %s" label code err)))))
     (lambda (code err) (message "cube: %s dry-run failed (%s): %s" label code err)))))

(defun cube-goal--new-set (key value &optional append)
  "Set KEY to VALUE in the new-goal transient, APPENDing repeatable values."
  (setq cube-goal--new-plist
        (plist-put cube-goal--new-plist key
                   (if append (append (plist-get cube-goal--new-plist key) (list value)) value)))
  (message "cube: %s %s" (substring (symbol-name key) 1) value))

(defun cube-goal-new-set-title ()
  "Set the new goal title."
  (interactive)
  (cube-goal--new-set :title (read-string "Goal title: ")))

(defun cube-goal-new-set-target ()
  "Set the new goal target date using Org's date reader."
  (interactive)
  (cube-goal--new-set :target (org-read-date nil nil nil "Target date: ")))

(defun cube-goal-new-add-success ()
  "Add one testable success criterion to the new goal."
  (interactive)
  (cube-goal--new-set :success (read-string "Success criterion: ") t))

(defun cube-goal--project-completion ()
  "Return project completion pairs from cube projects."
  (mapcar (lambda (project)
            (cons (format "%s (%s)" (cube-get project 'name) (cube-get project 'slug))
                  (cube-get project 'slug)))
          (condition-case nil (cube-projects) (error nil))))

(defun cube-goal--person-completion ()
  "Return people completion pairs from cube people."
  (mapcar (lambda (person)
            (cons (format "%s (%s)" (cube-get person 'name) (cube-get person 'slug))
                  (cube-get person 'slug)))
          (cube-org-people)))

(defun cube-goal-new-set-project ()
  "Set the KG project for the new goal."
  (interactive)
  (let* ((choices (cube-goal--project-completion))
         (choice (completing-read "Project: " choices nil t)))
    (cube-goal--new-set :project (or (cdr (assoc choice choices)) choice))))

(defun cube-goal-new-add-person ()
  "Add a stakeholder to the new goal."
  (interactive)
  (let* ((choices (cube-goal--person-completion))
         (choice (completing-read "Person: " choices nil t)))
    (cube-goal--new-set :people (or (cdr (assoc choice choices)) choice) t)))

(defun cube-goal-new-add-provenance ()
  "Add a provenance path and locator to the new goal."
  (interactive)
  (cube-goal--new-set :provenance (read-string "Provenance PATH::LOCATOR: ") t))

(defun cube-goal-new-execute ()
  "Create the pending goal after presenting its dry-run plan."
  (interactive)
  (cube-goal--write (cube-goal--new-args cube-goal--new-plist) "new goal"))

(transient-define-prefix cube-goal-new-menu ()
  "Set a goal, its evidence, and its stakeholders."
  ["Goal"
   ("t" "Title" cube-goal-new-set-title)
   ("d" "Target date" cube-goal-new-set-target)
   ("s" "Add success criterion" cube-goal-new-add-success)
   ("p" "Project" cube-goal-new-set-project)
   ("P" "Add person" cube-goal-new-add-person)]
  ["Evidence" ("v" "Add provenance" cube-goal-new-add-provenance)]
  ["Execute"
   ("RET" "Preview and create" cube-goal-new-execute)
   ("q" "Quit" transient-quit-one)])

(defun cube-goal-new (&optional title)
  "Start a transient for a new goal, optionally seeded with TITLE."
  (interactive)
  (setq cube-goal--new-plist (and title (list :title title)))
  (transient-setup 'cube-goal-new-menu))

;;;; Focused goal buffer

(defun cube-goal--insert-item (item)
  "Insert ITEM as a visitable row in the current goal section."
  (magit-insert-section (cube-goal-item item)
    (magit-insert-heading (concat "  " (plist-get item :label)))))

(defun cube-goal--insert-group (kind title items empty)
  "Insert group KIND titled TITLE with ITEMS or EMPTY text."
  (magit-insert-section (cube-goal-group kind)
    (magit-insert-heading (format "%s (%d)" title (length items)))
    (if items
        (dolist (item items) (cube-goal--insert-item item))
      (insert "  " empty "\n"))
    (insert "\n")))

(defun cube-goal--insert-project-link (project)
  "Insert a usable project link for PROJECT."
  (if (and project (not (string-empty-p (cube--string project))))
      (insert-text-button (cube--string project) 'follow-link t
                          'help-echo "Open this project"
                          'action (lambda (_button) (cube-project-open project)))
    (insert "-")))

(defun cube-goal--render ()
  "Render the current goal buffer from the local goal object."
  (when (and cube-goal--goal (derived-mode-p 'cube-goal-mode))
    (let ((inhibit-read-only t) (line (line-number-at-pos)) (column (current-column))
          (goal cube-goal--goal))
      (erase-buffer)
      (magit-insert-section (cube-goal-root)
        (magit-insert-heading
          (format "%s  %s" (cube-goal--on-track-glyph goal)
                  (cube--string (cube-get goal 'title))))
        (insert (format "Target: %s   %s\n" (cube--string (cube-get goal 'target))
                        (cube-goal--days-left-text goal)))
        (cube-key-legend-insert 'cube-goal-mode)
        (insert "Success criteria\n")
        (if-let* ((success (cube-get goal 'success)))
            (dolist (criterion success) (insert (format "  - %s\n" criterion)))
          (insert "  - none recorded\n"))
        (insert "Project: ")
        (cube-goal--insert-project-link (cube-get goal 'project))
        (insert "\n\n")
        (cube-goal--insert-group 'agents "Agents" (cube-goal--agent-items goal)
                                 "no ready agent work")
        (cube-goal--insert-group 'people "People"
                                 (mapcar #'cube-goal--owed-item (cube-get goal 'next 'people))
                                 "no one is owed an item")
        (cube-goal--insert-group 'blockers "Blockers"
                                 (mapcar #'cube-goal--blocker-item (cube-get goal 'blockers))
                                 "none")
        (let ((start (point)))
          (insert (if (cube-goal--update-supported-p goal)
                      "e  Edit target or success criteria\n"
                    "e  Edit unavailable: backend does not expose goal update\n"))
          (unless (cube-goal--update-supported-p goal)
            (add-text-properties start (point)
                                 '(font-lock-face shadow
                                   help-echo "The current cube backend does not advertise goal update.")))))
      (goto-char (point-min))
      (forward-line (1- line))
      (move-to-column column))))

(defun cube-goal--current-item ()
  "Return the focused goal item's plist, if point is on an item."
  (let ((value (and (magit-current-section) (oref (magit-current-section) value))))
    (and (listp value) (plist-get value :type) value)))

(defun cube-goal-visit ()
  "Open the focused agent or blocker bead, or the selected person's dossier."
  (interactive)
  (let ((item (cube-goal--current-item)))
    (pcase (plist-get item :type)
      ((or 'agent 'bead) (cube-beads-show (plist-get item :id)))
      ('person (cube-org-person-context (plist-get item :id)
                                        (cube-org--person (plist-get item :id))))
      (_ (when-let* ((section (magit-current-section))) (magit-section-toggle section))))))

(defun cube-goal-spin-agent ()
  "Dry-run, review, confirm, and apply a spin for the ready agent at point."
  (interactive)
  (unless cube-goal--goal (user-error "cube: not a goal buffer"))
  (let* ((item (cube-goal--current-item))
         (agent (and (eq (plist-get item :type) 'agent) (plist-get item :data))))
    (unless agent (user-error "cube: select a ready agent bead first"))
    (cube-goal--write (cube-goal--spin-args cube-goal--goal agent)
                      (format "spin %s" (cube-get agent 'bead))
                      (lambda (_) (cube-goal-revert)))))

(defun cube-goal-run-agent ()
  "Dry-run and start the ready agent bead at point in the rolodex.
The effective project runner profile is shown before confirmation, and a
stored resume id selects `cube run --resume'."
  (interactive)
  (let* ((item (cube-goal--current-item))
         (agent (and (eq (plist-get item :type) 'agent) (plist-get item :data))))
    (unless agent (user-error "cube: select a ready agent bead first"))
    (cube-run-bead (cube--string (cube-get agent 'role))
                   (cube--string (cube-get agent 'bead))
                   (cube-get agent 'resume_id))))

(defun cube-goal-add-to-agenda ()
  "Add the owed item at point to its person's next-meeting agenda."
  (interactive)
  (let* ((item (cube-goal--current-item))
         (owed (and (eq (plist-get item :type) 'person) (plist-get item :data))))
    (unless owed (user-error "cube: select an owed person item first"))
    (let* ((person (cube--string (cube-get owed 'person)))
           (title (cube--string (cube-get owed 'title)))
           (agenda (concat title (if-let* ((due (cube-get owed 'due)))
                                     (format " (due %s)" due) ""))))
      (cube-org--write
       (cube-org--append-args person "Next meeting agenda" nil (list agenda))
       (format "agenda item for %s" person) nil))))

(defun cube-goal-decompose ()
  "Ask for a dry-run decomposition and open the ordinary review queue."
  (interactive)
  (unless cube-goal--goal (user-error "cube: not a goal buffer"))
  (let ((args (list "goal" "decompose" (cube-goal--id cube-goal--goal) "--dry-run")))
    (cube--call-json-async
     args (lambda (json) (cube-goal--show-plan "decompose" args json) (cube-review-queue))
     (lambda (code err) (message "cube: decompose failed (%s): %s" code err)))))

(defun cube-goal-edit ()
  "Edit the goal target or success criteria when the backend supports it."
  (interactive)
  (unless cube-goal--goal (user-error "cube: not a goal buffer"))
  (unless (cube-goal--update-supported-p cube-goal--goal)
    (user-error "cube: this backend does not expose goal update"))
  (let* ((field (intern (completing-read "Update: " '("target" "success") nil t)))
         (value (if (eq field 'target) (org-read-date nil nil nil "Target date: ")
                  (read-string "Success criterion: "))))
    (cube-goal--write (cube-goal--update-args cube-goal--goal field value)
                      (format "update %s" field) (lambda (_) (cube-goal-revert)))))

(defun cube-goal-revert ()
  "Refresh the current goal from cube goal show."
  (interactive)
  (unless cube-goal--goal (user-error "cube: not a goal buffer"))
  (let ((buffer (current-buffer)) (id (cube-goal--id cube-goal--goal)))
    (cube--call-json-async
     (cube-goal--show-args id)
     (lambda (json)
       (when (buffer-live-p buffer)
         (with-current-buffer buffer
           (setq cube-goal--goal (cube-goal--object json))
           (cube-goal--render))))
     (lambda (code err) (message "cube: goal %s failed (%s): %s" id code err)))))

(defvar cube-goal-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map magit-section-mode-map)
    (define-key map (kbd "g") #'cube-goal-revert)
    (define-key map (kbd "G") #'cube-goal-new)
    (define-key map (kbd "RET") #'cube-goal-visit)
    (define-key map (kbd "r") #'cube-goal-run-agent)
    (define-key map (kbd "s") #'cube-goal-spin-agent)
    (define-key map (kbd "m") #'cube-goal-add-to-agenda)
    (define-key map (kbd "d") #'cube-goal-decompose)
    (define-key map (kbd "e") #'cube-goal-edit)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap of cube-goal-mode.")

(defconst cube-goal-mode-key-help
  '(("RET" . "open") ("G" . "new goal") ("d" . "decompose") ("e" . "edit")
    ("r" . "run agent") ("s" . "spin agent") ("m" . "add to agenda")
    ("g" . "refresh"))
  "Key legend of `cube-goal-mode', proved against its keymap by the tests.")

(cube-key-legend-register 'cube-goal-mode)

(define-derived-mode cube-goal-mode magit-section-mode "cube-goal"
  "One goal, its people, agents, and blockers."
  (setq-local revert-buffer-function (lambda (&rest _) (cube-goal-revert))))

(defun cube-goal-open (goal)
  "Open GOAL, an alist or an identifier, in cube-goal-mode."
  (interactive
   (list (let ((choice (completing-read
                        "Goal: "
                        (mapcar (lambda (g) (cons (cube-goal--label g) g)) cube-goals--cache)
                        nil t)))
           (or (cdr (assoc choice
                           (mapcar (lambda (g) (cons (cube-goal--label g) g))
                                   cube-goals--cache)))
               choice))))
  (let* ((cached (if (stringp goal)
                     (seq-find (lambda (g) (equal (cube-goal--id g) goal)) cube-goals--cache)
                   goal))
         (id (cube-goal--id (or cached goal)))
         (buffer (get-buffer-create (format "*cube-goal: %s*" id))))
    (with-current-buffer buffer
      (unless (derived-mode-p 'cube-goal-mode) (cube-goal-mode))
      (setq cube-goal--goal (or cached (list (cons 'id id) (cons 'title id))))
      (cube-goal--render))
    (pop-to-buffer buffer)
    (with-current-buffer buffer (cube-goal-revert))))

(defun cube-goals ()
  "Show cached goals and refresh them asynchronously."
  (interactive)
  (with-current-buffer (get-buffer-create "*cube-goals*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert "Goals\n\n")
      (if cube-goals--cache
          (dolist (goal cube-goals--cache)
            (insert (format "%s\n" (cube-goal--row-text goal))))
        (insert "  refreshing...\n"))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer)))
  (cube-goals-refresh))

(provide 'cube-goals)
;;; cube-goals.el ends here
