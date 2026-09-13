;;; cube-pipeline.el --- Research pipelines in the cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;;; Commentary:

;; The cockpit presents the deterministic research-pipeline ledger.  The
;; backend remains authoritative for stages, experiments, gates and their
;; transitions.  This file only renders its JSON contract and opens the
;; existing bead, agent and terminal interfaces around it.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'org)
(require 'transient)
(require 'magit-section)
(require 'cube-core)
(require 'cube-beads)
(require 'cube-agents)
(require 'cube-project)
(require 'cube-org)
(require 'cube-rolodex)
(require 'cube-term)

(defvar cube-pipelines--payload nil
  "Most recently fetched `cube pipeline status' payload.")
(defvar cube-pipelines--cache nil
  "Pipelines from the most recent successful status call.")
(defvar cube-pipelines--error nil
  "Most recent bounded failure while listing pipelines.")
(defvar cube-pipelines--time nil
  "Time of the most recent pipeline list result or failure.")
(defvar cube-pipeline--new-plist nil
  "Fields collected by the new-pipeline transient.")

(defvar-local cube-pipeline--pipeline nil
  "Pipeline object rendered in the current pipeline buffer.")
(defvar-local cube-pipeline--view nil
  "Current pipeline buffer view, either `list' or `show'.")
(defvar-local cube-pipeline--error nil
  "Bounded failure rendered in the current pipeline buffer.")
(defvar-local cube-pipeline--plan-args nil
  "Dry-run command displayed in the current pipeline plan buffer.")

(defcustom cube-pipeline-confirm-advance t
  "When non-nil ask before applying one pipeline transition."
  :type 'boolean
  :group 'borg-cube)

;;;; Contract normalisers

(defun cube-pipeline--pipelines (json)
  "Return the pipeline list in status JSON, or an empty list.
The list form is exactly the `pipelines' member documented for `cube pipeline
status --json'."
  (if (and (consp json) (assq 'pipelines json))
      (cube-get json 'pipelines)
    nil))

(defun cube-pipeline--object (json)
  "Return one pipeline object from a single-status JSON response."
  json)

(defun cube-pipeline--id (pipeline)
  "Return PIPELINE's epic identifier as a string."
  (if (stringp pipeline) pipeline (cube--string (cube-get pipeline 'epic))))

(defun cube-pipeline--gate-verdict (pipeline)
  "Return PIPELINE's gate verdict, with a readable pending fallback."
  (or (cube-get pipeline 'gate 'verdict) "pending"))

(defun cube-pipeline--kill-text (pipeline)
  "Return a readable kill-condition state for PIPELINE."
  (if (cube-true-p (cube-get pipeline 'kill)) "yes" "no"))

(defun cube-pipeline--row-text (pipeline)
  "Return the compact dashboard line for PIPELINE."
  (format "%s  %s  iteration %s"
          (cube--string (cube-get pipeline 'title))
          (cube--string (cube-get pipeline 'stage))
          (cube--string (cube-get pipeline 'iteration))))

(defun cube-pipeline--row-item (pipeline)
  "Return a dashboard item for PIPELINE."
  (list :type 'pipeline :id (cube-pipeline--id pipeline)
        :label (cube-pipeline--row-text pipeline) :detail nil :data pipeline))

(defun cube-pipeline--set-cache (json)
  "Store the successful pipeline list JSON response."
  (setq cube-pipelines--payload json
        cube-pipelines--cache (cube-pipeline--pipelines json)
        cube-pipelines--error nil
        cube-pipelines--time (current-time))
  cube-pipelines--cache)

(defun cube-pipeline--stage-text (stage)
  "Return one display line for a pipeline STAGE object."
  (format "%s  %s  %s  owner %s%s"
          (cube--string (cube-get stage 'name))
          (cube--string (cube-get stage 'bead))
          (cube--string (cube-get stage 'status))
          (cube--string (cube-get stage 'owner))
          (let ((blocked (cube-get stage 'blocked_by)))
            (if blocked
                (format "  blocked by %s"
                        (string-join (mapcar #'cube--string blocked) ", "))
              ""))))

(defun cube-pipeline--experiment-text (experiment)
  "Return one display line for pipeline EXPERIMENT."
  (let ((review (cube-get experiment 'review)))
    (format "%s  %s%s"
            (cube--string (cube-get experiment 'bead))
            (cube--string (cube-get experiment 'status))
            (if review
                (format "  review %s %s %s"
                        (cube--string (cube-get review 'bead))
                        (cube--string (cube-get review 'status))
                        (cube--string (cube-get review 'verdict)))
              "  review pending"))))

(defun cube-pipeline--render-text (pipeline)
  "Return the pure readable rendering of one PIPELINE status object."
  (with-temp-buffer
    (insert (format "%s\n" (cube--string (cube-get pipeline 'title))))
    (insert (format "Epic: %s\nStage: %s\nIteration: %s\nKill: %s\n"
                    (cube-pipeline--id pipeline)
                    (cube--string (cube-get pipeline 'stage))
                    (cube--string (cube-get pipeline 'iteration))
                    (cube-pipeline--kill-text pipeline)))
    (insert "\nStages\n")
    (if-let* ((stages (cube-get pipeline 'stages)))
        (dolist (stage stages) (insert "- " (cube-pipeline--stage-text stage) "\n"))
      (insert "- none\n"))
    (insert "\nExperiments\n")
    (if-let* ((experiments (cube-get pipeline 'experiments)))
        (dolist (experiment experiments)
          (insert "- " (cube-pipeline--experiment-text experiment) "\n"))
      (insert "- none\n"))
    (let ((gate (cube-get pipeline 'gate)))
      (insert (format "\nGate\n- %s  %s  %s\n"
                      (cube--string (cube-get gate 'n))
                      (cube--string (cube-get gate 'bead))
                      (cube-pipeline--gate-verdict pipeline))))
    (insert (format "\nNext\n%s\n" (cube--string (cube-get pipeline 'next))))
    (buffer-string)))

;;;; Status fetching and rendering

(defun cube-pipeline--status-args (&optional epic)
  "Return status command arguments, optionally narrowed to EPIC."
  (append '("pipeline" "status") (when epic (list epic))))

(defun cube-pipelines-refresh ()
  "Fetch all research-pipeline status records asynchronously."
  (interactive)
  (cube--call-json-async
   (cube-pipeline--status-args)
   (lambda (json)
     (cube-pipeline--set-cache json)
     (when-let* ((buffer (get-buffer "*cube-pipelines*")))
       (with-current-buffer buffer (when (eq cube-pipeline--view 'list)
                                     (cube-pipeline--render))))
     (message "cube: %d pipeline(s) cached" (length cube-pipelines--cache)))
   (lambda (code err)
     (setq cube-pipelines--error (format "pipeline status failed (%s): %s" code err)
           cube-pipelines--time (current-time))
     (when-let* ((buffer (get-buffer "*cube-pipelines*")))
       (with-current-buffer buffer (when (eq cube-pipeline--view 'list)
                                     (cube-pipeline--render)))))))

(defun cube-pipeline--insert-item (item)
  "Insert visitable pipeline ITEM in the current Magit section."
  (magit-insert-section (cube-pipeline-item item)
    (magit-insert-heading (concat "  " (plist-get item :label)))))

(defun cube-pipeline--insert-group (kind title items empty &optional formatter)
  "Insert pipeline group KIND titled TITLE using ITEMS and FORMATTER.
EMPTY is rendered when ITEMS is empty."
  (magit-insert-section (cube-pipeline-group kind)
    (magit-insert-heading (format "%s (%d)" title (length items)))
    (if items
        (dolist (item items)
          (cube-pipeline--insert-item
           (funcall (or formatter #'identity) item)))
      (insert "  " empty "\n"))
    (insert "\n")))

(defun cube-pipeline--stage-item (stage)
  "Return a visitable Beads item for STAGE."
  (list :type 'bead :id (cube--string (cube-get stage 'bead)) :data stage
        :label (cube-pipeline--stage-text stage)))

(defun cube-pipeline--experiment-item (experiment)
  "Return a visitable Beads item for EXPERIMENT."
  (list :type 'bead :id (cube--string (cube-get experiment 'bead)) :data experiment
        :label (cube-pipeline--experiment-text experiment)))

(defun cube-pipeline--gate-item (pipeline)
  "Return the gate item for PIPELINE.
Before the first gate the item remains informational rather than visitable."
  (let ((gate (cube-get pipeline 'gate)))
    (let ((bead (cube-get gate 'bead)))
      (list :type (if bead 'bead 'pipeline-gate) :id (cube--string bead) :data gate
            :label (format "%s  bead %s  %s"
                           (cube--string (cube-get gate 'n))
                           (if bead (cube--string bead) "-")
                           (cube-pipeline--gate-verdict pipeline))))))

(defun cube-pipeline--render-list ()
  "Render the all-pipelines list in the current buffer."
  (magit-insert-section (cube-pipeline-list-root)
    (magit-insert-heading (format "Pipelines (%d)" (length cube-pipelines--cache)))
    (cube-key-legend-insert 'cube-pipeline-mode)
    (cond
     (cube-pipelines--error
      (insert "  " (propertize cube-pipelines--error 'face 'error) "\n"))
     (cube-pipelines--cache
      (dolist (pipeline cube-pipelines--cache)
        (let ((item (cube-pipeline--row-item pipeline)))
          (magit-insert-section (cube-pipeline-list-item item)
          (magit-insert-heading
           (format "%s  stage %s  iteration %s  gate %s  kill %s"
                   (cube--string (cube-get pipeline 'title))
                   (cube--string (cube-get pipeline 'stage))
                   (cube--string (cube-get pipeline 'iteration))
                   (cube-pipeline--gate-verdict pipeline)
                   (cube-pipeline--kill-text pipeline)))
            (insert "  Next: " (cube--string (cube-get pipeline 'next)) "\n\n")))))
     (t (insert "  loading pipeline status...\n")))))

(defun cube-pipeline--render-show (pipeline)
  "Render one PIPELINE status record in the current buffer."
  (magit-insert-section (cube-pipeline-root)
    (magit-insert-heading (cube--string (cube-get pipeline 'title)))
    (insert (format "Epic: %s  Stage: %s  Iteration: %s  Status: %s  Kill: %s\n\n"
                    (cube-pipeline--id pipeline)
                    (cube--string (cube-get pipeline 'stage))
                    (cube--string (cube-get pipeline 'iteration))
                    (cube--string (cube-get pipeline 'status))
                    (cube-pipeline--kill-text pipeline)))
    (cube-pipeline--insert-group 'stages "Stages" (cube-get pipeline 'stages)
                                 "no stage records" #'cube-pipeline--stage-item)
    (cube-pipeline--insert-group 'experiments "Experiments"
                                 (cube-get pipeline 'experiments) "no experiments"
                                 #'cube-pipeline--experiment-item)
    (cube-pipeline--insert-group 'gate "Gate"
                                 (list (cube-pipeline--gate-item pipeline)) "no gate yet")
    (magit-insert-section (cube-pipeline-next)
      (magit-insert-heading "Next")
      (insert "  " (cube--string (cube-get pipeline 'next)) "\n"))))

(defun cube-pipeline--render ()
  "Render the current pipeline view, including a bounded failure in place."
  (let ((inhibit-read-only t) (line (line-number-at-pos)) (column (current-column)))
    (erase-buffer)
    (cond
     ((eq cube-pipeline--view 'list) (cube-pipeline--render-list))
     (cube-pipeline--error
      (magit-insert-section (cube-pipeline-error-root)
        (magit-insert-heading
         (format "Pipeline: %s" (cube-pipeline--id cube-pipeline--pipeline)))
        (insert "  " (propertize cube-pipeline--error 'face 'error) "\n")))
     (cube-pipeline--pipeline (cube-pipeline--render-show cube-pipeline--pipeline))
     (t
      (magit-insert-section (cube-pipeline-loading-root)
        (magit-insert-heading "Pipeline")
        (insert "  loading pipeline status...\n"))))
    (goto-char (point-min))
    (forward-line (1- line))
    (move-to-column column)))

;;;; New-pipeline transient and guarded plan

(defun cube-pipeline--new-args (plist &optional flag)
  "Construct `cube pipeline new' arguments from PLIST.
TITLE, TARGET, SUCCESS and FROM-MAIL are required.  FLAG selects the write
mode and defaults to `--dry-run'."
  (let ((title (string-trim (cube--string (plist-get plist :title))))
        (target (string-trim (cube--string (plist-get plist :target))))
        (from-mail (string-trim (cube--string (plist-get plist :from-mail))))
        (success (seq-filter (lambda (item) (not (string-empty-p (string-trim item))))
                             (plist-get plist :success))))
    (when (string-empty-p title) (user-error "cube: a pipeline needs a title"))
    (when (string-empty-p target) (user-error "cube: a pipeline needs a target date"))
    (unless success (user-error "cube: a pipeline needs a success criterion"))
    (when (string-empty-p from-mail) (user-error "cube: a pipeline needs sent-mail words"))
    (append (list "pipeline" "new" "--title" title "--target" target)
            (apply #'append (mapcar (lambda (item) (list "--success" item)) success))
            (list "--from-mail" from-mail)
            (when-let* ((person (plist-get plist :person))) (list "--person" person))
            (when-let* ((project (plist-get plist :project))) (list "--project" project))
            (when-let* ((privacy (plist-get plist :privacy))) (list "--privacy" privacy))
            (list (or flag "--dry-run")))))

(defun cube-pipeline--advance-args (epic &optional flag)
  "Construct `cube pipeline advance' arguments for EPIC.
FLAG selects the write mode and defaults to `--dry-run'."
  (list "pipeline" "advance" (cube-pipeline--id epic) (or flag "--dry-run")))

(defun cube-pipeline--show-plan (label args json &optional epic)
  "Show LABEL, dry-run ARGS and JSON in a pipeline plan buffer.
EPIC identifies the result to open after an applied new pipeline."
  (with-current-buffer (get-buffer-create "*cube-pipeline-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (format "Pipeline plan: %s\n\nCommand\n  cube %s --json\n\nResult\n"
                      label (string-join args " ")))
      (insert (pp-to-string json))
      (insert "\na  Apply this plan\n")
      (setq-local cube-pipeline--plan-args args)
      (setq-local cube-pipeline--pipeline (and epic (list (cons 'epic epic))))
      (goto-char (point-min)))
    (special-mode)
    (use-local-map (copy-keymap special-mode-map))
    (local-set-key (kbd "a") #'cube-pipeline-plan-apply)
    (ignore-errors (pop-to-buffer (current-buffer)))))

(defun cube-pipeline--show-plan-failure (label args code err)
  "Render a bounded failure for planned LABEL ARGS in the plan buffer."
  (with-current-buffer (get-buffer-create "*cube-pipeline-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (format "Pipeline plan: %s\n\nCommand\n  cube %s --json\n\n"
                      label (string-join args " ")))
      (insert (propertize (format "cube: %s failed (%s): %s\n" label code err)
                          'face 'error))
      (goto-char (point-min)))
    (special-mode)
    (ignore-errors (pop-to-buffer (current-buffer)))))

(defun cube-pipeline-plan-apply ()
  "Apply the pipeline command previewed in this plan buffer."
  (interactive)
  (unless cube-pipeline--plan-args (user-error "cube: no pipeline plan is available"))
  (let* ((base (seq-remove (lambda (arg) (member arg '("--dry-run" "--apply")))
                           cube-pipeline--plan-args))
         (is-new (equal (seq-take base 2) '("pipeline" "new"))))
    (cube--call-json-async
     (append base '("--apply"))
     (lambda (json)
       (let ((epic (or (cube-get json 'epic)
                       (and cube-pipeline--pipeline
                            (cube-pipeline--id cube-pipeline--pipeline)))))
         (cube-pipelines-refresh)
         (if (and is-new epic)
             (cube-pipeline-show epic)
           (when epic (cube-pipeline-show epic)))
         (message "cube: pipeline plan applied")))
     (lambda (code err)
       (cube-pipeline--show-plan-failure "apply" (append base '("--apply")) code err)))))

(defun cube-pipeline--new-set (key value &optional append)
  "Set KEY to VALUE in the new-pipeline transient, APPENDing when requested."
  (setq cube-pipeline--new-plist
        (plist-put cube-pipeline--new-plist key
                   (if append (append (plist-get cube-pipeline--new-plist key) (list value)) value)))
  (message "cube: %s %s" (substring (symbol-name key) 1) value))

(defun cube-pipeline-new-set-title ()
  "Set the new pipeline title."
  (interactive)
  (cube-pipeline--new-set :title (read-string "Pipeline title: ")))

(defun cube-pipeline-new-set-target ()
  "Set the new pipeline target date."
  (interactive)
  (cube-pipeline--new-set :target (org-read-date nil nil nil "Target date: ")))

(defun cube-pipeline-new-add-success ()
  "Add one success criterion to the new pipeline."
  (interactive)
  (cube-pipeline--new-set :success (read-string "Success criterion: ") t))

(defun cube-pipeline-new-set-from-mail ()
  "Set sent-mail subject words or recipient for the new pipeline."
  (interactive)
  (cube-pipeline--new-set :from-mail (read-string "Sent-mail subject words or recipient: ")))

(defun cube-pipeline-new-set-person ()
  "Set the optional person for the new pipeline."
  (interactive)
  (let* ((choices (mapcar (lambda (person)
                            (cons (format "%s (%s)" (cube-get person 'name)
                                          (cube-get person 'slug))
                                  (cube-get person 'slug)))
                          (cube-org-people)))
         (choice (completing-read "Person: " choices nil t)))
    (cube-pipeline--new-set :person (or (cdr (assoc choice choices)) choice))))

(defun cube-pipeline-new-set-project ()
  "Set the optional project for the new pipeline."
  (interactive)
  (let* ((choices (mapcar (lambda (project)
                            (cons (format "%s (%s)" (cube-get project 'name)
                                          (cube-get project 'slug))
                                  (cube-get project 'slug)))
                          (cube-projects)))
         (choice (completing-read "Project: " choices nil t)))
    (cube-pipeline--new-set :project (or (cdr (assoc choice choices)) choice))))

(defun cube-pipeline-new-set-privacy ()
  "Set the privacy class for the new pipeline."
  (interactive)
  (cube-pipeline--new-set
   :privacy (completing-read "Privacy: " '("public" "internal" "local-only") nil t
                              nil nil (or (plist-get cube-pipeline--new-plist :privacy)
                                          "internal"))))

(defun cube-pipeline-new-execute ()
  "Preview the new pipeline command in a plan buffer."
  (interactive)
  (let ((args (cube-pipeline--new-args cube-pipeline--new-plist)))
    (cube--call-json-async
     args
     (lambda (json) (cube-pipeline--show-plan "new pipeline" args json))
     (lambda (code err) (cube-pipeline--show-plan-failure "new pipeline" args code err)))))

(transient-define-prefix cube-pipeline-new-menu ()
  "Collect a research pipeline and preview its backend plan."
  ["Pipeline"
   ("t" "Title" cube-pipeline-new-set-title)
   ("d" "Target date" cube-pipeline-new-set-target)
   ("s" "Add success criterion" cube-pipeline-new-add-success)
   ("m" "From sent mail" cube-pipeline-new-set-from-mail)
   ("p" "Person" cube-pipeline-new-set-person)
   ("P" "Project" cube-pipeline-new-set-project)
   ("v" "Privacy" cube-pipeline-new-set-privacy)]
  ["Execute"
   ("RET" "Preview" cube-pipeline-new-execute)
   ("q" "Quit" transient-quit-one)])

(defun cube-pipeline-new ()
  "Start the transient for a research pipeline."
  (interactive)
  (setq cube-pipeline--new-plist '(:privacy "internal"))
  (transient-setup 'cube-pipeline-new-menu))

;;;; Commands and mode

(defun cube-pipeline--current-item ()
  "Return the selected pipeline or bead item, if any."
  (when-let* ((section (magit-current-section)))
    (let ((value (oref section value)))
      (and (listp value) (plist-get value :type) value))))

(defun cube-pipeline-visit ()
  "Open a selected bead or pipeline, or toggle the current section."
  (interactive)
  (let ((item (cube-pipeline--current-item)))
    (pcase (plist-get item :type)
      ('bead (cube-beads-show (plist-get item :id)))
      ('pipeline (cube-pipeline-show (plist-get item :id)))
      (_ (when-let* ((section (magit-current-section))) (magit-section-toggle section))))))

(defun cube-pipeline-revert ()
  "Refresh the active pipeline list or focused pipeline status."
  (interactive)
  (if (eq cube-pipeline--view 'list)
      (cube-pipelines-refresh)
    (let* ((buffer (current-buffer)) (epic (cube-pipeline--id cube-pipeline--pipeline)))
      (unless (string-empty-p epic)
        (cube--call-json-async
         (cube-pipeline--status-args epic)
         (lambda (json)
           (when (buffer-live-p buffer)
             (with-current-buffer buffer
               (setq cube-pipeline--pipeline (cube-pipeline--object json)
                     cube-pipeline--error nil)
               (cube-pipeline--render))))
         (lambda (code err)
           (when (buffer-live-p buffer)
             (with-current-buffer buffer
               (setq cube-pipeline--error
                     (format "pipeline status failed (%s): %s" code err))
               (cube-pipeline--render)))))))))

(defun cube-pipeline-advance-dry-run ()
  "Show the dry-run transition plan for the focused pipeline."
  (interactive)
  (let ((epic (cube-pipeline--id cube-pipeline--pipeline)))
    (when (string-empty-p epic) (user-error "cube: not a pipeline buffer"))
    (let ((args (cube-pipeline--advance-args epic)))
      (cube--call-json-async
       args
       (lambda (json)
         (cube-pipeline--show-plan (format "advance %s" epic) args json epic))
       (lambda (code err) (cube-pipeline--show-plan-failure "advance" args code err))))))

(defun cube-pipeline-advance (&optional epic)
  "Apply one transition for EPIC and refresh its status.
Outside a focused pipeline buffer, prompt for the epic identifier."
  (interactive
   (list (let ((current (cube-pipeline--id cube-pipeline--pipeline)))
           (if (string-empty-p current)
               (read-string "Pipeline epic: ")
             current))))
  (let ((epic (cube-pipeline--id epic)))
    (when (string-empty-p epic) (user-error "cube: not a pipeline buffer"))
    (if (or (not cube-pipeline-confirm-advance)
            (y-or-n-p (format "Advance pipeline %s? " epic)))
        (cube--call-json-async
         (cube-pipeline--advance-args epic "--apply")
         (lambda (_json)
           (cube-pipelines-refresh)
           (if (eq cube-pipeline--view 'show)
               (cube-pipeline-revert)
             (cube-pipeline-show epic))
           (message "cube: advanced pipeline %s" epic))
         (lambda (code err)
           (setq cube-pipeline--error (format "pipeline advance failed (%s): %s" code err))
           (cube-pipeline--render)))
      (message "cube: pipeline advance cancelled"))))

(defun cube-pipeline-talk ()
  "Talk to the coordinator about the focused pipeline."
  (interactive)
  (cube-agent-talk nil "coordinator"))

(defun cube-pipeline-tell ()
  "Tell the coordinator about the focused pipeline using the shared inbox path."
  (interactive)
  (cube-agent-tell "coordinator" (read-string "Tell coordinator: ")))

(defun cube-pipeline-open-plan ()
  "Open the focused pipeline's v2 plan over the existing host-file helper.
Fall back to plan-v1 when the revised plan is not available yet."
  (interactive)
  (let* ((epic (cube-pipeline--id cube-pipeline--pipeline))
         (v2 (format "runs/pipelines/%s/plan-v2.yaml" epic))
         (path (if (file-exists-p (cube-host-file-name v2)) v2
                 (format "runs/pipelines/%s/plan-v1.yaml" epic))))
    (find-file (cube-host-file-name path))))

(defun cube-pipeline-rehearse ()
  "Run `cube pipeline rehearse' in a visible rolodex shell transcript."
  (interactive)
  (let* ((name "pipeline-rehearsal")
         (session (cube-rolodex-start 'shell name))
         (command (cube--shell-join (append (cube--program-args)
                                             '("pipeline" "rehearse")))))
    (cube-term-send-string (cube-session-buffer session) (concat command "\n"))))

(defvar cube-pipeline-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map magit-section-mode-map)
    (define-key map (kbd "g") #'cube-pipeline-revert)
    (define-key map (kbd "RET") #'cube-pipeline-visit)
    (define-key map (kbd "A") #'cube-pipeline-advance)
    (define-key map (kbd "d") #'cube-pipeline-advance-dry-run)
    (define-key map (kbd "T") #'cube-pipeline-talk)
    (define-key map (kbd "t") #'cube-pipeline-tell)
    (define-key map (kbd "o") #'cube-pipeline-open-plan)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap for `cube-pipeline-mode'.")

(defconst cube-pipeline-mode-key-help
  '(("RET" . "open") ("A" . "advance") ("d" . "advance dry-run") ("T" . "talk")
    ("t" . "tell") ("o" . "open plan") ("g" . "refresh"))
  "Key legend of `cube-pipeline-mode', proved against its keymap by the tests.")

(cube-key-legend-register 'cube-pipeline-mode)

(define-derived-mode cube-pipeline-mode magit-section-mode "cube-pipeline"
  "One research pipeline or the pipeline list."
  (setq-local revert-buffer-function (lambda (&rest _) (cube-pipeline-revert))))

(defun cube-pipeline-list ()
  "Show all research pipelines in the *cube-pipelines* buffer."
  (interactive)
  (with-current-buffer (get-buffer-create "*cube-pipelines*")
    (unless (derived-mode-p 'cube-pipeline-mode) (cube-pipeline-mode))
    (setq cube-pipeline--view 'list cube-pipeline--error nil)
    (cube-pipeline--render)
    (pop-to-buffer (current-buffer)))
  (cube-pipelines-refresh))

(defun cube-pipeline-show (epic)
  "Show research pipeline EPIC in its focused status buffer."
  (interactive
   (list (let* ((choices (mapcar (lambda (pipeline)
                                   (cons (format "%s (%s)" (cube-get pipeline 'title)
                                                 (cube-pipeline--id pipeline))
                                         (cube-pipeline--id pipeline)))
                                 cube-pipelines--cache))
                (choice (completing-read "Pipeline: " choices nil t)))
           (or (cdr (assoc choice choices)) choice))))
  (let* ((id (cube-pipeline--id epic))
         (cached (if (stringp epic)
                     (seq-find (lambda (pipeline) (equal (cube-pipeline--id pipeline) epic))
                               cube-pipelines--cache)
                   epic))
         (buffer (get-buffer-create (format "*cube-pipeline: %s*" id))))
    (with-current-buffer buffer
      (unless (derived-mode-p 'cube-pipeline-mode) (cube-pipeline-mode))
      (setq cube-pipeline--view 'show
            cube-pipeline--pipeline (or cached (list (cons 'epic id) (cons 'title id)))
            cube-pipeline--error nil)
      (cube-pipeline--render))
    (pop-to-buffer buffer)
    (with-current-buffer buffer (cube-pipeline-revert))))

(provide 'cube-pipeline)
;;; cube-pipeline.el ends here
