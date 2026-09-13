;;; cube-term.el --- Terminal backend abstraction (eat or vterm)  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, processes, terminals

;;; Commentary:

;; A small facade over the two terminal emulators the cockpit can use so
;; the rolodex never talks to eat or vterm directly.  Neither package is
;; required at load time; the chosen backend is loaded lazily on the
;; first `cube-term-make' and a clear `user-error' is raised when it is
;; not installed.  The file byte-compiles without eat or vterm present.
;;
;; Eat tuning borrowed from claude-code.el: TERM xterm-256color, shell
;; prompt annotation off, keep the buffer when the process exits.  S-TAB
;; and ESC passthrough live in `cube-session-mode' (cube-rolodex.el).

;;; Code:

(require 'cl-lib)
(require 'cube-core)

;; eat
(defvar eat-terminal)
(defvar eat-term-name)
(defvar eat-enable-shell-prompt-annotation)
(defvar eat-kill-buffer-on-exit)
(defvar eat-term-scrollback-size)
(declare-function eat-mode "eat")
(declare-function eat-exec "eat" (buffer name command startfile switches))
(declare-function eat-term-send-string "eat" (terminal string))
(declare-function eat-emacs-mode "eat")
(declare-function eat-semi-char-mode "eat")
(declare-function eat-term-name "eat")

;; vterm
(defvar vterm-shell)
(defvar vterm-environment)
(defvar vterm-buffer-name)
(defvar vterm-kill-buffer-on-exit)
(defvar vterm-copy-mode)
(declare-function vterm-mode "vterm")
(declare-function vterm-send-string "vterm" (string &optional paste-p))
(declare-function vterm-copy-mode "vterm" (&optional arg))

(defvar-local cube-term--backend nil
  "Backend symbol (`eat' or `vterm') of the terminal in this buffer.")

(defvar-local cube-term--output-hooks nil
  "Functions called with (BUFFER STRING) when the terminal receives output.")

(defun cube-term--backend ()
  "Resolve `cube-terminal-backend' to `eat' or `vterm', loading it.
Signal a `user-error' with installation advice when neither is present."
  (pcase cube-terminal-backend
    ('eat (unless (require 'eat nil t)
            (user-error "cube: package `eat' is not installed (M-x package-install RET eat)"))
          'eat)
    ('vterm (unless (require 'vterm nil t)
              (user-error "cube: package `vterm' is not installed"))
            'vterm)
    (_ (cond ((require 'eat nil t) 'eat)
             ((require 'vterm nil t) 'vterm)
             (t (user-error
                 "cube: no terminal backend; install `eat' (M-x package-install RET eat)"))))))

