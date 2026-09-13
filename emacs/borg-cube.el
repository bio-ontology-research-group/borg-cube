;;; borg-cube.el --- Emacs cockpit for the borg-cube orchestration suite  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Version: 0.1.0
;; Package-Requires: ((emacs "29.1"))
;; Keywords: tools, processes
;; URL: https://github.com/bio-ontology-research-group/borg-cube

;;; Commentary:

;; Entry point of the cockpit.  Load this file, enable `cube-mode', and
;; the `C-c b' prefix (see `cube-prefix-key') gives you the rolodex of
;; agent sessions, the fleet list and the `cube-menu' transient.  The
;; heavy lifting lives in cube-core.el (settings, ssh, JSON),
;; cube-term.el (eat/vterm), cube-rolodex.el (sessions) and
;; cube-server.el (notifications and the event tail).
;;
;; Setup, three lines in ~/.emacs:
;;   (add-to-list \\='load-path "~/Public/software/borg-cube/emacs")
;;   (require \\='borg-cube)
;;   (cube-mode 1)
;;
;; v1 adds the *cube* dashboard (cube-dashboard.el), v2 the beads, org
;; and review modules (cube-beads.el, cube-org.el, cube-review.el).

;;; Code:

(require 'cl-lib)
(require 'subr-x)
(require 'transient)
(require 'cube-core)
(require 'cube-term)
(require 'cube-rolodex)
(require 'cube-server)
(require 'cube-beads)
(require 'cube-org)
(require 'cube-project)
(require 'cube-roster)
(require 'cube-review)
(require 'cube-decisions)
(require 'cube-people)
(require 'cube-dashboard)
(require 'cube-tier)
(require 'cube-cockpit)
(require 'cube-goals)
(require 'cube-agents)
(require 'cube-pipeline)
(require 'cube-watch)

;;;; Backend commands

(defvar cube--refresh-timer nil
  "Timer polling the backend attention list.")

(defvar cube--refresh-failed nil
  "Non-nil after a poll failed, to log the failure only once.")

(defun cube-refresh ()
  "Poll `cube attention' and update the mode line."
  (interactive)
  (cube--call-json-async
   '("attention")
   (lambda (json)
     (setq cube--refresh-failed nil)
     (cube-attention-set-items json)
     (when (called-interactively-p 'any)
       (message "cube: %d attention item(s)" (length cube--attention-items))))
   (lambda (code err)
     (unless cube--refresh-failed
       (setq cube--refresh-failed t)
       (cube-log "attention poll failed (%s): %s" code err)))))

