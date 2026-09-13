;;; cube-keys-test.el --- The in-buffer key legend of every cube mode  -*- lexical-binding: t; -*-

;;; Commentary:
;; The legend must never drift from the bindings: every legend key is bound in
;; the mode map, and every action bound in that map appears in the legend.

;;; Code:

(require 'cube-test-helper)

(defun cube-keys--map (mode)
  "Return the keymap of MODE."
  (symbol-value (intern (format "%s-map" mode))))

(ert-deftest cube-keys-every-cockpit-mode-has-a-legend ()
  "The dashboard, agents, rolodex, beads, review, pipeline and goal buffers."
  (dolist (mode '(cube-dashboard-mode cube-agent-mode cube-fleet-mode
                  cube-beads-mode cube-beads-list-mode cube-review-mode
                  cube-decisions-mode cube-pipeline-mode cube-goal-mode))
    (should (memq mode cube-key-legend-modes))
    (should (cube-key-legend-alist mode))))

(ert-deftest cube-keys-legend-keys-are-bound-in-the-mode-map ()
  "Nothing in a legend is a key the buffer does not answer."
  (dolist (mode cube-key-legend-modes)
    (let ((map (cube-keys--map mode)))
      (dolist (pair (cube-key-legend-alist mode))
        (let ((command (lookup-key map (kbd (car pair)))))
          (should (commandp command)))))))

(ert-deftest cube-keys-every-action-binding-has-a-legend-entry ()
  "Every non-navigation key of a cube buffer is named in its legend."
  (dolist (mode cube-key-legend-modes)
    (let* ((map (cube-keys--map mode))
           (legend (cube-key-legend-alist mode))
           (named (mapcar (lambda (pair) (lookup-key map (kbd (car pair)))) legend)))
      (dolist (binding (cube--keymap-own-bindings map))
        (let ((key (car binding)) (command (cdr binding)))
          (unless (or (memq command cube-key-legend-navigation-commands)
                      (memq command named)
                      (equal key "?"))
            (ert-fail (format "%s binds %s to %s with no legend entry"
                              mode key command))))))))

(ert-deftest cube-keys-legend-string-ends-with-the-all-keys-hint ()
  (let ((text (cube-key-legend-string 'cube-dashboard-mode)))
    (should (string-prefix-p "RET open  t tell  i inbox  w workday  T talk" text))
    (should (string-match-p "c claim" text))
    (should (string-match-p "y yes" text))
    (should (string-match-p "n no" text))
    (should (string-match-p "a answer" text))
    (should (string-match-p "D decisions" text))
    (should (string-match-p "k close" text))
    (should (string-match-p "d dismiss" text))
    (should (string-match-p "g refresh" text))
    (should (string-suffix-p "? all keys" text))
    ;; one or two lines, never a wall of text
    (should (<= (length (split-string text "\n")) 2))))

(ert-deftest cube-keys-legend-can-be-switched-off ()
  (with-temp-buffer
    (let ((cube-show-key-legend nil))
      (cube-key-legend-insert 'cube-dashboard-mode)
      (should (string-empty-p (buffer-string))))
    (let ((cube-show-key-legend t))
      (cube-key-legend-insert 'cube-dashboard-mode)
      (should (string-match-p "RET open" (buffer-string))))))

(ert-deftest cube-keys-question-mark-opens-the-mode-transient ()
  "`?' is bound in every cube mode and its transient exists and is grouped."
  (dolist (mode cube-key-legend-modes)
    (should (eq (lookup-key (cube-keys--map mode) (kbd "?")) #'cube-mode-keys))
    (let ((prefix (cube-key-legend-transient-symbol mode)))
      (should (fboundp prefix))
      (should (get prefix 'transient--prefix))))
  (let ((groups (mapcar (lambda (group) (aref group 0))
                        (cube-key-legend--transient-layout 'cube-dashboard-mode))))
    (should (member "Open" groups))
    (should (member "Act" groups))
    (should (member "Agents" groups))
    (should (equal groups (seq-filter (lambda (title) (member title groups))
                                      '("Open" "Act" "Agents" "Navigate"))))))

(ert-deftest cube-keys-decisions-legend-and-transient-cover-the-answer-keys ()
  "The decisions buffer names y, n, a and its transient groups them."
  (let ((text (cube-key-legend-string 'cube-decisions-mode)))
    (should (string-match-p "y yes" text))
    (should (string-match-p "n no" text))
    (should (string-match-p "a answer" text))
    (should (string-suffix-p "? all keys" text)))
  (let ((groups (mapcar (lambda (group) (aref group 0))
                        (cube-key-legend--transient-layout 'cube-decisions-mode))))
    (should (member "Act" groups))
    (should (member "Open" groups))))

(ert-deftest cube-keys-tabulated-buffers-carry-the-legend-on-the-header-line ()
  "The beads and fleet lists print their columns and keep the legend on top."
  (dolist (mode '(cube-beads-list-mode cube-fleet-mode))
    (with-temp-buffer
      (funcall mode)
      (should-not tabulated-list-use-header-line)
      (should (stringp header-line-format))
      (should (string-match-p "RET " header-line-format))
      (should (string-match-p "all keys" header-line-format)))))

(provide 'cube-keys-test)
;;; cube-keys-test.el ends here
