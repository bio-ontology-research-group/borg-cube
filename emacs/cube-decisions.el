;;; cube-decisions.el --- Decisions: how the agents ask Robert  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools

;;; Commentary:

;; An agent that needs Robert stops and asks.  The backend collects every
;; channel it can ask through (outbound approvals, `needs:robert' beads,
;; resource permissions, pipeline recruitment requests, free-text questions)
;; into one list, `cube decisions --json'.  This file is the cockpit end of
;; that list: one buffer, one row per pending decision, clickable [Yes] [No]
;; or [Approve] [Reject] buttons, `y'/`n' for the same answer from the
;; keyboard, and `a' for a typed answer in a small compose buffer.
;;
;; Answers go back through `cube decide ID --choice ... --apply' (or
;; `--text'), which records them in state/decisions.jsonl and routes them to
;; whoever asked: a standing agent's inbox, a follow-up bead for a role, a
;; recruitment decision, or a resource grant.  Outbound approvals keep going
;; through the review queue, so an email still opens in Gnus and is never
;; sent from here.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'magit-section)
(require 'cube-core)
(require 'cube-beads)
(require 'cube-review)

(declare-function cube-dashboard-refresh "cube-dashboard")

(defcustom cube-decisions-count 5
  "Rows shown in the dashboard's Decisions section."
  :type 'integer
  :group 'borg-cube)

(defcustom cube-decisions-body-lines 4
  "Lines of the request summary shown under each decision row.
Short by design (Robert: not multiple pages); the full request is one
`RET' away.  0 hides the text and shows titles only."
  :type 'integer
  :group 'borg-cube)

(defcustom cube-decisions-confirm nil
  "When non-nil ask before sending an answer.
Clicking [Yes] or pressing `y' is already Robert's approval, so the
default is to send it straight through."
  :type 'boolean
  :group 'borg-cube)

(defvar cube-decisions--items nil
  "Pending decisions from the last successful `cube decisions' call.")

(defvar cube-decisions--answered nil
  "The last answers Robert gave, newest last.")

(defvar cube-decisions--generated nil
  "Timestamp string of the last successful fetch.")

(defvar cube-decisions--error nil
  "Message of the last failed fetch, or nil.")

(defvar cube-decisions-update-hook nil
  "Hook run after the cached decisions changed.")

(defconst cube-decisions-buffer "*cube-decisions*"
  "Name of the decisions buffer.")

;;;; Pure helpers

(defun cube-decisions--id (item)
  "Return the id of ITEM as a string."
  (cube--string (cube-get item 'id)))

(defun cube-decisions--kind (item)
  "Return the decision kind of ITEM."
  (cube--string (cube-get item 'kind)))

(defun cube-decisions--options (item)
  "Return the answer options of ITEM as a list of strings."
  (mapcar #'cube--string (append (cube-get item 'options) nil)))

(defun cube-decisions--free-p (item)
  "Return non-nil when ITEM only takes a typed answer."
  (equal (cube-decisions--options item) '("free")))

(defun cube-decisions--approval-p (item)
  "Return non-nil when ITEM is an outbound approval from the approval store."
  (equal (cube-decisions--kind item) "approval"))

(defun cube-decisions--host (item)
  "Return the host that must deliver the answer to ITEM, or nil."
  (let ((host (cube-get (cube-get item 'context) 'host)))
    (and host (not (eq host :false)) (cube--string host))))

(defun cube-decisions--evidence (item)
  "Return the first evidence path of ITEM, or nil."
  (car (append (cube-get (cube-get item 'context) 'evidence) nil)))

(defun cube-decisions--policy (item)
  "Return the policy preview of ITEM, or nil when it waits for Robert."
  (let ((preview (cube-get item 'policy_preview)))
    (and preview (not (eq preview :null)) (not (eq preview :false)) preview)))

(defun cube-decisions--policy-tag (item)
  "Return the dim `auto: ANSWER at next tick' tag of ITEM, or nil.
The decisions patrol answers it at its next tick unless Robert answers
first, so `n' on the row still pre-empts the rule."
  (when-let* ((preview (cube-decisions--policy item)))
    (propertize (format "auto: %s at next tick"
                        (cube--string (cube-get preview 'answer)))
                'font-lock-face 'shadow)))

(defun cube-decisions--bead (item)
  "Return the bead id behind ITEM, or nil."
  (let ((bead (cube-get (cube-get item 'context) 'bead)))
    (and bead (not (eq bead :false)) (cube--string bead))))

(defconst cube-decisions--sections
  '(("Permissions" permission recruit)
    ("Questions" question)
    ("Approvals" approval)
    ("Other" proposal finding conflict))
  "Section title to the decision kinds it holds, in display order.")

(defun cube-decisions--section (item)
  "Return the section title ITEM belongs to."
  (let ((kind (intern (cube-decisions--kind item))))
    (or (car (seq-find (lambda (spec) (memq kind (cdr spec))) cube-decisions--sections))
        "Other")))

(defun cube-decisions--in-section (title &optional items)
  "Return the decisions of ITEMS that belong to section TITLE."
  (seq-filter (lambda (item) (equal (cube-decisions--section item) title))
              (or items cube-decisions--items)))

(defun cube-decisions--affirm (item)
  "Return the affirmative choice of ITEM (yes, approve or accept)."
  (let ((options (cube-decisions--options item)))
    (if (cube-decisions--free-p item) nil (car options))))

(defun cube-decisions--deny (item)
  "Return the negative choice of ITEM (no or reject)."
  (let ((options (cube-decisions--options item)))
    (cond ((cube-decisions--free-p item) nil)
          ((member "no" options) "no")
          ((member "reject" options) "reject")
          (t (cadr options)))))

(defun cube-decisions--button-labels (item)
  "Return the (LABEL . CHOICE) buttons of ITEM.
The labels are the backend's own options capitalized, so yes/no becomes
[Yes] [No] and an approval becomes [Approve] [Reject]; a decision with
more than two options also offers [Answer]."
  (if (cube-decisions--free-p item)
      (list (cons "Answer" nil))
    (let ((affirm (cube-decisions--affirm item))
          (deny (cube-decisions--deny item)))
      (append (list (cons (capitalize affirm) affirm) (cons (capitalize deny) deny))
              (when (> (length (cube-decisions--options item)) 2)
                (list (cons "Answer" nil)))))))

(defun cube-decisions--row-text (item &optional now)
  "Return the one line row of ITEM.  NOW is for the tests."
  (let ((age (cube--age-string (or (cube-get item 'age) (cube-get item 'since)) now)))
    (format "%-22s %-5s %s"
            (cube--string (cube-get item 'from))
            (if (string-empty-p age) "-" age)
            (cube--string (cube-get item 'title)))))

(defun cube-decisions--question-text (item)
  "Return the question line of ITEM when it adds anything to the title."
  (let ((question (cube--string (cube-get item 'question)))
        (title (cube--string (cube-get item 'title))))
    (and (not (string-empty-p question)) (not (equal question title)) question)))

(defun cube-decisions--answered-text (row)
  "Return the one line summary of the answered decision ROW."
  (format "%-12s %-10s %s"
          (cube--string (cube-get row 'id))
          (cube--string (cube-get row 'choice))
          (or (cube--string (cube-get row 'text)) "")))

(defun cube-decisions--decide-args (id &optional choice text)
  "Return the `cube decide' arguments for ID with CHOICE or TEXT."
  (append (list "decide" (cube--string id))
          (when choice (list "--choice" (cube--string choice)))
          (when text (list "--text" text))
          (list "--apply")))

(defun cube-decisions-relay-args (item answer)
  "Return the delivery command re-run on the asking agent's own host.
The bead is answered on the backend host; only the inbox append happens
where the agent lives, exactly as `cube agent inbox' relays its pass."
  (let ((name (cadr (split-string (cube--string (cube-get item 'from)) ":"))))
    (list "agent" "tell" name (format "Robert answered: %s" answer) "--from" "robert" "--apply")))

;;;; Cache and fetching

(defun cube-decisions-set-json (json)
  "Cache the parsed `cube decisions' payload JSON."
  (setq cube-decisions--items (append (cube-get json 'decisions) nil)
        cube-decisions--answered (append (cube-get json 'answered) nil)
        cube-decisions--generated (or (cube-get json 'generated)
                                      (format-time-string "%FT%T%z"))
        cube-decisions--error nil)
  (force-mode-line-update t)
  (run-hooks 'cube-decisions-update-hook)
  cube-decisions--items)

(defun cube-decisions-pending-count ()
  "Return how many decisions wait for Robert."
  (length cube-decisions--items))

(defun cube-decisions--fetch (&optional callback)
  "Fetch the decisions and call CALLBACK with no arguments."
  (cube--call-json-async
   '("decisions")
   (lambda (json)
     (cube-decisions-set-json json)
     (when callback (funcall callback)))
   (lambda (code err)
     (setq cube-decisions--error (format "decisions failed (%s): %s" code err))
     (cube-log "%s" cube-decisions--error)
     (when callback (funcall callback)))))

(defun cube-decisions-poll ()
  "Refresh the cached decisions; bound to the attention poll."
  (cube-decisions--fetch
   (lambda ()
     (when (get-buffer cube-decisions-buffer) (cube-decisions--render)))))

;;;; Buttons

(defvar cube-decisions-button-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map button-map)
    (define-key map [mouse-1] #'push-button)
    map)
  "Keymap of a decision button: mouse-1 and RET answer.")

(defun cube-decisions--button (label item choice)
  "Return the clickable button text LABEL answering ITEM with CHOICE."
  (make-text-button
   (copy-sequence (format "[%s]" label)) nil
   'action (lambda (_button) (cube-decisions-answer-item item choice))
   'follow-link t
   'keymap cube-decisions-button-map
   'cube-decision-id (cube-decisions--id item)
   'cube-decision-choice (or choice "free")
   'help-echo (format "%s %s" label (cube-decisions--id item))))

(defun cube-decisions--buttons-string (item)
  "Return the button strip of ITEM as one string."
  (mapconcat (lambda (spec) (cube-decisions--button (car spec) item (cdr spec)))
             (cube-decisions--button-labels item)
             " "))

;;;; Rendering

(defvar cube-decisions-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map magit-section-mode-map)
    (define-key map (kbd "g") #'cube-decisions-refresh)
    (define-key map (kbd "y") #'cube-decisions-yes)
    (define-key map (kbd "n") #'cube-decisions-no)
    (define-key map (kbd "a") #'cube-decisions-answer)
    (define-key map (kbd "P") #'cube-decisions-apply-policy)
    (define-key map (kbd "RET") #'cube-decisions-visit)
    (define-key map (kbd "o") #'cube-decisions-open-evidence)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap of `cube-decisions-mode'.")

(defconst cube-decisions-mode-key-help
  '(("y" . "yes") ("n" . "no") ("a" . "answer") ("P" . "apply policy") ("RET" . "open")
    ("o" . "open evidence") ("g" . "refresh"))
  "Key legend of `cube-decisions-mode', proved against its keymap by the tests.")

(cube-key-legend-register 'cube-decisions-mode)

(define-derived-mode cube-decisions-mode magit-section-mode "cube-decisions"
  "Everything the agents are waiting for Robert to answer."
  (setq-local revert-buffer-function (lambda (&rest _) (cube-decisions-refresh))))

(defun cube-decisions--body-lines (item)
  "Return the request text lines of ITEM, capped by `cube-decisions-body-lines'."
  (let* ((body (cube--string (or (cube-get item 'summary) (cube-get item 'body) "")))
         (lines (seq-remove #'string-empty-p (split-string body "\n")))
         (limit (max 0 cube-decisions-body-lines)))
    (if (> (length lines) limit)
        (append (seq-take lines limit) (list "[more: RET opens the full request]"))
      lines)))

(defun cube-decisions--duplicates-text (item)
  "Return the duplicates note of ITEM, or nil."
  (let ((dups (cube-get item 'duplicates)))
    (and dups (> (length dups) 0)
         (format "same request %d more time%s (%s); one answer closes all"
                 (length dups) (if (= (length dups) 1) "" "s")
                 (mapconcat #'cube--string dups ", ")))))

(defun cube-decisions--restore-button-keymaps (start end)
  "Give every decision button between START and END its own keymap back.
magit-section puts its toggle keymap on a heading whose section has a
body; the buttons underneath must keep answering on mouse-1 and RET."
  (let ((pos start))
    (while (and pos (< pos end))
      (let ((next (next-single-property-change pos 'cube-decision-id nil end)))
        (when (get-text-property pos 'cube-decision-id)
          (put-text-property pos next 'keymap cube-decisions-button-map))
        (setq pos next)))))

(defun cube-decisions-insert-item (item)
  "Insert the section for one decision ITEM: buttons, row, request text."
  (let ((id (cube-decisions--id item))
        (start (point)))
    (cube-decisions--insert-item-section item id)
    (cube-decisions--restore-button-keymaps start (point))))

(defun cube-decisions--insert-item-section (item id)
  "Insert the magit section of decision ITEM with ID."
  (progn
    (magit-insert-section (cube-decision (list :type 'decision :id id :data item))
      (magit-insert-heading
        (concat "  " (cube-decisions--buttons-string item)
                (if-let* ((tag (cube-decisions--policy-tag item))) (concat " " tag) "")
                "  " (cube-decisions--row-text item)))
      (when-let* ((question (cube-decisions--question-text item)))
        (insert "      " (propertize question 'font-lock-face 'shadow) "\n"))
      (when-let* ((dups (cube-decisions--duplicates-text item)))
        (insert "      " (propertize dups 'font-lock-face 'warning) "\n"))
      (dolist (line (cube-decisions--body-lines item))
        (insert "      " line "\n")))))

(defun cube-decisions--insert-section (title &optional items)
  "Insert the decisions section TITLE holding ITEMS."
  (let ((rows (cube-decisions--in-section title items)))
    (magit-insert-section (cube-decisions-group (intern (downcase title)))
      (magit-insert-heading
        (propertize (format "%s (%d)" title (length rows))
                    'font-lock-face 'magit-section-heading))
      (if rows
          (dolist (item rows) (cube-decisions-insert-item item))
        (insert "  none\n"))
      (insert "\n"))))

(defun cube-decisions--insert-answered ()
  "Insert the recently answered decisions."
  (magit-insert-section (cube-decisions-group 'answered)
    (magit-insert-heading
      (propertize (format "Answered (%d)" (length cube-decisions--answered))
                  'font-lock-face 'magit-section-heading))
    (if cube-decisions--answered
        (dolist (row (reverse cube-decisions--answered))
          (insert "  " (cube-decisions--answered-text row) "\n"))
      (insert "  nothing answered yet\n"))
    (insert "\n")))

(defun cube-decisions--render ()
  "Redraw the decisions buffer from the cache."
  (with-current-buffer (get-buffer-create cube-decisions-buffer)
    (unless (derived-mode-p 'cube-decisions-mode) (cube-decisions-mode))
    (let ((inhibit-read-only t)
          (line (line-number-at-pos)))
      (erase-buffer)
      (magit-insert-section (cube-decisions-root)
        (magit-insert-heading
          (format "Decisions (%d)%s%s"
                  (length cube-decisions--items)
                  (if cube-decisions--generated
                      (format ", as of %s ago" (cube--age-string cube-decisions--generated))
                    "")
                  (if cube-decisions--error (format "  [%s]" cube-decisions--error) "")))
        (cube-key-legend-insert 'cube-decisions-mode)
        (insert "\n")
        (dolist (spec cube-decisions--sections)
          (cube-decisions--insert-section (car spec)))
        (cube-decisions--insert-answered))
      (goto-char (point-min))
      (ignore-errors (forward-line (1- line))))
    (current-buffer)))

;;;###autoload
(defun cube-decisions ()
  "Show everything waiting for Robert's answer in `cube-decisions-buffer'."
  (interactive)
  (pop-to-buffer (cube-decisions--render))
  (cube-decisions-refresh))

(defun cube-decisions-refresh ()
  "Refetch the decisions and redraw."
  (interactive)
  (cube-decisions--fetch (lambda () (cube-decisions--render))))

;;;; Answering

(defun cube-decisions--current ()
  "Return the decision at point, or signal a `user-error'."
  (let ((value (and (magit-current-section) (oref (magit-current-section) value))))
    (if (and (listp value) (eq (plist-get value :type) 'decision))
        (plist-get value :data)
      (user-error "cube: no decision at point"))))

(defun cube-decisions--find (id)
  "Return the cached decision with ID."
  (seq-find (lambda (item) (equal (cube-decisions--id item) id)) cube-decisions--items))

(defun cube-decisions--after-answer (id)
  "Refresh what shows ID after it was answered."
  (message "cube: answered %s" id)
  (cube-decisions--fetch
   (lambda ()
     (when (get-buffer cube-decisions-buffer) (cube-decisions--render))
     (when (and (fboundp 'cube-dashboard-refresh) (get-buffer "*cube*"))
       (cube-dashboard-refresh)))))

(defun cube-decisions--relay (item answer)
  "Deliver ANSWER for ITEM on the asking agent's own host."
  (when-let* ((host (cube-decisions--host item)))
    (cube--call-json-async-on
     host (cube-decisions-relay-args item answer)
     (lambda (_json) (message "cube: answer delivered on %s" host))
     (lambda (code err) (message "cube: delivery on %s failed (%s): %s" host code err)))))

(defun cube-decisions--run (item args answer)
  "Run `cube ARGS --json' for ITEM and relay ANSWER when its agent is elsewhere."
  (let ((id (cube-decisions--id item)))
    (cube--call-json-async
     args
     (lambda (json)
       (when (cube-get json 'relay) (cube-decisions--relay item answer))
       (cube-decisions--after-answer id))
     (lambda (code err)
       ;; exit 3 is the relay convention of `cube agent inbox': the answer is
       ;; recorded on the backend host, delivery happens on the agent's host.
       (if (equal code 3)
           (progn (cube-decisions--relay item answer) (cube-decisions--after-answer id))
         (message "cube: decide %s failed (%s): %s" id code err))))))

(defun cube-decisions-answer-item (item &optional choice text)
  "Answer ITEM with CHOICE or TEXT.
An outbound approval keeps going through the review queue, so an email
draft still opens in Gnus and nothing is ever sent from here."
  (let* ((id (cube-decisions--id item))
         (answer (or text choice "")))
    (cond
     ((and (null choice) (null text)) (cube-decisions-compose item))
     ((cube-decisions--approval-p item)
      ;; an outbound approval keeps its single trigger in cube-review.el
      (if (equal choice (cube-decisions--deny item))
          (cube-review-reject-id id)
        (cube-review-approve-id id)))
     ((and cube-decisions-confirm
           (not (y-or-n-p (format "Answer %s with %S? " id answer))))
      (message "cube: %s left open" id))
     (t (cube-decisions--run item (cube-decisions--decide-args id choice text) answer)))))

(defun cube-decisions-yes ()
  "Answer the decision at point affirmatively."
  (interactive)
  (let ((item (cube-decisions--current)))
    (if (cube-decisions--free-p item)
        (cube-decisions-compose item)
      (cube-decisions-answer-item item (cube-decisions--affirm item)))))

(defun cube-decisions-no ()
  "Answer the decision at point negatively."
  (interactive)
  (let ((item (cube-decisions--current)))
    (if (cube-decisions--free-p item)
        (user-error "cube: this decision only takes a typed answer (a)")
      (cube-decisions-answer-item item (cube-decisions--deny item)))))

(defun cube-decisions-answer ()
  "Answer the decision at point, choosing an option or typing a reply."
  (interactive)
  (let* ((item (cube-decisions--current))
         (options (cube-decisions--options item)))
    (if (cube-decisions--free-p item)
        (cube-decisions-compose item)
      (let ((choice (completing-read
                     (format "Answer %s: " (cube-decisions--id item))
                     (append options '("free text")) nil t)))
        (if (equal choice "free text")
            (cube-decisions-compose item)
          (cube-decisions-answer-item item choice))))))

(defconst cube-decisions-policy-buffer "*cube-decisions-policy*"
  "Buffer showing what `cube decisions apply-policy' would answer.")

(defun cube-decisions--policy-plan-text (json)
  "Return the plan text of an `apply-policy' payload JSON."
  (let ((answered (append (cube-get json 'answered) nil)))
    (string-join
     (cons (format "%d decision(s) the policy answers, %d wait for Robert"
                   (length answered)
                   (length (append (cube-get json 'waiting) nil)))
           (mapcar (lambda (row)
                     (format "  %-12s %-8s %s"
                             (cube--string (cube-get row 'id))
                             (cube--string (cube-get row 'answer))
                             (cube--string (cube-get row 'note))))
                   answered))
     "\n")))

(defun cube-decisions--show-policy-plan (json)
  "Show the apply-policy plan JSON in `cube-decisions-policy-buffer'."
  (with-current-buffer (get-buffer-create cube-decisions-policy-buffer)
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (cube-decisions--policy-plan-text json) "\n")
      (goto-char (point-min)))
    (special-mode)
    (display-buffer (current-buffer))))

(defun cube-decisions-apply-policy ()
  "Answer now what the decisions patrol would answer at its next tick.
Goes through the dry-run gate first: the plan appears in
`cube-decisions-policy-buffer' and nothing is answered until you confirm."
  (interactive)
  (cube--call-json-async
   '("decisions" "apply-policy" "--dry-run")
   (lambda (json)
     (cube-decisions--show-policy-plan json)
     (if (null (append (cube-get json 'answered) nil))
         (message "cube: the policy answers nothing right now")
       (when (y-or-n-p "Apply the policy answers? ")
         (cube--call-json-async
          '("decisions" "apply-policy" "--apply")
          (lambda (_result)
            (message "cube: policy applied")
            (cube-decisions-refresh))
          (lambda (code err)
            (message "cube: apply-policy failed (%s): %s" code err))))))
   (lambda (code err)
     (message "cube: apply-policy dry run failed (%s): %s" code err))))

(defun cube-decisions-visit ()
  "Open the bead or approval behind the decision at point."
  (interactive)
  (let ((item (cube-decisions--current)))
    (cond ((cube-decisions--approval-p item) (cube-review-open (cube-decisions--id item)))
          ((cube-decisions--bead item) (cube-beads-show (cube-decisions--bead item)))
          (t (user-error "cube: this decision has nothing to open")))))

(defun cube-decisions-open-evidence ()
  "Open the first evidence path of the decision at point."
  (interactive)
  (let* ((item (cube-decisions--current))
         (path (or (cube-decisions--evidence item)
                   (user-error "cube: this decision names no evidence"))))
    (if (string-match-p "\\`\\(bead\\|runs\\|agents?\\):" path)
        (message "cube: evidence %s" path)
      (find-file (cube-host-file-name (car (split-string path "#")))))))

;;;; Compose buffer

(defvar-local cube-decision-compose--item nil
  "Decision being answered in this compose buffer.")

(defvar cube-decision-compose-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c C-c") #'cube-decision-compose-finish)
    (define-key map (kbd "C-c C-k") #'cube-decision-compose-abort)
    map)
  "Keymap of `cube-decision-compose-mode'.")

(define-derived-mode cube-decision-compose-mode text-mode "cube-answer"
  "Type Robert's answer to one decision; C-c C-c submits it."
  (setq-local comment-start "#"))

(defun cube-decisions-compose (item)
  "Open a compose buffer for the typed answer to ITEM."
  (let ((id (cube-decisions--id item)))
    (with-current-buffer (get-buffer-create (format "*cube-answer: %s*" id))
      (erase-buffer)
      (cube-decision-compose-mode)
      (insert (format "# %s asks: %s\n# Lines starting with # are ignored.\n"
                      (cube--string (cube-get item 'from))
                      (or (cube--string (cube-get item 'question))
                          (cube--string (cube-get item 'title)))))
      (when-let* ((options (and (not (cube-decisions--free-p item))
                                (cube-decisions--options item))))
        (insert (format "# Options: %s\n" (string-join options " | "))))
      (insert "\n")
      (setq cube-decision-compose--item item)
      (setq header-line-format
            (format "Answering %s: C-c C-c submits, C-c C-k cancels" id))
      (pop-to-buffer (current-buffer))
      (goto-char (point-max))
      (current-buffer))))

(defun cube-decision-compose-text ()
  "Return the typed answer of the current compose buffer."
  (string-trim
   (string-join
    (seq-remove (lambda (line) (string-prefix-p "#" line))
                (split-string (buffer-substring-no-properties (point-min) (point-max)) "\n"))
    "\n")))

(defun cube-decision-compose-finish ()
  "Submit the typed answer of this compose buffer."
  (interactive)
  (let ((item (or cube-decision-compose--item (user-error "cube: not an answer buffer")))
        (text (cube-decision-compose-text)))
    (when (string-empty-p text)
      (user-error "cube: type an answer first, or C-c C-k to cancel"))
    (cube-decisions--run item
                         (cube-decisions--decide-args (cube-decisions--id item) nil text)
                         text)
    (quit-window t)))

(defun cube-decision-compose-abort ()
  "Close the compose buffer without answering."
  (interactive)
  (quit-window t))

(add-hook 'cube-attention-update-hook #'cube-decisions-poll)

(provide 'cube-decisions)
;;; cube-decisions.el ends here
