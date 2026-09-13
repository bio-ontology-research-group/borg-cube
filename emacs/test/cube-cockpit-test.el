;;; cube-cockpit-test.el --- Tests for cube-cockpit  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(ert-deftest cube-cockpit-layout-plan-keeps-dashboard-to-a-third ()
  (let* ((plan (cube-cockpit--layout-plan 120 90))
         (left (plist-get plan :left-width))
         (top (plist-get plan :top-height))
         (bottom (plist-get plan :bottom-height)))
    (should (= left 26))
    (should (= top 60))
    (should (= bottom 30))
    (should (< left 120))))

(ert-deftest cube-cockpit-layout-plan-has-small-frame-minimums ()
  (let ((plan (cube-cockpit--layout-plan 40 12)))
    (should (>= (plist-get plan :left-width) 18))
    (should (>= (plist-get plan :bottom-height) 4))))

(ert-deftest cube-cockpit-restore-without-saved-state-quits ()
  (let ((quit nil))
    (cl-letf (((symbol-function 'quit-window) (lambda (&rest _) (setq quit t))))
      (cube-cockpit-restore))
    (should quit)))

(provide 'cube-cockpit-test)
;;; cube-cockpit-test.el ends here
