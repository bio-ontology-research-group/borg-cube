;;; cube-review.el --- Approval queue: the only outbound trigger  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, mail

;;; Commentary:

;; Every action of the agents that would reach another person (an email,
;; a Mattermost message, a git push into a shared file) waits in the
;; approval queue of the backend.  This file shows that queue as a
;; magit-section buffer, renders the draft body (markdown or diff), and
;; lets Robert approve, reject or edit an item.
;;
;; `cube approve ID' is the single outbound trigger of the whole cockpit.
;; Email drafts are never sent from here: approving an email hands the
;; body to the Gnus Emacs through `server-eval-at' and
;; `claude-email-compose', which opens a message buffer for Robert to
;; read and send with C-c C-c; the approval is then recorded with
;; `cube approve'.  A test greps the sources for forbidden send commands.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'server)
(require 'magit-section)
(require 'cube-core)
(require 'cube-beads)
(require 'cube-org)

(declare-function markdown-mode "markdown-mode")
(declare-function cube-rolodex-find "cube-rolodex" (name))
(declare-function cube-rolodex--show "cube-rolodex" (buffer))
(declare-function cube-rolodex-attach "cube-rolodex" (name))
(declare-function cube-session-buffer "cube-rolodex" (session))
(declare-function cube-session-run-id "cube-rolodex" (session))
(declare-function cube-rolodex-live-sessions "cube-rolodex" ())

(defcustom cube-review-gnus-server "gnus"
  "Name of the Emacs server that runs Gnus and `claude-email-compose'."
  :type 'string
  :group 'borg-cube)

(defcustom cube-review-local-draft-directory "~/.cache/cube/drafts/"
  "Local directory that receives email bodies handed to Gnus."
  :type 'directory
  :group 'borg-cube)

(defcustom cube-review-confirm t
  "When non-nil ask before approving or rejecting."
  :type 'boolean
  :group 'borg-cube)

(defvar cube-review--approvals nil
  "Approvals from the last successful fetch.")

(defvar cube-review--generated nil
  "Timestamp string of the last successful fetch.")

(defvar cube-review--bodies nil
  "Alist of approval id to body text, filled lazily.")

(defvar cube-review--details nil
  "Alist of approval id to the `cube approvals show' payload.")

(defvar cube-review--error nil
  "Message of the last failed fetch, or nil.")

;;;; Pure helpers

(defun cube-review--id (approval)
  "Return the id of APPROVAL as a string."
  (cube--string (cube-get approval 'id)))

(defun cube-review--body-file (approval)
  "Return the draft body file of APPROVAL (body_file or draft_file)."
  (or (cube-get approval 'body_file) (cube-get approval 'draft_file)))

(defun cube-review--email-p (approval)
  "Return non-nil when APPROVAL is an outbound email."
  (and (equal (cube-get approval 'kind) "outbound")
       (equal (cube-get approval 'channel) "email")))

(defun cube-review--body-mode (approval)
  "Return the major mode symbol used to fontify APPROVAL's body."
  (let ((file (or (cube-review--body-file approval) "")))
    (cond ((string-match-p "\\.\\(diff\\|patch\\)\\'" file) 'diff-mode)
          ((equal (cube-get approval 'channel) "git") 'diff-mode)
          (t 'markdown-mode))))

(defun cube-review--fontify (text mode)
  "Return TEXT fontified with major MODE (falls back to `text-mode')."
  (with-temp-buffer
    (insert text)
    (let ((fn (cond ((and (eq mode 'markdown-mode) (require 'markdown-mode nil t)) mode)
                    ((and (not (eq mode 'markdown-mode)) (fboundp mode)) mode)
                    (t 'text-mode))))
      (delay-mode-hooks (funcall fn))
      (font-lock-ensure))
    (buffer-string)))

(defun cube-review--heading (approval &optional now)
  "Return the one line heading of APPROVAL; NOW is for tests."
  (let ((recipient (cube--string (cube-get approval 'recipient)))
        (age (cube--age-string (cube-get approval 'created) now)))
    (format "%-9s %-8s %-6s %-12s %s%s"
            (cube-review--id approval)
            (cube--string (cube-get approval 'kind))
            (cube--string (cube-get approval 'channel))
            (if (string-empty-p recipient) "-" (concat "-> " recipient))
            (cube--string (cube-get approval 'summary))
            (if (string-empty-p age) "" (concat "  " age)))))

(defun cube-review--email-form (approval body-file)
  "Return the form evaluated in the Gnus Emacs for the email APPROVAL.
BODY-FILE is a local file with the body.  The form calls
`claude-email-compose' (TO SUBJECT BODY-FILE), which opens a message
buffer and does not send."
  (let ((to (or (cube-get approval 'to) (cube-get approval 'recipient_email)
                (cube-get approval 'recipient) ""))
        (subject (or (cube-get approval 'subject) (cube-get approval 'summary) "")))
    (list 'claude-email-compose to subject (expand-file-name body-file))))

(defun cube-review--approve-args (id &optional body-file)
  "Return the `cube approve' args for ID, with an edited BODY-FILE if given."
  (append (list "approve" id)
          (when body-file (list "--body-file" body-file))))

(defun cube-review--reject-args (id &optional reason)
  "Return the `cube reject' args for ID with REASON."
  (append (list "reject" id)
          (when (and reason (not (string-empty-p reason))) (list "--reason" reason))))

(defun cube-review--edited-body-path (id)
  "Return the host path (relative to `cube-root') for the edited body of ID."
  (format "state/drafts/%s.edited.md" id))

(defun cube-review--local-draft-file (id)
  "Return the local file that holds the body of ID for Gnus."
  (expand-file-name (format "%s.md" id) cube-review-local-draft-directory))

(defun cube-review--result-message (json)
  "Return a message for the `cube approve'/`cube reject' payload JSON."
  (format "cube: %s %s: %s%s"
          (cube--string (cube-get json 'action))
          (cube--string (cube-get json 'id))
          (cube--string (cube-get json 'result))
          (let ((m (cube-get json 'message)))
            (if (and m (not (string-empty-p m))) (concat " (" m ")") ""))))

(defun cube-review--merged (approval &optional details)
  "Return APPROVAL with the keys of DETAILS (default: its cached details) on top."
  (let ((details (or details (cdr (assoc (cube-review--id approval) cube-review--details))))
        (merged (copy-sequence approval)))
    (dolist (pair details)
      (when (and (consp pair) (symbolp (car pair)))
        (setf (alist-get (car pair) merged) (cdr pair))))
    merged))

(defun cube-review--find (id)
  "Return the cached approval with ID."
  (seq-find (lambda (a) (equal (cube-review--id a) id)) cube-review--approvals))

;;;; Fetching

(defun cube-review--fetch (callback)
  "Fetch the approval queue and call CALLBACK with no arguments."
  (cube--call-json-async
   '("approvals")
   (lambda (json)
     (setq cube-review--approvals (cube-get json 'approvals)
           cube-review--generated (or (cube-get json 'generated)
                                      (format-time-string "%FT%T%z"))
           cube-review--error nil)
     (funcall callback))
   (lambda (code err)
     (setq cube-review--error (format "approvals failed (%s): %s" code err))
     (cube-log "%s" cube-review--error)
     (funcall callback))))

(defun cube-review--fetch-body (approval callback)
  "Fetch the body of APPROVAL and call CALLBACK with the text.
Tries `cube approvals show ID --json' (key `body'), then the draft file
on the host; unavailable bodies yield a placeholder."
  (let* ((id (cube-review--id approval))
         (cached (assoc id cube-review--bodies)))
    (if cached
        (funcall callback (cdr cached))
      (let ((finish (lambda (text)
                      (let ((text (or text "(body unavailable)")))
                        (push (cons id text) cube-review--bodies)
                        (funcall callback text))))
            (file (cube-review--body-file approval)))
        (cube--call-json-async
         (list "approvals" "show" id)
         (lambda (json)
           (let ((body (cube-get json 'body)))
             (when (consp json)
               (setf (alist-get id cube-review--details nil nil #'equal) json))
             (funcall finish (if (and body (not (string-empty-p body)))
                                 body
                               (and file (cube-host-file-contents file))))))
         (lambda (_code _err)
           (funcall finish (and file (cube-host-file-contents file)))))))))

;;;; Buffer

(defvar cube-review-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map magit-section-mode-map)
    (define-key map (kbd "g") #'cube-review-refresh)
    (define-key map (kbd "RET") #'cube-review-show-body)
    (define-key map (kbd "a") #'cube-review-approve)
    (define-key map (kbd "x") #'cube-review-reject)
    (define-key map (kbd "r") #'cube-review-reject)
    (define-key map (kbd "e") #'cube-review-edit)
    (define-key map (kbd "j") #'cube-review-jump-session)
    (define-key map (kbd "o") #'cube-review-open-target)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap of `cube-review-mode'.")

(defconst cube-review-mode-key-help
  '(("RET" . "show body") ("a" . "approve item") ("x" . "reject") ("e" . "edit")
    ("o" . "open target") ("j" . "jump to session") ("g" . "refresh"))
  "Key legend of `cube-review-mode', proved against its keymap by the tests.")

(cube-key-legend-register 'cube-review-mode)

(define-derived-mode cube-review-mode magit-section-mode "cube-review"
  "Approval queue of the borg-cube backend."
  (setq-local revert-buffer-function (lambda (&rest _) (cube-review-refresh))))

(defun cube-review--insert-item (approval)
  "Insert the section for APPROVAL with its body as a hidden child."
  (let ((id (cube-review--id approval)))
    (magit-insert-section (cube-approval (list :type 'approval :id id :data approval) t)
      (magit-insert-heading (cube-review--heading approval))
      (when-let* ((bead (cube-get approval 'bead)))
        (insert (format "    bead %s" bead))
        (when-let* ((run (cube-get approval 'run_id))) (insert (format ", run %s" run)))
        (insert "\n"))
      (let ((body (assoc id cube-review--bodies)))
        (if body
            (insert (cube-review--fontify (cdr body) (cube-review--body-mode approval)) "\n")
          (insert "    (press RET to load the body)\n"))))))

(defun cube-review--render ()
  "Redraw the *cube-review* buffer from the cached approvals."
  (with-current-buffer (get-buffer-create "*cube-review*")
    (unless (derived-mode-p 'cube-review-mode) (cube-review-mode))
    (let ((inhibit-read-only t)
          (section (magit-current-section))
          (line (line-number-at-pos)))
      (erase-buffer)
      (magit-insert-section (cube-review-root)
        (magit-insert-heading
          (format "Approvals (%d)%s%s"
                  (length cube-review--approvals)
                  (if cube-review--generated
                      (format ", as of %s ago" (cube--age-string cube-review--generated))
                    "")
                  (if cube-review--error (format "  [%s]" cube-review--error) "")))
        (cube-key-legend-insert 'cube-review-mode)
        (if (null cube-review--approvals)
            (insert "  nothing waiting\n")
          (dolist (a cube-review--approvals) (cube-review--insert-item a))))
      (goto-char (point-min))
      (when section
        (ignore-errors (forward-line (1- line)))))
    (current-buffer)))

(defun cube-review-queue ()
  "Show the approval queue in *cube-review*."
  (interactive)
  (pop-to-buffer (cube-review--render))
  (cube-review-refresh))

(defun cube-review-refresh ()
  "Refetch the approvals and redraw."
  (interactive)
  (cube-review--fetch (lambda () (cube-review--render))))

(defun cube-review--current ()
  "Return the approval at point, or signal a `user-error'."
  (let ((value (and (magit-current-section) (oref (magit-current-section) value))))
    (if (and (listp value) (eq (plist-get value :type) 'approval))
        (plist-get value :data)
      (user-error "cube: no approval at point"))))

(defun cube-review--goto (id)
  "Move point to the section of approval ID and expand it."
  (goto-char (point-min))
  (let ((found nil))
    (while (and (not found) (not (eobp)))
      (let* ((section (magit-current-section))
             (value (and section (oref section value))))
        (if (and (listp value) (equal (plist-get value :id) id))
            (progn (setq found t) (magit-section-show section))
          (forward-line 1))))
    found))

(defun cube-review-open (id)
  "Show the queue with approval ID selected and its body loaded."
  (interactive (list (completing-read "Approval: " (mapcar #'cube-review--id cube-review--approvals))))
  (let ((show (lambda ()
                (pop-to-buffer (cube-review--render))
                (if-let* ((approval (cube-review--find id)))
                    (cube-review--fetch-body
                     approval
                     (lambda (_)
                       (with-current-buffer (cube-review--render)
                         (cube-review--goto id))))
                  (message "cube: approval %s is not in the queue" id)))))
    (if (cube-review--find id)
        (funcall show)
      (cube-review--fetch show))))

(defun cube-review-show-body ()
  "Load the body of the approval at point into its section."
  (interactive)
  (let* ((approval (cube-review--current))
         (id (cube-review--id approval)))
    (cube-review--fetch-body
     approval
     (lambda (_)
       (with-current-buffer (cube-review--render)
         (cube-review--goto id))))))

;;;; Actions

(defun cube-review--confirm (prompt)
  "Return non-nil when the action described by PROMPT may proceed."
  (or (not cube-review-confirm) (y-or-n-p prompt)))

(defun cube-review--run (args)
  "Run `cube ARGS --json', report the result and refresh the queue."
  (cube--call-json-async
   args
   (lambda (json)
     (message "%s" (cube-review--result-message json))
     (when (get-buffer "*cube-review*") (cube-review-refresh)))
   (lambda (code err) (message "cube: %s failed (%s): %s" (car args) code err))))

(defun cube-review--hand-to-gnus (approval body)
  "Open a Gnus message buffer for the email APPROVAL with BODY text.
Return the compose buffer name, or signal an error when the Gnus server
cannot be reached.  Nothing is sent."
  (let ((file (cube-review--local-draft-file (cube-review--id approval))))
    (make-directory (file-name-directory file) t)
    (with-temp-file file (insert body))
    (server-eval-at cube-review-gnus-server
                    (cube-review--email-form (cube-review--merged approval) file))))

(defun cube-review--approve-with-body (approval body &optional body-file)
  "Approve APPROVAL whose text is BODY, edited into host BODY-FILE if given.
For email the draft first goes to Gnus; the approval is recorded only
when that succeeded."
  (let ((id (cube-review--id approval)))
    (when (cube-review--email-p approval)
      (condition-case err
          (let ((buf (cube-review--hand-to-gnus approval body)))
            (message "cube: draft opened in Gnus as %s; send it there with C-c C-c" buf))
        (error (user-error "cube: Gnus server %S unreachable (%s); approval not recorded"
                           cube-review-gnus-server (error-message-string err)))))
    (cube-review--run (cube-review--approve-args id body-file))))

(defun cube-review-approve (&optional approval)
  "Approve APPROVAL (default: the one at point).
Emails are handed to Gnus as a draft instead of being sent; everything
else is applied by the backend through `cube approve'."
  (interactive)
  (let* ((approval (or approval (cube-review--current)))
         (id (cube-review--id approval)))
    (when (cube-review--confirm
           (format "Approve %s (%s)? " id (cube--string (cube-get approval 'summary))))
      (if (cube-review--email-p approval)
          (cube-review--fetch-body
           approval (lambda (body) (cube-review--approve-with-body approval body)))
        (cube-review--run (cube-review--approve-args id))))))

(defun cube-review-approve-id (id)
  "Approve the approval with ID (used by the dashboard)."
  (let ((approval (cube-review--find id)))
    (if approval
        (cube-review-approve approval)
      (cube-review--fetch
       (lambda ()
         (if-let* ((a (cube-review--find id)))
             (cube-review-approve a)
           (user-error "cube: approval %s not found" id)))))))

(defun cube-review-reject (&optional approval reason)
  "Reject APPROVAL (default: at point) with REASON."
  (interactive)
  (let* ((approval (or approval (cube-review--current)))
         (id (cube-review--id approval))
         (reason (or reason (read-string (format "Reason for rejecting %s: " id)))))
    (when (cube-review--confirm (format "Reject %s? " id))
      (cube-review--run (cube-review--reject-args id reason)))))

(defun cube-review-reject-id (id)
  "Reject the approval with ID after asking for a reason (dashboard)."
  (cube-review-reject (or (cube-review--find id) (list (cons 'id id)))))

;;;; Editing the body

(defvar-local cube-review-edit--approval nil
  "Approval being edited in this buffer.")

(defvar cube-review-edit-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c C-c") #'cube-review-edit-finish)
    (define-key map (kbd "C-c C-k") #'cube-review-edit-abort)
    map)
  "Keymap of `cube-review-edit-mode'.")

(define-minor-mode cube-review-edit-mode
  "Edit an approval body; C-c C-c approves with the edited text."
  :lighter " cube-edit"
  :keymap cube-review-edit-mode-map)

(defun cube-review-edit ()
  "Edit the body of the approval at point in *cube-review-edit: ID*."
  (interactive)
  (let* ((approval (cube-review--current))
         (id (cube-review--id approval))
         (mode (cube-review--body-mode approval)))
    (cube-review--fetch-body
     approval
     (lambda (body)
       (with-current-buffer (get-buffer-create (format "*cube-review-edit: %s*" id))
         (erase-buffer)
         (insert body)
         (goto-char (point-min))
         (cond ((and (eq mode 'markdown-mode) (require 'markdown-mode nil t)) (markdown-mode))
               ((and (not (eq mode 'markdown-mode)) (fboundp mode)) (funcall mode))
               (t (text-mode)))
         (setq cube-review-edit--approval approval)
         (cube-review-edit-mode 1)
         (setq header-line-format
               (format "Editing %s: C-c C-c approve with this body, C-c C-k abort" id))
         (pop-to-buffer (current-buffer)))))))

(defun cube-review-edit-finish ()
  "Approve the edited approval with the buffer contents as body.
The text is written to state/drafts/<id>.edited.md on the host and
passed to `cube approve ID --body-file'."
  (interactive)
  (let* ((approval (or cube-review-edit--approval (user-error "cube: not an edit buffer")))
         (id (cube-review--id approval))
         (body (buffer-substring-no-properties (point-min) (point-max)))
         (path (cube-review--edited-body-path id)))
    (when (cube-review--confirm (format "Approve %s with the edited body? " id))
      (cube-host-write-file path body)
      (setf (alist-get id cube-review--bodies nil nil #'equal) body)
      (cube-review--approve-with-body approval body path)
      (quit-window t))))

(defun cube-review-edit-abort ()
  "Abort editing."
  (interactive)
  (quit-window t))

;;;; Navigation to related things

(defun cube-review-jump-session ()
  "Jump to the session behind the approval at point (its run)."
  (interactive)
  (let* ((approval (cube-review--current))
         (run-id (or (cube-get approval 'run_id)
                     (user-error "cube: approval has no run")))
         (name (concat "run-" run-id))
         (session (or (cube-rolodex-find name)
                      (seq-find (lambda (s) (equal (cube-session-run-id s) run-id))
                                (cube-rolodex-live-sessions)))))
    (cond ((and session (buffer-live-p (cube-session-buffer session)))
           (cube-rolodex--show (cube-session-buffer session)))
          (cube-remote-host
           (when (y-or-n-p (format "No buffer for %s; attach to tmux cube/%s? " run-id name))
             (cube-rolodex-attach name)))
          (t (message "cube: run %s has no session buffer" run-id)))))

(defun cube-review-open-target ()
  "Open the bead of the approval at point, else the recipient's org file."
  (interactive)
  (let ((approval (cube-review--current)))
    (cond ((cube-get approval 'bead) (cube-beads-show (cube-get approval 'bead)))
          ((cube-get approval 'recipient) (cube-org-open-person (cube-get approval 'recipient)))
          (t (user-error "cube: approval has neither bead nor recipient")))))

(provide 'cube-review)
;;; cube-review.el ends here