(defun cube-doctor ()
  "Run `cube doctor --json' and show the checks."
  (interactive)
  (message "cube: running doctor...")
  (cube--call-json-async
   '("doctor")
   (lambda (json)
     (cube-doctor-set-json json)
     (with-current-buffer (get-buffer-create "*cube-doctor*")
       (let ((inhibit-read-only t))
         (erase-buffer)
         (insert (format "cube doctor: %s\n\n"
                         (if (cube-true-p (cube-get json 'ok)) "ok" "problems")))
         (dolist (check (cube-get json 'checks))
           (insert (format "%s %-24s %s\n"
                           (if (cube-true-p (cube-get check 'ok)) "ok  " "FAIL")
                           (or (cube-get check 'name) "?")
                           (or (cube-get check 'detail) "")))
           (when-let* ((fix (cube-get check 'fix)))
             (insert (format "     fix: %s\n" fix)))))
       (special-mode)
       (pop-to-buffer (current-buffer))))
   (lambda (code err) (message "cube: doctor failed (%s): %s" code err))))

(defun cube-laptop-worker-run-once ()
  "Run one local laptop worker pass and report its backend result.
The explicit nil host keeps this action on the laptop even when the cockpit's
ordinary backend is configured as ws."
  (interactive)
  (message "cube: running laptop worker once...")
  (cube--call-json-async-on
   nil '("worker" "--once" "--host" "laptop")
   (lambda (json)
     (message "cube: laptop worker %s"
              (or (cube-get json 'message) (cube-get json 'result) "finished")))
   (lambda (code err) (message "cube: laptop worker failed (%s): %s" code err))))

(defun cube-send (start end)
  "Send the region START to END, or the @file:line reference, to a session.
Without an active region send \"@FILE:LINE \" for the current position,
which Claude Code and Codex understand as a file reference."
  (interactive "r")
  (let* ((session (cube-rolodex--current-or-choose))
         (buffer (cube-session-buffer session))
         (text (if (use-region-p)
                   (buffer-substring-no-properties start end)
                 (if buffer-file-name
                     (format "@%s:%d " (file-relative-name buffer-file-name
                                                           (cube--local-directory))
                             (line-number-at-pos))
                   (user-error "cube: no region and no file to reference")))))
    (cube-term-send-string buffer text)
    (message "cube: sent %d chars to %s" (length text) (cube-rolodex--label session))))

;;;; Mode line

(defun cube-mode-line-string ()
  "Return the mode line indicator \"?D ⚠N ●M\".
D counts the decisions the agents are waiting for Robert to answer, N the
local sessions needing attention plus backend attention items, M the
running sessions.  Empty when there is nothing to show."
  (let* ((sessions (cube-rolodex-live-sessions))
         (attention (+ (length (cube-rolodex-attention-sessions))
                       (length cube--attention-items)))
         (running (seq-count (lambda (s) (eq (cube-session-state s) 'running))
                             sessions))
         (decisions (cube-decisions-pending-count))
         (banner (cube-status-banner))
         (banner-segment
          (when banner
            (let ((severity (upcase (or (cube-get banner 'severity) "incident"))))
              (propertize severity 'face
                          (intern (format "cube-banner-%s"
                                          (downcase severity))))))))
    (if (and (zerop attention) (zerop running) (zerop decisions) (null banner-segment))
        ""
      (concat (and banner-segment (concat banner-segment " "))
              (if (> decisions 0)
                  (concat (propertize (format "?%d" decisions) 'face 'warning) " ")
                "")
              (if (> attention 0)
                  (propertize (format "⚠%d" attention) 'face 'warning)
                (format "⚠%d" attention))
              (format " ●%d" running)))))

(defvar cube--mode-line-construct '(:eval (cube-mode-line-string))
  "Mode line construct added to `global-mode-string'.")

(defvar cube-mode-map (make-sparse-keymap)
  "Keymap of `cube-mode'; holds the prefix binding and menu bar.")

(require 'cube-menu)

;;;; Keymap

(defvar cube-repeat-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "n") #'cube-rolodex-next)
    (define-key map (kbd "p") #'cube-rolodex-prev)
    (define-key map (kbd "!") #'cube-attention)
    (define-key map (kbd "b") #'cube-rolodex-toggle)
    map)
  "Repeat map so `C-c b n n n' keeps flipping (needs `repeat-mode').")

(dolist (cmd '(cube-rolodex-next cube-rolodex-prev cube-attention
                                 cube-rolodex-toggle))
  (put cmd 'repeat-map 'cube-repeat-map))

;;;; Global minor mode

(defun cube--install-prefix ()
  "Bind `cube-command-map' under `cube-prefix-key' in `cube-mode-map'."
  (define-key cube-mode-map (kbd cube-prefix-key) cube-command-map))

(defun cube--start-timers ()
  "Start the periodic attention poll."
  (cube--stop-timers)
  (when cube-refresh-interval
    (setq cube--refresh-timer
          (run-with-timer 5 cube-refresh-interval #'cube-refresh))))

(defun cube--stop-timers ()
  "Stop the periodic attention poll."
  (when cube--refresh-timer
    (cancel-timer cube--refresh-timer)
    (setq cube--refresh-timer nil)))

;;;###autoload
(define-minor-mode cube-mode
  "Global cockpit mode: prefix keymap, mode line, event watcher, server."
  :global t
  :group 'borg-cube
  :lighter ""
  :keymap cube-mode-map
  (if cube-mode
      (progn
        (cube--install-prefix)
        (ignore-errors (cube-beads-install-capture))
        (unless (member cube--mode-line-construct global-mode-string)
          (setq global-mode-string
                (append (or global-mode-string '("")) (list cube--mode-line-construct))))
        (cube--start-timers)
        (unless noninteractive
          (ignore-errors (cube-server-ensure))
          (ignore-errors (cube-server-watch-events))))
    (setq global-mode-string (delete cube--mode-line-construct global-mode-string))
    (cube--stop-timers)
    (cube-server-unwatch-events)))

(provide 'borg-cube)
;;; borg-cube.el ends here
