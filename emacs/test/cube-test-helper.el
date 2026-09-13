;;; cube-test-helper.el --- Shared setup for the cockpit tests  -*- lexical-binding: t; -*-

;;; Commentary:
;; Puts the fake `cube' on `exec-path', points `cube-root' at the fixtures
;; and forces local mode.  Loaded by every *-test.el.

;;; Code:

(require 'ert)

(defconst cube-test-dir
  (file-name-directory (or load-file-name buffer-file-name))
  "Directory of the test files.")

(defconst cube-test-fixtures (expand-file-name "fixtures/" cube-test-dir)
  "Directory of the JSON fixtures.")

(defconst cube-test-bin (expand-file-name "bin/" cube-test-dir)
  "Directory of the fake binaries.")

(add-to-list 'load-path (expand-file-name ".." cube-test-dir))
(require 'borg-cube)

(defun cube-test-fixture (name)
  "Return the path of fixture NAME."
  (expand-file-name name cube-test-fixtures))

(defun cube-test-read-fixture (name)
  "Parse fixture NAME as JSON."
  (with-temp-buffer
    (insert-file-contents (cube-test-fixture name))
    (goto-char (point-min))
    (cube--parse-json-buffer)))

(defmacro cube-test-with-local (&rest body)
  "Run BODY in local mode with the fake cube on `exec-path'."
  (declare (indent 0))
  `(let ((cube-remote-host nil)
         (cube-root (expand-file-name ".." cube-test-dir))
         (cube-program "cube")
         (cube-notify-method nil)
         (exec-path (cons cube-test-bin exec-path))
         (process-environment
          (cons (concat "PATH=" cube-test-bin ":" (getenv "PATH"))
                process-environment)))
     ,@body))

(defmacro cube-test-with-remote (&rest body)
  "Run BODY in remote mode against host \"ws\"."
  (declare (indent 0))
  `(let ((cube-remote-host "ws")
         (cube-root "~/Public/software/borg-cube")
         (cube-program "cube")
         (cube-notify-method nil)
         (cube-claude-tui 'inherit))
     ,@body))

(defmacro cube-test-with-clean-rolodex (&rest body)
  "Run BODY with an empty session registry, restoring it afterwards."
  (declare (indent 0))
  `(let ((cube-rolodex--sessions nil)
         (cube-rolodex--idle-timer (or cube-rolodex--idle-timer 'disabled))
         (cube--attention-items nil)
         (cube--status-json nil))
     ,@body))

(defmacro cube-test-wait-until (form &optional seconds)
  "Process output until FORM is non-nil or SECONDS (default 10) pass."
  (declare (indent 1))
  `(with-timeout ((or ,seconds 10) (ert-fail (format "timed out waiting for %S" ',form)))
     (while (not ,form) (accept-process-output nil 0.05))))

(defun cube-test-temp-file (prefix &optional text suffix)
  "Return a temp file named after PREFIX holding TEXT, with SUFFIX."
  (let ((file (make-temp-file prefix nil suffix)))
    (when text (with-temp-file file (insert text)))
    file))

(provide 'cube-test-helper)
;;; cube-test-helper.el ends here