(defun cube-term--process-filter-hook (proc string)
  "Run `cube-term--output-hooks' of PROC's buffer after output STRING."
  (let ((buf (process-buffer proc)))
    (when (buffer-live-p buf)
      (dolist (fn (buffer-local-value 'cube-term--output-hooks buf))
        (condition-case err
            (funcall fn buf string)
          (error (cube-log "output hook %S failed: %s" fn
                           (error-message-string err))))))))

(defun cube-term--attach-filter (buffer)
  "Hook `cube-term--process-filter-hook' onto BUFFER's process filter."
  (let ((proc (get-buffer-process buffer)))
    (when (and proc (not (process-get proc 'cube-term-hooked)))
      (add-function :after (process-filter proc)
                    #'cube-term--process-filter-hook)
      (process-put proc 'cube-term-hooked t))))

(defun cube-term--eat-make (buffer program args cwd env)
  "Create an eat terminal in BUFFER running PROGRAM with ARGS.
CWD is the working directory and ENV a list of \"VAR=value\" strings."
  (with-current-buffer buffer
    (when cwd (setq default-directory cwd))
    (unless (derived-mode-p 'eat-mode) (eat-mode))
    (setq-local eat-term-name "xterm-256color")
    (setq-local eat-enable-shell-prompt-annotation nil)
    (setq-local eat-kill-buffer-on-exit nil)
    (setq-local eat-term-scrollback-size (* 1024 1024))
    (setq-local scroll-margin 0)
    (setq-local scroll-conservatively 101)
    (let ((process-environment (append env process-environment)))
      (eat-exec buffer (buffer-name buffer) program nil args))
    (setq cube-term--backend 'eat)
    buffer))

(defun cube-term--vterm-make (buffer program args cwd env)
  "Create a vterm terminal in BUFFER running PROGRAM with ARGS.
CWD is the working directory and ENV a list of \"VAR=value\" strings."
  (let ((vterm-shell (cube--shell-join (cons program args)))
        (vterm-environment (append env (bound-and-true-p vterm-environment)))
        (vterm-buffer-name (buffer-name buffer))
        (vterm-kill-buffer-on-exit nil))
    (with-current-buffer buffer
      (when cwd (setq default-directory cwd))
      (vterm-mode)
      (setq cube-term--backend 'vterm)
      buffer)))

(cl-defun cube-term-make (buffer-name program args &key cwd env)
  "Start PROGRAM with ARGS in a terminal buffer named BUFFER-NAME.
CWD is a local directory (never a TRAMP path; ssh runs locally) and
ENV a list of \"VAR=value\" strings added to the process environment.
Return the buffer.  Signal an error when the buffer already hosts a
live terminal process."
  (let* ((backend (cube-term--backend))
         (buffer (get-buffer-create buffer-name)))
    (when (cube-term-live-p buffer)
      (user-error "cube: %s already has a running process" buffer-name))
    (let ((cwd (and cwd (file-name-as-directory (expand-file-name cwd)))))
      (pcase backend
        ('eat (cube-term--eat-make buffer program args cwd env))
        ('vterm (cube-term--vterm-make buffer program args cwd env))))
    (cube-term--attach-filter buffer)
    buffer))

(defun cube-term-process (buffer)
  "Return the terminal process of BUFFER, or nil."
  (and (buffer-live-p buffer) (get-buffer-process buffer)))

(defun cube-term-live-p (buffer)
  "Return non-nil when BUFFER has a live terminal process."
  (let ((proc (cube-term-process buffer)))
    (and proc (process-live-p proc))))

(defun cube-term-send-string (buffer string)
  "Send STRING to the terminal in BUFFER as if typed."
  (unless (cube-term-live-p buffer)
    (user-error "cube: no live terminal in %s" (buffer-name buffer)))
  (with-current-buffer buffer
    (pcase cube-term--backend
      ('eat (eat-term-send-string eat-terminal string))
      ('vterm (vterm-send-string string))
      (_ (process-send-string (get-buffer-process buffer) string)))))

(defun cube-term-copy-mode (&optional buffer arg)
  "Toggle copy (scrollback, Emacs keys) mode in BUFFER.
ARG follows minor mode conventions: positive enables, negative or zero
disables, nil toggles."
  (interactive)
  (with-current-buffer (or buffer (current-buffer))
    (pcase cube-term--backend
      ('eat
       (let ((enable (cond ((null arg) (not buffer-read-only))
                           ((numberp arg) (> arg 0))
                           (t t))))
         (if enable (eat-emacs-mode) (eat-semi-char-mode))))
      ('vterm
       (vterm-copy-mode (cond ((null arg) 'toggle)
                              ((numberp arg) arg)
                              (t 1))))
      (_ (user-error "cube: %s is not a cube terminal" (buffer-name))))))

(defun cube-term-add-output-hook (buffer function)
  "Call FUNCTION with (BUFFER STRING) whenever BUFFER's terminal gets output."
  (with-current-buffer buffer
    (add-hook 'cube-term--output-hooks function nil t))
  (cube-term--attach-filter buffer))

(defun cube-term-remove-output-hook (buffer function)
  "Stop calling FUNCTION for output in BUFFER."
  (when (buffer-live-p buffer)
    (with-current-buffer buffer
      (remove-hook 'cube-term--output-hooks function t))))

(defun cube-term-kill (buffer)
  "Terminate the terminal process of BUFFER, if any, keeping the buffer."
  (let ((proc (cube-term-process buffer)))
    (when (and proc (process-live-p proc))
      (set-process-query-on-exit-flag proc nil)
      (delete-process proc))))

(provide 'cube-term)
;;; cube-term.el ends here
