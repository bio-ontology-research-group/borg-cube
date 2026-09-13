;;; cube-cockpit.el --- Arrange a compact borg-cube working frame  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools

;;; Commentary:

;; `cube-cockpit' is a reversible frame arrangement: the fleet list is on
;; the left, the current session is central, and the dashboard occupies the
;; bottom third.  The prior window state is retained per frame until `q' in
;; the dashboard restores it.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'cube-core)
(require 'cube-rolodex)
(require 'cube-dashboard)

(defvar cube-cockpit--previous-window-states (make-hash-table :test #'eq)
  "Frame -> window state saved before entering the cockpit layout.")

;;;; Pure layout planning

(defun cube-cockpit--layout-plan (width height)
  "Return the split sizes for a frame WIDTH by HEIGHT.
The left list is about 22 percent wide and the dashboard is the lower
third.  Minimums keep the layout usable on a small frame."
  (let* ((left (max 18 (floor (* width 0.22))))
         (top (max 4 (floor (* height 0.67))))
         (top (min top (- height 4))))
    (list :left-width (min left (max 1 (- width 20)))
          :top-height top
          :bottom-height (- height top))))

(defun cube-cockpit--placeholder-buffer ()
  "Return the buffer shown in the session pane when no agent session exists."
  (with-current-buffer (get-buffer-create "*cube-sessions*")
    (let ((inhibit-read-only t))
      (erase-buffer)
      (insert "No agent session yet.\n\n"
              "  C-c b c   new Claude session on the host\n"
              "  C-c b x   new Codex session\n"
              "  C-c b h   new Hermes session\n"
              "  C-c b $   shell on the host\n"
              "  C-c b L   attach an existing tmux session\n"
              "  C-c b ?   every command\n")
      (special-mode))
    (current-buffer)))

(defun cube-cockpit--session-buffer ()
  "Return the best current session buffer.
Never a cockpit pane buffer (dashboard, fleet, log): when no agent session
exists the placeholder from `cube-cockpit--placeholder-buffer' is used, so
the dashboard is never shown twice."
  (or (and (cube-rolodex-session-for-buffer)
           (current-buffer))
      (and (buffer-live-p cube-rolodex--last-session)
           cube-rolodex--last-session)
      (when-let* ((session (car (cube-rolodex-live-sessions))))
        (cube-session-buffer session))
      (cube-cockpit--placeholder-buffer)))

(defun cube-cockpit--fleet-buffer ()
  "Build and return the rolodex list buffer without selecting it."
  (with-current-buffer (get-buffer-create "*cube-fleet*")
    (unless (derived-mode-p 'cube-fleet-mode) (cube-fleet-mode))
    (cube-fleet--refresh)
    (tabulated-list-print nil)
    (current-buffer)))

(defun cube-cockpit--dashboard-buffer ()
  "Build and return the dashboard buffer without selecting it."
  (with-current-buffer (get-buffer-create "*cube*")
    (unless (derived-mode-p 'cube-dashboard-mode) (cube-dashboard-mode))
    (cube-dashboard--render)
    (current-buffer)))

;;;; Layout

(defun cube-cockpit ()
  "Arrange the selected frame as fleet, session and dashboard panes."
  (interactive)
  (let* ((frame (selected-frame))
         (root (frame-root-window frame))
         (plan (cube-cockpit--layout-plan (window-total-width root)
                                          (window-total-height root)))
         (session-buffer (cube-cockpit--session-buffer))
         (fleet-buffer (cube-cockpit--fleet-buffer))
         (dashboard-buffer (cube-cockpit--dashboard-buffer)))
    (unless (gethash frame cube-cockpit--previous-window-states)
      (puthash frame (window-state-get root t)
               cube-cockpit--previous-window-states))
    (delete-other-windows root)
    (let* ((left root)
           (right (split-window root (plist-get plan :left-width) 'right))
           (bottom (split-window right (plist-get plan :top-height) 'below)))
      (set-window-buffer left fleet-buffer)
      (set-window-buffer right session-buffer)
      (set-window-buffer bottom dashboard-buffer)
      (select-window right)
      (cube-dashboard-refresh)
      (message "cube: cockpit layout ready (q in *cube* restores the previous layout)"))))

(defun cube-cockpit-restore ()
  "Restore the frame layout saved before entering `cube-cockpit'."
  (interactive)
  (let* ((frame (selected-frame))
         (state (gethash frame cube-cockpit--previous-window-states)))
    (if state
        (progn
          (remhash frame cube-cockpit--previous-window-states)
          (window-state-put state (frame-root-window frame) 'safe)
          (message "cube: previous window layout restored"))
      (quit-window))))

(provide 'cube-cockpit)
;;; cube-cockpit.el ends here
