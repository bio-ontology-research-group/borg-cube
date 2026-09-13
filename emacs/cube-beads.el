;;; cube-beads.el --- Beads (bd) work items in the cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, outlines

;;; Commentary:

;; Beads are the work ledger of borg-cube (the `bd' program on the host).
;; This file lists ready beads in a tabulated list, renders one bead as
;; org text, and wraps the three write actions (claim, close, create)
;; behind a confirmation prompt.  Reads prefer the `cube' program
;; (`cube ready --json', `cube beads show ID --json') and fall back to
;; `bd' itself, which is what makes the cockpit usable before the backend
;; implements every command.  Writes always go to `bd' on the host.
;;
;; Org integration: the `bead:' link type, an org-capture template under
;; key "b" that creates the bead when the capture is finalised, and
;; `cube-beads-from-heading' for turning an existing heading into a bead.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'tabulated-list)
(require 'org)
(require 'transient)
(require 'cube-core)

(declare-function org-capture-get "org-capture" (prop &optional local))
(declare-function cube-org-open-person "cube-org" (slug))
(declare-function cube-org-people "cube-org" (&optional refresh))
(declare-function cube-projects "cube-project" (&optional refresh))
(declare-function cube-run-bead "cube-rolodex" (role &optional bead resume-id))
(declare-function cube-menu--context-items "cube-menu" (type))
(defvar org-capture-templates)
(defvar org-capture-before-finalize-hook)

(defcustom cube-beads-program "bd"
  "Name of the beads command line program on the host."
  :type 'string
  :group 'borg-cube)

(defcustom cube-beads-inbox-file "~/org/inbox.org"
  "Org file that receives captured beads (on this machine)."
  :type 'file
  :group 'borg-cube)

(defcustom cube-beads-confirm-writes t
  "When non-nil ask before claiming, closing or creating a bead."
  :type 'boolean
  :group 'borg-cube)

(defcustom cube-beads-default-labels nil
  "Labels added to every bead created from the cockpit."
  :type '(repeat string)
  :group 'borg-cube)

(defconst cube-beads-types '("task" "epic" "chore" "bug" "feature" "decision")
  "Bead types accepted by `bd create'.")

(defvar cube-beads--cache nil
  "Ready beads from the last successful list refresh (normalised).")

(defvar cube-beads--assign-bead nil
  "Bead id currently being assigned through the transient.")

(defvar cube-beads--assign-plist nil
  "Fields collected by the assignment transient.")

(defvar cube-beads--create-plist nil
  "Fields collected by the cube-backed creation transient.")

;;;; Normalisation (pure)

(defun cube-beads--label-value (labels prefix)
  "Return the value of the first label in LABELS starting with PREFIX:, or nil."
  (let ((pre (concat prefix ":")))
    (seq-some (lambda (l)
                (and (stringp l) (string-prefix-p pre l)
                     (substring l (length pre))))
              labels)))

(defun cube-beads--normalize (bead)
  "Return BEAD (from `cube ready' or from `bd --json') as one flat alist.
Keys: id title type kind stage priority labels parent student deadline
assignee status description updated.  Missing fields are nil."
  (let* ((labels (cube-get bead 'labels))
         (get (lambda (&rest keys) (seq-some (lambda (k) (cube-get bead k)) keys))))
    (list (cons 'id (cube-get bead 'id))
          (cons 'title (cube-get bead 'title))
          (cons 'type (funcall get 'type 'issue_type))
          (cons 'kind (or (cube-get bead 'kind) (cube-beads--label-value labels "kind")))
          (cons 'stage (or (cube-get bead 'stage) (cube-beads--label-value labels "stage")))
          (cons 'priority (cube-get bead 'priority))
          (cons 'labels labels)
          (cons 'parent (funcall get 'parent 'parent_id))
          (cons 'student (or (cube-get bead 'student)
                             (cube-beads--label-value labels "student")
                             (cube-beads--label-value labels "person")))
          (cons 'deadline (funcall get 'deadline 'due))
          (cons 'assignee (cube-get bead 'assignee))
          (cons 'role (or (cube-get bead 'role)
                          (cube-beads--label-value labels "role")))
          (cons 'resume_id (or (cube-get bead 'resume_id)
                               (cube-get bead 'resume-id)))
          (cons 'status (cube-get bead 'status))
          (cons 'description (cube-get bead 'description))
          (cons 'updated (funcall get 'updated_at 'updated)))))

(defun cube-beads--normalize-list (json)
  "Return the normalised beads in JSON, a `cube ready' object or a `bd' array."
  (mapcar #'cube-beads--normalize
          (cond ((and (consp json) (assq 'beads json)) (cube-get json 'beads))
                ((and (consp json) (consp (car json)) (symbolp (caar json))
                      (assq 'id json))
                 (list json))
                (t json))))

(defun cube-beads--first (json)
  "Return the single bead in JSON, which may be an object or a one element array."
  (cond ((null json) nil)
        ((and (consp json) (consp (car json)) (symbolp (caar json))) json)
        (t (car json))))

;;;; Argument builders (pure)

(defun cube-beads--show-args (id)
  "Return the `bd show' argv for bead ID."
  (list cube-beads-program "show" id "--json"))

(defun cube-beads--ready-args ()
  "Return the `bd ready' argv."
  (list cube-beads-program "ready" "--json"))

(defun cube-beads--claim-args (id)
  "Return the argv that claims bead ID."
  (list cube-beads-program "update" id "--claim" "--json"))

(defun cube-beads--close-args (id reason)
  "Return the argv that closes bead ID with REASON."
  (append (list cube-beads-program "close" id)
          (when (and reason (not (string-empty-p reason))) (list "--reason" reason))
          (list "--json")))

(defun cube-beads--bd-create-args (plist)
  "Return the `bd create' argv for PLIST.
PLIST keys: :title (required) :type :priority :labels (list) :parent
:description.  The command prints only the new id (--silent)."
  (let ((title (or (plist-get plist :title) (error "cube: bead needs a :title")))
        (labels (append cube-beads-default-labels (plist-get plist :labels))))
    (append (list cube-beads-program "create" title
                  "-t" (or (plist-get plist :type) "task")
                  "-p" (format "%s" (or (plist-get plist :priority) 2)))
            (when labels (list "-l" (string-join labels ",")))
            (when-let* ((parent (plist-get plist :parent)))
              (unless (string-empty-p parent) (list "--parent" parent)))
            (when-let* ((desc (plist-get plist :description)))
              (unless (string-empty-p (string-trim desc)) (list "-d" desc)))
            (list "--silent"))))

(defun cube-beads--assign-args (bead plist &optional flag)
  "Return `cube assign' ARGS for BEAD and option PLIST.
PLIST keys are :role, :person, :project, :deadline, :priority, :note
and :run.  FLAG is `--dry-run' or `--apply' and defaults to dry-run."
  (append (list "assign" bead)
          (when-let* ((role (plist-get plist :role))) (list "--role" role))
          (when-let* ((person (plist-get plist :person))) (list "--person" person))
          (when-let* ((project (plist-get plist :project))) (list "--project" project))
          (when-let* ((deadline (plist-get plist :deadline)))
            (list "--deadline" deadline))
          (when-let* ((priority (plist-get plist :priority)))
            (list "--priority" (format "%s" priority)))
          (when-let* ((note (plist-get plist :note))) (list "--note" note))
          (when (plist-get plist :run) (list "--run"))
          (list (or flag "--dry-run"))))

(defun cube-beads--cube-create-args (plist &optional flag)
  "Return `cube create' ARGS for PLIST, defaulting to dry-run.
PLIST keys are :title, :kind, :role, :person, :project, :deadline,
:priority, :privacy, :acceptance and :provenance.  A valid backend
creation needs at least one acceptance line and provenance entry."
  (let ((title (or (plist-get plist :title) (user-error "cube: bead needs a title")))
        (acceptance (plist-get plist :acceptance))
        (provenance (plist-get plist :provenance)))
    (unless (and acceptance
                 (or (and (stringp acceptance) (not (string-empty-p (string-trim acceptance))))
                     (and (listp acceptance) (seq-some #'identity acceptance))))
      (user-error "cube: bead needs an acceptance line"))
    (unless (and provenance (seq-some #'identity provenance))
      (user-error "cube: bead needs provenance"))
    (append (list "create" "--title" title "--kind" (or (plist-get plist :kind) "task"))
            (when-let* ((role (plist-get plist :role))) (list "--role" role))
            (when-let* ((person (plist-get plist :person))) (list "--person" person))
            (when-let* ((project (plist-get plist :project))) (list "--project" project))
            (when-let* ((deadline (plist-get plist :deadline)))
              (list "--deadline" deadline))
            (when-let* ((priority (plist-get plist :priority)))
              (list "--priority" (format "%s" priority)))
            (when-let* ((privacy (plist-get plist :privacy))) (list "--privacy" privacy))
            (cond ((stringp acceptance) (list "--acceptance" acceptance))
                  (t (apply #'append (mapcar (lambda (line) (list "--acceptance" line))
                                             acceptance))))
            (apply #'append (mapcar (lambda (source) (list "--provenance" source))
                                    (if (listp provenance) provenance (list provenance))))
            (list (or flag "--dry-run")))))

(defun cube-beads--create-args (plist)
  "Return creation ARGS for PLIST.
Legacy PLISTs with `:type' use the bd compatibility command used by
org capture; cube-backed PLISTs with `:kind', `:acceptance' or
`:provenance' use `cube create'."
  (if (or (plist-member plist :kind)
          (plist-member plist :acceptance)
          (plist-member plist :provenance))
      (cube-beads--cube-create-args plist)
    (cube-beads--bd-create-args plist)))

;;;; Rendering (pure)

(defun cube-beads--org-escape-body (text)
  "Return TEXT safe to embed under an org heading.
Lines starting with an asterisk get a leading space and markdown fences
become source blocks."
  (let ((in-fence nil))
    (mapconcat
     (lambda (line)
       (cond
        ((string-match "\\````[ \t]*\\([A-Za-z0-9_+-]*\\)" line)
         (if in-fence
             (progn (setq in-fence nil) "#+end_src")
           (setq in-fence t)
           (let ((lang (match-string 1 line)))
             (if (string-empty-p lang) "#+begin_src" (concat "#+begin_src " lang)))))
        ((string-prefix-p "*" line) (concat " " line))
        (t line)))
     (split-string (or text "") "\n") "\n")))

(defun cube-beads--org-link (id &optional title)
  "Return an org link to bead ID with optional TITLE."
  (if (and title (not (string-empty-p title)))
      (format "[[bead:%s][%s]]" id title)
    (format "[[bead:%s]]" id)))

(defun cube-beads--render-org (bead)
  "Return BEAD (a parsed `bd show' object) rendered as org text."
  (let* ((b (cube-beads--normalize bead))
         (id (cube--string (alist-get 'id b)))
         (title (cube--string (alist-get 'title b)))
         (labels (alist-get 'labels b))
         (parent (alist-get 'parent b))
         (deps (cube-get bead 'dependencies))
         (dependents (cube-get bead 'dependents))
         (comments (cube-get bead 'comments)))
    (with-temp-buffer
      (insert (format "#+title: %s: %s\n\n" id title))
      (insert (format "* %s\n" title))
      (insert ":PROPERTIES:\n")
      (insert (format ":BEAD: %s\n" id))
      (dolist (pair `((:STATUS: . ,(alist-get 'status b))
                      (:TYPE: . ,(alist-get 'type b))
                      (:KIND: . ,(alist-get 'kind b))
                      (:STAGE: . ,(alist-get 'stage b))
                      (:PRIORITY: . ,(alist-get 'priority b))
                      (:STUDENT: . ,(alist-get 'student b))
                      (:DEADLINE: . ,(alist-get 'deadline b))
                      (:ASSIGNEE: . ,(alist-get 'assignee b))
                      (:UPDATED: . ,(alist-get 'updated b))))
        (let ((v (cube--string (cdr pair))))
          (unless (string-empty-p v)
            (insert (format "%s %s\n" (car pair) v)))))
      (when labels
        (insert (format ":LABELS: %s\n" (string-join (mapcar #'cube--string labels) " "))))
      (when (and parent (not (string-empty-p (cube--string parent))))
        (insert (format ":PARENT: %s\n" (cube-beads--org-link (cube--string parent)))))
      (insert ":END:\n\n")
      (let ((desc (alist-get 'description b)))
        (when (and desc (not (string-empty-p (string-trim desc))))
          (insert (cube-beads--org-escape-body desc) "\n\n")))
      (when deps
        (insert "** Depends on\n")
        (dolist (d deps)
          (insert (format "- %s (%s)\n"
                          (cube-beads--org-link (cube--string (cube-get d 'id))
                                                (cube-get d 'title))
                          (cube--string (cube-get d 'status)))))
        (insert "\n"))
      (when dependents
        (insert "** Blocks\n")
        (dolist (d dependents)
          (insert (format "- %s (%s)\n"
                          (cube-beads--org-link (cube--string (cube-get d 'id))
                                                (cube-get d 'title))
                          (cube--string (cube-get d 'status)))))
        (insert "\n"))
      (when comments
        (insert "** Comments\n")
        (dolist (c comments)
          (insert (format "- %s, %s ::\n  %s\n"
                          (cube--string (or (cube-get c 'author) "?"))
                          (cube--string (or (cube-get c 'created_at) (cube-get c 'ts)))
                          (replace-regexp-in-string
                           "\n" "\n  " (cube--string (or (cube-get c 'text)
                                                         (cube-get c 'body))))))))
      (buffer-string))))

;;;; Fetching (cube first, bd as fallback)

(defun cube-beads--fetch-ready (callback &optional error-callback)
  "Fetch the ready beads and call CALLBACK with the normalised list.
Tries `cube ready --json' first and `bd ready --json' when that fails.
ERROR-CALLBACK receives (CODE MESSAGE) when both fail."
  (cube--call-json-async
   '("ready")
   (lambda (json) (funcall callback (cube-beads--normalize-list json)))
   (lambda (code err)
     (cube-log "cube ready failed (%s): %s; trying bd" code err)
     (cube--call-text-async
      (cube-beads--ready-args)
      (lambda (out)
        (condition-case e
            (funcall callback (cube-beads--normalize-list (cube--parse-json-string out)))
          (error (if error-callback
                     (funcall error-callback -1 (error-message-string e))
                   (cube-log "bd ready: %s" (error-message-string e))))))
      error-callback))))

(defun cube-beads--fetch-bead (id callback &optional error-callback)
  "Fetch bead ID and call CALLBACK with the parsed object.
Tries `cube beads show ID --json' first and `bd show ID --json' when
that fails.  ERROR-CALLBACK receives (CODE MESSAGE) when both fail."
  (cube--call-json-async
   (list "beads" "show" id)
   (lambda (json) (funcall callback (cube-beads--first json)))
   (lambda (_code _err)
     (cube--call-text-async
      (cube-beads--show-args id)
      (lambda (out)
        (condition-case e
            (funcall callback (cube-beads--first (cube--parse-json-string out)))
          (error (if error-callback
                     (funcall error-callback -1 (error-message-string e))
                   (cube-log "bd show %s: %s" id (error-message-string e))))))
      error-callback))))

;;;; Write actions

(defun cube-beads--confirm (prompt)
  "Return non-nil when the write described by PROMPT may proceed."
  (or (not cube-beads-confirm-writes) (y-or-n-p prompt)))

(defun cube-beads--run-write (argv what &optional callback)
  "Run ARGV on the host for the write action WHAT, then call CALLBACK.
CALLBACK receives the trimmed stdout.  Failures are shown as messages."
  (message "cube: %s..." what)
  (cube--call-text-async
   argv
   (lambda (out)
     (message "cube: %s done" what)
     (cube-beads--revert-list)
     (when callback (funcall callback (string-trim out))))
   (lambda (code err)
     (message "cube: %s failed (%s): %s" what code err))))

(defun cube-beads--revert-list ()
  "Refresh the *cube-beads* buffer if it exists."
  (when-let* ((buf (get-buffer "*cube-beads*")))
    (with-current-buffer buf
      (when (derived-mode-p 'cube-beads-mode) (cube-beads--refresh)))))

(defun cube-beads-claim (id)
  "Claim bead ID (`bd update ID --claim' on the host)."
  (interactive (list (cube-beads--read-id "Claim bead: ")))
  (when (cube-beads--confirm (format "Claim %s? " id))
    (cube-beads--run-write (cube-beads--claim-args id) (format "claim %s" id))))

(defun cube-beads-close (id reason)
  "Close bead ID with REASON (`bd close ID --reason REASON' on the host)."
  (interactive (let ((id (cube-beads--read-id "Close bead: ")))
                 (list id (read-string (format "Reason for closing %s: " id)))))
  (when (cube-beads--confirm (format "Close %s? " id))
    (cube-beads--run-write (cube-beads--close-args id reason) (format "close %s" id))))

(defun cube-beads-create-async (plist &optional callback)
  "Create a bead from PLIST (see `cube-beads--bd-create-args') on the host.
Ask for confirmation, then call CALLBACK with the new id."
  (when (cube-beads--confirm (format "Create bead %S? " (plist-get plist :title)))
    (cube-beads--run-write (cube-beads--bd-create-args plist)
                           (format "create %S" (plist-get plist :title))
                           (lambda (out)
                             (let ((id (car (last (split-string out "\n" t)))))
                               (message "cube: created %s" id)
                               (when callback (funcall callback id)))))
    t))

(defun cube-beads--create-sync (plist)
  "Create a bead from PLIST synchronously and return its id."
  (let ((out (cube--call-text (cube-beads--bd-create-args plist))))
    (car (last (split-string out "\n" t)))))

;;;; Cube-backed writes

(defun cube-beads--show-write-plan (label args json)
  "Show LABEL, ARGS and the parsed JSON result in a small buffer."
  (with-current-buffer (get-buffer-create "*cube-bead-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (format "cube %s dry-run\n\n" label)
              (cube--shell-join (append (cube--program-args) args))
              "\n\n"
              (if (stringp json) json (pp-to-string json)))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-beads--write-cube (args label &optional callback)
  "Run the dry-run ARGS for LABEL, then apply after confirmation.
ARGS may contain either write flag; it is replaced with dry-run and
apply respectively.  CALLBACK receives the parsed applied result."
  (let* ((base (seq-remove (lambda (arg) (member arg '("--dry-run" "--apply"))) args))
         (dry (append base '("--dry-run"))))
    (cube--call-json-async
     dry
     (lambda (json)
       (cube-beads--show-write-plan label dry json)
       (when (cube-beads--confirm (format "Apply cube %s? " label))
         (cube--call-json-async
          (append base '("--apply"))
          (lambda (result)
            (message "cube: %s applied" label)
            (cube-beads--revert-list)
            (when callback (funcall callback result)))
          (lambda (code err)
            (message "cube: %s apply failed (%s): %s" label code err)))))
     (lambda (code err)
       (message "cube: %s dry-run failed (%s): %s" label code err)))))

(defconst cube-beads--role-fallback
  '("advisor" "auditor" "concierge" "editor" "group-leader" "lecturer" "liaison"
    "marshal" "programmer" "scribe" "secretary" "senior" "sentinel" "sysadmin"
    "student-researcher" "student-reviewer" "grant-writer")
  "Role names available when the local roles directory cannot be read.")

(defun cube-beads--role-names ()
  "Return role names from the local roles directory or its known fallback."
  (let ((directory (expand-file-name "roles" cube-root)))
    (or (and (null cube-remote-host) (file-directory-p directory)
             (let ((names (mapcar (lambda (file) (file-name-base file))
                                  (directory-files directory nil "\\.yaml\\'"))))
               (setq names (delete "_schema" names))
               (and names (sort names #'string<))))
        (copy-sequence cube-beads--role-fallback))))

(defun cube-beads--completion-value (prompt choices)
  "Read a display value with PROMPT from alist or string CHOICES."
  (let* ((table (if (and choices (consp (car choices))) choices
                  (mapcar (lambda (value) (cons value value)) choices)))
         (choice (completing-read prompt table nil t)))
    (or (cdr (assoc choice table)) choice)))

(defun cube-beads--person-names ()
  "Return completion pairs of person display names and slugs."
  (mapcar (lambda (person)
            (cons (format "%s (%s)" (cube-get person 'name) (cube-get person 'slug))
                  (cube-get person 'slug)))
          (cube-org-people)))

(defun cube-beads--project-names ()
  "Return completion pairs of project display names and slugs."
  (mapcar (lambda (project)
            (cons (format "%s (%s)" (cube-get project 'name) (cube-get project 'slug))
                  (cube-get project 'slug)))
          (condition-case nil (cube-projects) (error nil))))

(defun cube-beads--assign-set (key value)
  "Set assignment KEY to VALUE and report it."
  (setq cube-beads--assign-plist (plist-put cube-beads--assign-plist key value))
  (message "cube: %s %s" (substring (symbol-name key) 1) value))

(defun cube-beads-assign-role ()
  "Set the role in the assignment transient."
  (interactive)
  (cube-beads--assign-set :role (cube-beads--completion-value
                                 "Role: " (cube-beads--role-names))))

(defun cube-beads-assign-person ()
  "Set the person in the assignment transient."
  (interactive)
  (cube-beads--assign-set :person
                          (cube-beads--completion-value "Person: "
                                                        (cube-beads--person-names))))

(defun cube-beads-assign-project ()
  "Set the project in the assignment transient."
  (interactive)
  (cube-beads--assign-set :project
                          (cube-beads--completion-value "Project: "
                                                        (cube-beads--project-names))))

(defun cube-beads-assign-deadline ()
  "Set the deadline in the assignment transient."
  (interactive)
  (cube-beads--assign-set :deadline (org-read-date nil nil nil "Deadline: ")))

(defun cube-beads-assign-note ()
  "Set the note in the assignment transient."
  (interactive)
  (cube-beads--assign-set :note (read-string "Assignment note: ")))

(defun cube-beads--assign-write (&optional run)
  "Dry-run the current assignment, with RUN requesting an immediate run."
  (interactive)
  (unless cube-beads--assign-bead (user-error "cube: no bead selected"))
  (let ((plist (plist-put (copy-sequence cube-beads--assign-plist) :run run)))
    (cube-beads--write-cube
     (cube-beads--assign-args cube-beads--assign-bead plist)
     (format "assign %s" cube-beads--assign-bead))))

(defun cube-beads-assign-apply ()
  "Assign the selected bead after showing a dry-run plan."
  (interactive)
  (cube-beads--assign-write nil))

(defun cube-beads-assign-run ()
  "Assign the selected bead and ask the backend to run it immediately."
  (interactive)
  (cube-beads--assign-write t))

(defun cube-beads--point-id ()
  "Return a bead id at point in a bead or ready-list buffer, if any."
  (cond ((and (boundp 'cube-bead--id) cube-bead--id) cube-bead--id)
        ((or (derived-mode-p 'cube-beads-mode)
             (derived-mode-p 'cube-beads-list-mode))
         (tabulated-list-get-id))
        ((and (fboundp 'cube-dashboard--current-item)
              (let ((item (cube-dashboard--current-item)))
                (and (eq (plist-get item :type) 'bead)
                     (plist-get item :id)))))))

(defun cube-beads-claim-current ()
  "Claim the bead at point in a bead-aware cockpit buffer."
  (interactive)
  (cube-beads-claim
   (or (cube-beads--point-id) (user-error "cube: no bead at point"))))

(defun cube-beads-close-current ()
  "Close the bead at point in a bead-aware cockpit buffer."
  (interactive)
  (let ((id (or (cube-beads--point-id) (user-error "cube: no bead at point"))))
    (cube-beads-close id (read-string (format "Reason for closing %s: " id)))))

(defun cube-beads--start-assign (bead &optional project)
  "Start assignment of BEAD, initially targeting PROJECT when given."
  (setq cube-beads--assign-bead (if (stringp bead) bead (cube-get bead 'id))
        cube-beads--assign-plist (and project (list :project project)))
  (transient-setup 'cube-beads-assign-menu))

(defun cube-beads-assign (&optional bead project)
  "Pick BEAD and start the assignment transient.
When BEAD is omitted, use a bead at point or fetch `cube ready'."
  (interactive)
  (let ((point-id (or bead (cube-beads--point-id))))
    (if point-id
        (cube-beads--start-assign point-id project)
      (cube-beads--fetch-ready
       (lambda (beads)
         (setq cube-beads--cache beads)
         (if beads
             (cube-beads--start-assign
              (completing-read "Assign bead: "
                               (mapcar (lambda (b)
                                         (cons (format "%s %s"
                                                       (alist-get 'id b)
                                                       (alist-get 'title b))
                                               (alist-get 'id b)))
                                       beads)
                               nil t)
              project)
           (user-error "cube: no ready beads")))
       (lambda (code err) (message "cube: ready failed (%s): %s" code err))))))

(transient-define-prefix cube-beads-assign-menu ()
  "Assign a bead with a dry-run and explicit apply gate."
  ["Assignment"
   ("r" "Role" cube-beads-assign-role)
   ("p" "Person" cube-beads-assign-person)
   ("P" "Project" cube-beads-assign-project)
   ("d" "Deadline" cube-beads-assign-deadline)
   ("n" "Note" cube-beads-assign-note)]
  ["Execute"
   ("RET" "Assign" cube-beads-assign-apply)
   ("x" "Assign and run now" cube-beads-assign-run)
   ("q" "Quit" transient-quit-one)])

(defun cube-beads--create-set (key value)
  "Set creation KEY to VALUE and report it."
  (setq cube-beads--create-plist (plist-put cube-beads--create-plist key value))
  (message "cube: %s %s" (substring (symbol-name key) 1) value))

(defun cube-beads-create-set-title ()
  "Set the title in the creation transient."
  (interactive)
  (cube-beads--create-set :title (read-string "Title: ")))

(defun cube-beads-create-set-kind ()
  "Set the kind in the creation transient."
  (interactive)
  (cube-beads--create-set :kind (read-string "Kind: ")))

(defun cube-beads-create-set-role ()
  "Set the role in the creation transient."
  (interactive)
  (cube-beads--create-set :role (cube-beads--completion-value
                                 "Role: " (cube-beads--role-names))))

(defun cube-beads-create-set-person ()
  "Set the person in the creation transient."
  (interactive)
  (cube-beads--create-set :person
                          (cube-beads--completion-value "Person: "
                                                        (cube-beads--person-names))))

(defun cube-beads-create-set-project ()
  "Set the project in the creation transient."
  (interactive)
  (cube-beads--create-set :project
                          (cube-beads--completion-value "Project: "
                                                        (cube-beads--project-names))))

(defun cube-beads-create-set-deadline ()
  "Set the deadline in the creation transient."
  (interactive)
  (cube-beads--create-set :deadline (org-read-date nil nil nil "Deadline: ")))

(defun cube-beads-create-set-priority ()
  "Set the priority in the creation transient."
  (interactive)
  (cube-beads--create-set :priority (read-string "Priority 0-4: ")))

(defun cube-beads-create-set-privacy ()
  "Set privacy in the creation transient."
  (interactive)
  (cube-beads--create-set :privacy (read-string "Privacy (public): " nil nil "public")))

(defun cube-beads-create-set-acceptance ()
  "Set acceptance text in the creation transient."
  (interactive)
  (cube-beads--create-set :acceptance (read-string "Acceptance: ")))

(defun cube-beads-create-set-provenance ()
  "Set a provenance source and locator in the creation transient."
  (interactive)
  (cube-beads--create-set :provenance (list (read-string "Provenance PATH::LOCATOR: "))))

(defun cube-beads-create-execute ()
  "Create the current bead after showing a dry-run plan."
  (interactive)
  (cube-beads--write-cube
   (cube-beads--cube-create-args cube-beads--create-plist)
   "create"))

(transient-define-prefix cube-beads-create-menu ()
  "Create a bead with required acceptance and provenance."
  ["Bead"
   ("t" "Title" cube-beads-create-set-title)
   ("k" "Kind" cube-beads-create-set-kind)
   ("r" "Role" cube-beads-create-set-role)
   ("p" "Person" cube-beads-create-set-person)
   ("P" "Project" cube-beads-create-set-project)
   ("d" "Deadline" cube-beads-create-set-deadline)
   ("i" "Priority" cube-beads-create-set-priority)
   ("y" "Privacy" cube-beads-create-set-privacy)]
  ["Evidence"
   ("a" "Acceptance" cube-beads-create-set-acceptance)
   ("v" "Provenance" cube-beads-create-set-provenance)]
  ["Execute"
   ("x" "Create" cube-beads-create-execute)
   ("q" "Quit" transient-quit-one)])

(defun cube-beads--read-create-plist ()
  "Ask for the fields of a new bead and return them as a plist."
  (let* ((title (read-string "Title: "))
         (type (completing-read "Type (task): " cube-beads-types nil nil nil nil "task"))
         (priority (read-string "Priority 0-4 (2): " nil nil "2"))
         (labels (split-string (read-string "Labels (comma separated): ") "," t "[ \t]+"))
         (parent (read-string "Parent bead (optional): ")))
    (when (string-empty-p title) (user-error "cube: a bead needs a title"))
    (list :title title :type type :priority priority :labels labels
          :parent (unless (string-empty-p parent) parent))))

(defun cube-beads-create ()
  "Start the cube-backed creation transient."
  (interactive)
  (setq cube-beads--create-plist
        (list :title (read-string "Title: ")
              :kind (read-string "Kind (task): " nil nil "task")
              :priority (read-string "Priority 0-4 (2): " nil nil "2")
              :acceptance (read-string "Acceptance: ")
              :provenance (list (read-string "Provenance PATH::LOCATOR: "))))
  (transient-setup 'cube-beads-create-menu))

;;;; Bead buffer

(defvar cube-bead-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "g") #'cube-bead-revert)
    (define-key map (kbd "c") #'cube-bead-claim)
    (define-key map (kbd "k") #'cube-bead-close)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap of `cube-bead-mode'.")

(define-minor-mode cube-bead-mode
  "Minor mode of the read-only bead buffers rendered by `cube-beads-show'."
  :lighter " bead"
  :keymap cube-bead-mode-map)

(defvar-local cube-bead--id nil
  "Bead id shown in this buffer.")

(defun cube-beads--buffer-name (id)
  "Return the buffer name for bead ID."
  (format "*cube-bead: %s*" id))

(defun cube-beads--render-into (buffer bead)
  "Render BEAD into BUFFER as org text and show it."
  (with-current-buffer buffer
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (cube-beads--render-org bead))
      (goto-char (point-min)))
    (unless (derived-mode-p 'org-mode) (org-mode))
    (setq cube-bead--id (cube--string (cube-get bead 'id)))
    (setq buffer-read-only t)
    (cube-bead-mode 1)
    (view-mode 1)
    (when (fboundp 'org-fold-show-all) (org-fold-show-all)))
  (pop-to-buffer buffer))

(defun cube-beads-show (id)
  "Show bead ID as org text in the buffer *cube-bead: ID*."
  (interactive (list (cube-beads--read-id "Show bead: ")))
  (let ((buffer (get-buffer-create (cube-beads--buffer-name id))))
    (message "cube: fetching %s..." id)
    (cube-beads--fetch-bead
     id
     (lambda (bead)
       (if bead
           (cube-beads--render-into buffer bead)
         (message "cube: bead %s not found" id)))
     (lambda (code err) (message "cube: show %s failed (%s): %s" id code err)))))

(defun cube-bead-revert ()
  "Refetch the bead shown in this buffer."
  (interactive)
  (if cube-bead--id (cube-beads-show cube-bead--id) (user-error "cube: not a bead buffer")))

(defun cube-bead-claim ()
  "Claim the bead shown in this buffer."
  (interactive)
  (unless cube-bead--id (user-error "cube: not a bead buffer"))
  (cube-beads-claim cube-bead--id))

(defun cube-bead-close ()
  "Close the bead shown in this buffer."
  (interactive)
  (unless cube-bead--id (user-error "cube: not a bead buffer"))
  (cube-beads-close cube-bead--id (read-string "Reason: ")))

;;;; Ready list

(defvar cube-beads-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'cube-beads-list-show)
    (define-key map (kbd "c") #'cube-beads-list-claim)
    (define-key map (kbd "k") #'cube-beads-list-close)
    (define-key map (kbd "+") #'cube-beads-create)
    (define-key map (kbd "r") #'cube-beads-list-run)
    (define-key map (kbd "s") #'cube-beads-list-student)
    map)
  "Keymap of `cube-beads-mode'.")

(defconst cube-beads-mode-key-help
  '(("RET" . "show") ("c" . "claim") ("k" . "close") ("+" . "create")
    ("r" . "run role") ("s" . "student session"))
  "Key legend of `cube-beads-mode', proved against its keymap by the tests.")

(cube-key-legend-register 'cube-beads-mode)

(define-derived-mode cube-beads-mode tabulated-list-mode "cube-beads"
  "Ready beads from the host."
  ;; The header line carries the key legend, so the column names are printed
  ;; into the buffer instead.
  (setq-local tabulated-list-use-header-line nil)
  (setq tabulated-list-format
        [("Id" 10 t) ("P" 2 t) ("Stage" 10 t) ("Kind" 11 t) ("Student" 12 t)
         ("Due" 11 t) ("Title" 0 t)])
  (setq tabulated-list-padding 1)
  (add-hook 'tabulated-list-revert-hook #'cube-beads--refresh nil t)
  (tabulated-list-init-header)
  (setq-local header-line-format (cube-key-legend-header-line 'cube-beads-mode)))

(defvar cube-beads-list-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map cube-beads-mode-map)
    (define-key map (kbd "g") #'cube-beads--refresh)
    map)
  "Keymap of the named ready-bead list major mode.")

(defconst cube-beads-list-mode-key-help
  (append cube-beads-mode-key-help '(("g" . "refresh")))
  "Key legend of `cube-beads-list-mode': the ready list adds a refresh key.")

(cube-key-legend-register 'cube-beads-list-mode)

(define-derived-mode cube-beads-list-mode cube-beads-mode "cube-beads-list"
  "Named major mode for the ready bead list."
  (setq-local header-line-format (cube-key-legend-header-line 'cube-beads-list-mode)))

(defun cube-beads--entry (bead)
  "Return the tabulated-list entry for the normalised BEAD."
  (list (alist-get 'id bead)
        (vector (cube--string (alist-get 'id bead))
                (cube--string (alist-get 'priority bead))
                (cube--string (alist-get 'stage bead))
                (cube--string (alist-get 'kind bead))
                (cube--string (alist-get 'student bead))
                (cube--string (alist-get 'deadline bead))
                (cube--string (alist-get 'title bead)))))

(defvar cube-beads--row-map
  (let ((map (make-sparse-keymap)))
    (define-key map [mouse-1] #'cube-beads-list-mouse-visit)
    (define-key map [mouse-3] #'cube-beads-list-mouse-context)
    map)
  "Mouse map applied to ready-bead rows.")

(defun cube-beads--install-mouse-actions ()
  "Attach visit and context actions to rendered ready-bead rows."
  (let ((inhibit-read-only t))
    (save-excursion
      (goto-char (point-min))
      (while (not (eobp))
        (when (tabulated-list-get-id)
          (add-text-properties (line-beginning-position) (line-end-position)
                               (list 'mouse-face 'highlight 'keymap cube-beads--row-map
                                     'help-echo "RET opens; r runs an agent bead; mouse-3 shows actions")))
        (forward-line 1)))))

(defun cube-beads--print (beads)
  "Show BEADS in the *cube-beads* buffer."
  (setq cube-beads--cache beads)
  (with-current-buffer (get-buffer-create "*cube-beads*")
    (unless (derived-mode-p 'cube-beads-list-mode) (cube-beads-list-mode))
    (setq tabulated-list-entries (mapcar #'cube-beads--entry beads))
    ;; This is an explicit render after an async fetch.  Passing REVERT here
    ;; would invoke the revert hook and race a second `cube ready' request.
    (tabulated-list-print nil)
    (cube-beads--install-mouse-actions)
    (current-buffer)))

(defun cube-beads--refresh ()
  "Refetch the ready beads into the list buffer."
  (interactive)
  (cube-beads--fetch-ready
   (lambda (beads) (cube-beads--print beads))
   (lambda (code err) (message "cube: ready failed (%s): %s" code err))))

(defun cube-beads-list ()
  "Show the ready beads in *cube-beads*."
  (interactive)
  (pop-to-buffer (cube-beads--print cube-beads--cache))
  (cube-beads--refresh))

(defalias 'cube-beads-ready #'cube-beads-list)

(defun cube-beads--read-id (prompt)
  "Read a bead id with PROMPT, completing over the cached ready beads."
  (let ((at-point (and (derived-mode-p 'cube-beads-mode) (tabulated-list-get-id))))
    (or at-point
        (string-trim
         (completing-read prompt (mapcar (lambda (b) (alist-get 'id b)) cube-beads--cache)
                          nil nil nil nil cube-bead--id)))))

(defun cube-beads-list-show ()
  "Show the bead at point."
  (interactive)
  (cube-beads-show (or (tabulated-list-get-id) (user-error "cube: no bead at point"))))

(defun cube-beads-list-claim ()
  "Claim the bead at point."
  (interactive)
  (cube-beads-claim (or (tabulated-list-get-id) (user-error "cube: no bead at point"))))

(defun cube-beads-list-close ()
  "Close the bead at point."
  (interactive)
  (let ((id (or (tabulated-list-get-id) (user-error "cube: no bead at point"))))
    (cube-beads-close id (read-string (format "Reason for closing %s: " id)))))

(defun cube-beads--agent-role (bead)
  "Return the configured role for BEAD, asking only when it is not recorded."
  (or (alist-get 'role bead)
      (let ((labels (alist-get 'labels bead)))
        (cube-beads--label-value labels "role"))
      (completing-read "Role for this bead: "
                       '("leader" "senior" "programmer" "auditor" "editor" "lecturer"
                         "scribe" "advisor" "sysadmin" "secretary") nil t)))

(defun cube-beads-list-run ()
  "Dry-run and start the agent bead at point through its effective profile."
  (interactive)
  (let* ((bead (cube-beads--current-ready-bead))
         (id (alist-get 'id bead)))
    (cube-run-bead (cube-beads--agent-role bead) id (alist-get 'resume_id bead))))

(defun cube-beads--current-ready-bead ()
  "Return the ready bead at point in a bead list or dashboard context."
  (cond
   ((derived-mode-p 'cube-beads-mode)
    (let ((id (or (tabulated-list-get-id) (user-error "cube: no bead at point"))))
      (or (seq-find (lambda (item) (equal (alist-get 'id item) id)) cube-beads--cache)
          (user-error "cube: bead %s is no longer in the ready list" id))))
   ((and (fboundp 'cube-dashboard--current-item)
         (let ((item (cube-dashboard--current-item)))
           (and (eq (plist-get item :type) 'bead) (plist-get item :data))))
    (cube-beads--normalize (plist-get (cube-dashboard--current-item) :data)))
   (t (user-error "cube: select a ready bead first"))))

(defun cube-beads-list-mouse-visit (event)
  "Open the ready bead row clicked by mouse-1 EVENT."
  (interactive "e")
  (let* ((posn (event-end event)) (window (posn-window posn)) (point (posn-point posn)))
    (when (and (windowp window) (integer-or-marker-p point))
      (with-current-buffer (window-buffer window)
        (goto-char point)
        (cube-beads-list-show)))))

(defun cube-beads-list-mouse-context (event)
  "Show command-table bead actions for the ready-bead row in EVENT."
  (interactive "e")
  (let* ((posn (event-end event)) (window (posn-window posn)) (point (posn-point posn)))
    (when (and (windowp window) (integer-or-marker-p point))
      (with-current-buffer (window-buffer window)
        (goto-char point)
        (when-let* ((items (cube-menu--context-items 'bead))
                    (choice (popup-menu (cons "Bead" items))))
          (call-interactively choice))))))

(defun cube-beads-list-student ()
  "Open the org file of the student behind the bead at point."
  (interactive)
  (let* ((id (or (tabulated-list-get-id) (user-error "cube: no bead at point")))
         (bead (seq-find (lambda (b) (equal (alist-get 'id b) id)) cube-beads--cache))
         (student (and bead (alist-get 'student bead))))
    (if student
        (cube-org-open-person student)
      (user-error "cube: bead %s has no student" id))))

;;;; Org link type bead:

(defun cube-beads-link-follow (path &optional _arg)
  "Follow a bead: link with PATH (the bead id)."
  (cube-beads-show (string-trim path)))

(defun cube-beads-link-store ()
  "Store a bead: link when in a bead buffer.  For `org-store-link'."
  (when (and (boundp 'cube-bead--id) cube-bead--id)
    (let ((title (save-excursion
                   (goto-char (point-min))
                   (and (re-search-forward "^\\* \\(.*\\)$" nil t) (match-string 1)))))
      (org-link-store-props :type "bead"
                            :link (concat "bead:" cube-bead--id)
                            :description (or title cube-bead--id))
      t)))

(defun cube-beads-link-export (path desc backend &optional _info)
  "Export the bead: link PATH with DESC for BACKEND as plain reference text."
  (let ((text (if (and desc (not (string-empty-p desc)))
                  (format "%s (bead %s)" desc path)
                (format "bead %s" path))))
    (pcase backend
      ('html (format "<code>%s</code>" text))
      ('latex (format "\\texttt{%s}" text))
      (_ text))))

(org-link-set-parameters "bead"
                         :follow #'cube-beads-link-follow
                         :store #'cube-beads-link-store
                         :export #'cube-beads-link-export)

;;;; Org headings and capture

(defun cube-beads--org-priority->bd (priority)
  "Map an org PRIORITY character (or nil) to a bd priority number."
  (pcase priority
    (?A 1) (?B 2) (?C 3) (_ 2)))

(defun cube-beads--heading-plist ()
  "Return a bead plist for the org heading at point.
Title is the heading text, tags become labels (plus :LABELS: property
words), :PARENT: names the parent bead, the org priority maps to 1-3 and
the body below the property drawer is the description."
  (save-excursion
    (org-back-to-heading t)
    (let* ((title (org-get-heading t t t t))
           (tags (org-get-tags nil t))
           (labels-prop (org-entry-get nil "LABELS"))
           (parent (org-entry-get nil "PARENT"))
           (type (org-entry-get nil "TYPE"))
           (priority (let ((p (org-entry-get nil "PRIORITY")))
                       (and p (not (string-empty-p p)) (aref p 0))))
           (body (let ((end (save-excursion (org-end-of-subtree t t)))
                       (start (save-excursion (org-end-of-meta-data t) (point))))
                   (if (< start end)
                       (string-trim (buffer-substring-no-properties start end))
                     ""))))
      (list :title (string-trim (substring-no-properties (or title "")))
            :type (or type "task")
            :priority (cube-beads--org-priority->bd priority)
            :labels (append (mapcar #'substring-no-properties tags)
                            (and labels-prop (split-string labels-prop "[ ,]+" t)))
            :parent parent
            :description body))))

(defun cube-beads--capture-finalize (create-fn)
  "Create a bead for the heading in the current capture buffer with CREATE-FN.
CREATE-FN is called with the heading plist and must return the new id,
which is written into the :BEAD: property.  Headings whose :BEAD: is
already a real id are left alone.  Return the id or nil."
  (save-excursion
    (goto-char (point-min))
    (unless (org-at-heading-p) (outline-next-heading))
    (when (org-at-heading-p)
      (let ((existing (org-entry-get nil "BEAD")))
        (when (or (null existing) (string-empty-p existing)
                  (string= existing "pending"))
          (let ((id (funcall create-fn (cube-beads--heading-plist))))
            (when (and id (not (string-empty-p id)))
              (org-set-property "BEAD" id)
              id)))))))

(defun cube-beads-capture-finalize ()
  "Hook for `org-capture-before-finalize-hook': create the captured bead."
  (when (equal (org-capture-get :key) "b")
    (condition-case err
        (let ((cube-beads-confirm-writes nil))
          (cube-beads--capture-finalize #'cube-beads--create-sync))
      (error (message "cube: bead creation failed: %s" (error-message-string err))))))

(defconst cube-beads-capture-template
  '("b" "Bead (borg-cube work item)" entry
    (file cube-beads-inbox-file)
    "* TODO %^{Title}\n:PROPERTIES:\n:BEAD: pending\n:END:\n%?"
    :empty-lines 1)
  "Org capture template that creates a bead when finalised.")

(defun cube-beads-install-capture ()
  "Add the \"b\" capture template and the finalize hook."
  (require 'org-capture)
  (unless (assoc "b" org-capture-templates)
    (add-to-list 'org-capture-templates cube-beads-capture-template t))
  (add-hook 'org-capture-before-finalize-hook #'cube-beads-capture-finalize))

(defun cube-beads-from-heading ()
  "Create a bead from the org heading at point and record its id in :BEAD:."
  (interactive)
  (unless (derived-mode-p 'org-mode) (user-error "cube: not in an org buffer"))
  (let ((existing (org-entry-get nil "BEAD")))
    (when (and existing (not (member existing '("" "pending"))))
      (user-error "cube: heading already has bead %s" existing)))
  (let ((plist (cube-beads--heading-plist))
        (buffer (current-buffer))
        (marker (point-marker)))
    (cube-beads-create-async
     plist
     (lambda (id)
       (when (buffer-live-p buffer)
         (with-current-buffer buffer
           (save-excursion
             (goto-char marker)
             (org-set-property "BEAD" id))))))))

(provide 'cube-beads)
;;; cube-beads.el ends here
