;;; cube-tier.el --- Tier and runner controls for the borg-cube cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools

;;; Commentary:

;; The tier view is deliberately a thin client.  It displays the backend's
;; selected runner table and makes every state change pass through a dry-run
;; plan before asking Robert whether the backend should apply it.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'transient)
(require 'cube-core)

(defcustom cube-tier-confirm t
  "When non-nil, ask before applying a tier state change."
  :type 'boolean
  :group 'borg-cube)

(defvar cube-tier--json nil
  "Most recently fetched `cube tier' payload.")

(defconst cube-tier--known-runners '(claude codex openrouter local hermes)
  "Runner names accepted by the tier backend.")

;;;; Pure formatting

(defun cube-tier--until-text (until)
  "Return the local time portion of ISO UNTIL, or UNTIL itself."
  (if (and (stringp until) (not (string-empty-p until)))
      (condition-case nil
          (format-time-string "%H:%M" (encode-time (iso8601-parse until)))
        (error until))
    ""))

(defun cube-tier--tier-table-text (json)
  "Return a readable tier table for parsed `cube tier' JSON.
The backend order is preserved, including preferred and inactive entries."
  (with-temp-buffer
    (insert "Cube tiers\n\n")
    (insert (format "%-10s %-18s %-22s %-12s %s\n"
                   "Tier" "Runner" "Model" "State" "Until / reason"))
    (insert (make-string 76 ?-) "\n")
    (dolist (tier (cube-get json 'tiers))
      (let ((name (car tier))
            (entries (cdr tier)))
        (if (null entries)
            (insert (format "%-10s (no runners)\n" (cube--string name)))
          (dolist (entry entries)
            (let* ((runner (cube--string (cube-get entry 'runner)))
                   (model (or (cube-get entry 'model)
                              (cube-get entry 'profile)
                              "-"))
                   (state (cube--string (cube-get entry 'state)))
                   (active (if (cube-true-p (cube-get entry 'active)) "*" " "))
                   (until (cube-get entry 'until))
                   (reason (cube-get entry 'reason)))
              (insert (format "%-10s %s%-17s %-22s %-12s %s%s\n"
                              (cube--string name) active runner
                              (cube--string model) state
                              (if until (concat "until " (cube-tier--until-text until)) "")
                              (if reason (concat (if until "  " "") reason) ""))))))))
    (buffer-string)))

(defun cube-tier--tier-names ()
  "Return tier names currently present in `cube-tier--json'."
  (or (mapcar #'car (cube-get cube-tier--json 'tiers))
      '(plan implement bulk local)))

(defun cube-tier--runner-names ()
  "Return runner names currently present in `cube-tier--json'."
  (delete-dups
   (seq-filter #'stringp
               (append cube-tier--known-runners
                       (mapcar (lambda (entry) (cube-get entry 'runner))
                               (apply #'append
                                      (mapcar #'cdr (cube-get cube-tier--json 'tiers))))))))

(defun cube-tier--disable-args (runner duration reason &optional flag)
  "Return tier disable ARGS for RUNNER, DURATION and REASON.
FLAG is `--dry-run' or `--apply'; it defaults to `--dry-run'."
  (append (list "tier" "disable" runner (or flag "--dry-run") "--for" duration)
          (when (and reason (not (string-empty-p reason)))
            (list "--reason" reason))))

(defun cube-tier--enable-args (runner &optional flag)
  "Return tier enable ARGS for RUNNER with FLAG."
  (list "tier" "enable" runner (or flag "--dry-run")))

(defun cube-tier--prefer-args (tier runner &optional flag)
  "Return tier prefer ARGS for TIER and RUNNER with FLAG."
  (list "tier" "prefer" tier runner (or flag "--dry-run")))

(defun cube-tier--reset-args (&optional flag)
  "Return tier reset ARGS with FLAG."
  (list "tier" "reset" (or flag "--dry-run")))

;;;; Buffers and backend calls

(defun cube-tier--render (json)
  "Show parsed tier JSON in the `*cube-tier*' buffer and return it."
  (with-current-buffer (get-buffer-create "*cube-tier*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert (cube-tier--tier-table-text json))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-tier--fetch (callback)
  "Fetch the tier table and call CALLBACK with parsed JSON."
  (cube--call-json-async
   '("tier" "show")
   (lambda (json)
     (setq cube-tier--json json)
     (funcall callback json))
   (lambda (code err)
     (message "cube: tier failed (%s): %s" code err))))

(defun cube-tier--show-plan (json args)
  "Show dry-run JSON JSON for ARGS in a small plan buffer."
  (with-current-buffer (get-buffer-create "*cube-tier-plan*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert "cube tier dry-run\n\n"
              (cube--shell-join (append (cube--program-args) args))
              "\n\n"
              (if (stringp json) json (pp-to-string json)))
      (goto-char (point-min)))
    (special-mode)
    (pop-to-buffer (current-buffer))))

(defun cube-tier--confirm (args)
  "Return non-nil when the applying ARGS is confirmed."
  (or (not cube-tier-confirm)
      (y-or-n-p (format "Apply cube tier change (%s)? "
                        (string-join (cdr args) " ")))))

(defun cube-tier--write (args)
  "Dry-run ARGS, show its plan, then optionally apply it."
  (let* ((base (seq-remove (lambda (arg) (member arg '("--dry-run" "--apply"))) args))
         (dry-run (append base '("--dry-run"))))
    (cube--call-json-async
     dry-run
     (lambda (json)
       (cube-tier--show-plan json dry-run)
       (when (cube-tier--confirm base)
         (cube--call-json-async
          (append base '("--apply"))
          (lambda (result)
            (message "cube: tier change applied: %s"
                     (cube--string (or (cube-get result 'message)
                                       (cube-get result 'result)
                                       "ok")))
            (cube-tier--fetch (lambda (fresh) (cube-tier--render fresh))))
          (lambda (code err)
            (message "cube: tier change failed (%s): %s" code err)))))
     (lambda (code err)
       (message "cube: tier dry-run failed (%s): %s" code err)))))

(defun cube-tier-disable (&optional runner duration reason)
  "Disable RUNNER for DURATION with REASON after a dry-run plan."
  (interactive
   (list (completing-read "Runner: " (cube-tier--runner-names) nil t)
         (read-string "Duration (5h): " nil nil "5h")
         (read-string "Reason (optional): ")))
  (cube-tier--write (cube-tier--disable-args runner duration reason)))

(defun cube-tier-enable (&optional runner)
  "Enable RUNNER after a dry-run plan."
  (interactive (list (completing-read "Runner: " (cube-tier--runner-names) nil t)))
  (cube-tier--write (cube-tier--enable-args runner)))

(defun cube-tier-prefer (&optional tier runner)
  "Prefer RUNNER within TIER after a dry-run plan."
  (interactive
   (list (completing-read "Tier: " (mapcar #'symbol-name (cube-tier--tier-names)) nil t)
         (completing-read "Runner: " (cube-tier--runner-names) nil t)))
  (cube-tier--write (cube-tier--prefer-args tier runner)))

(defun cube-tier-reset ()
  "Reset tier preferences after a dry-run plan."
  (interactive)
  (cube-tier--write (cube-tier--reset-args)))

(defun cube-tier-refresh ()
  "Refresh the tier table, keeping the tier menu available."
  (interactive)
  (cube-tier--fetch #'cube-tier--render))

;;;; Transient

(transient-define-prefix cube-tier-menu ()
  "Inspect and change model tier routing."
  ["Tier actions"
   ("d" "Disable runner" cube-tier-disable)
   ("e" "Enable runner" cube-tier-enable)
   ("p" "Prefer runner in tier" cube-tier-prefer)
   ("r" "Reset preferences" cube-tier-reset)]
  ["View"
   ("g" "Refresh tier table" cube-tier-refresh)
   ("q" "Quit" transient-quit-one)]
  (interactive)
  (message "cube: fetching tier table...")
  (cube-tier--fetch
   (lambda (json)
     (cube-tier--render json)
     (transient-setup 'cube-tier-menu))))

(provide 'cube-tier)
;;; cube-tier.el ends here
