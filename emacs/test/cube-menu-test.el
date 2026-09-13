;;; cube-menu-test.el --- Tests for the command catalogue and menus  -*- lexical-binding: t; -*-

;;; Code:

(require 'cube-test-helper)

(defun cube-menu-test--commands (map)
  "Return command symbols bound in MAP, including nested prefix maps."
  (let (commands)
    (map-keymap (lambda (_event binding)
                  (cond ((keymapp binding)
                         (setq commands (nconc (cube-menu-test--commands binding) commands)))
                        ((commandp binding) (push binding commands))))
                map)
    commands))

(defun cube-menu-test--submenu (menu title)
  "Return TITLE's submenu from MENU, whose first element is its name."
  (seq-find (lambda (item) (and (listp item)
                               (equal (symbol-name (car item)) title)))
            (cdr menu)))

(ert-deftest cube-menu-command-table-round-trip ()
  "The global keymap and its table must not drift apart."
  (let ((map-commands (sort (mapcar #'symbol-name
                                    (cube-menu-test--commands cube-command-map))
                            #'string<))
        (table-commands
         (sort (mapcar (lambda (entry) (symbol-name (plist-get entry :command)))
                       (cube-menu--global-entries))
               #'string<)))
    (should (equal map-commands table-commands)))
  (dolist (entry cube-command-table)
    (should (stringp (plist-get entry :help)))
    (should-not (string-empty-p (string-trim (plist-get entry :help))))))

(ert-deftest cube-menu-is-on-global-mode-map ()
  "The Cube menu is a real menu-bar binding of the global minor mode."
  (let ((menu (lookup-key cube-mode-map [menu-bar Cube])))
    (should menu)
    (dolist (title '("Dashboard" "Sessions" "Work" "Goals" "Pipelines" "Agents" "People"
                     "Projects" "Review" "Control" "Configure" "Help"))
      (should (cube-menu-test--submenu menu title)))
    (should (lookup-key cube-mode-map [menu-bar]))
    ;; This is the menu-bar map that tmm-menubar traverses in a terminal.
    (should (lookup-key cube-mode-map [menu-bar Cube]))))

(ert-deftest cube-menu-configure-radio-and-toggle-state ()
  "Configure menu button expressions track the customization variables."
  (let* ((configure (cube-menu--configure-menu))
         (terminal (seq-find (lambda (item) (and (listp item)
                                                 (equal (car item) "Terminal backend")))
                             (cdr configure)))
         (eat (seq-find (lambda (item) (equal (aref item 0) "eat"))
                        (cdr terminal)))
         (auto (seq-find (lambda (item) (and (vectorp item)
                                             (equal (aref item 0) "Auto refresh dashboard")))
                         (cdr configure))))
    (let ((cube-terminal-backend 'eat)
          (cube-dashboard-auto-refresh t))
      (should (eval (aref eat 5)))
      (should (eval (aref auto 5))))
    (let ((cube-terminal-backend 'vterm)
          (cube-dashboard-auto-refresh nil))
      (should-not (eval (aref eat 5)))
      (should-not (eval (aref auto 5))))))

(ert-deftest cube-menu-mode-menus-and-help-bindings ()
  "Every requested cockpit mode has its own menu and question-mark help."
  (dolist (map '(cube-dashboard-mode-map cube-project-mode-map cube-roster-mode-map
                 cube-review-mode-map cube-beads-list-mode-map cube-fleet-mode-map
                 cube-session-mode-map))
    (let ((map (symbol-value map)))
      (should (lookup-key map (kbd "?")))
      (should (lookup-key map [menu-bar])))))

(ert-deftest cube-menu-dashboard-rows-have-mouse-actions ()
  "Dashboard rows carry RET and context actions from the command table."
  (cube-test-with-dashboard
    (cube-test-dashboard-load-fixtures)
    (with-current-buffer (get-buffer-create "*cube*")
      (cube-dashboard-mode)
      (cube-dashboard--render)
      (goto-char (point-min))
      (re-search-forward "Outbound email to Alex")
      (let ((map (get-text-property (1- (point)) 'keymap)))
        (should (eq (lookup-key map [mouse-1]) #'cube-dashboard-mouse-visit))
        (should (eq (lookup-key map [mouse-3]) #'cube-dashboard-mouse-context))))
    (dolist (type '(bead session student person paper repo project incident approval))
      (should (cube-menu--context-items type)))))

(ert-deftest cube-menu-groups-agents-by-host-and-shows-laptop-worker-state ()
  (let ((cube-agent--cache (cube-test-read-fixture "agents.json"))
        (cube--doctor-json (cube-test-read-fixture "doctor.json")))
    (let ((agents (cube-menu--agents-filter nil))
          (control (cube-menu--control-filter nil)))
      (should (seq-find (lambda (item) (and (listp item) (equal (car item) "laptop")))
                        agents))
      (should (seq-find (lambda (item) (and (listp item) (equal (car item) "ws")))
                        agents))
      (should (string-match-p "Laptop timer: installed" (prin1-to-string control))))
    (let* ((menu (cube-menu--global-menu))
           (control (seq-find (lambda (item) (and (listp item)
                                                  (equal (car item) "Control")))
                              (cdr menu))))
      (should (string-match-p "Laptop worker: run once now" (prin1-to-string control))))))

(provide 'cube-menu-test)
;;; cube-menu-test.el ends here
