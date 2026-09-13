;;; cube-literature-test.el --- The literature section of the dashboard  -*- lexical-binding: t; -*-

;;; Commentary:
;; `cube literature --json' feeds one dashboard section.  RET opens the digest
;; markdown, `o' opens the paper itself in a browser.

;;; Code:

(require 'cube-test-helper)

(defun cube-literature-test--entries ()
  "Return the entries of the literature fixture."
  (cube-get (cube-test-read-fixture "literature.json") 'entries))

(ert-deftest cube-literature-normalize-entry ()
  (let* ((items (mapcar #'cube-dashboard--normalize-literature
                        (cube-literature-test--entries)))
         (first (car items))
         (second (cadr items)))
    (should (eq (plist-get first :type) 'literature))
    (should (equal (plist-get first :id) "arxiv:2609.01234v1"))
    (should (string-prefix-p "[high] " (plist-get first :label)))
    (should (string-match-p "Temporal knowledge graph embeddings"
                            (plist-get first :label)))
    (should (string-match-p "(arxiv)" (plist-get first :detail)))
    (should (string-match-p "for: project nih-temporal-kg, student gus-student"
                            (plist-get first :detail)))
    (should (string-match-p "(biorxiv)" (plist-get second :detail)))
    (should (string-match-p "topic protein-function-prediction"
                            (plist-get second :detail)))))

(ert-deftest cube-literature-normalize-tolerates-missing-relevance ()
  (let ((item (cube-dashboard--normalize-literature
               '((id . "arxiv:1") (title . "Untargeted") (priority . "low")))))
    (should (equal (plist-get item :id) "arxiv:1"))
    (should (stringp (plist-get item :detail)))
    (should-not (string-match-p "for:" (plist-get item :detail)))))

(ert-deftest cube-literature-section-renders ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (cube-test-with-dashboard
        (cube-test-dashboard-load-fixtures)
        (with-current-buffer (get-buffer-create "*cube*")
          (cube-dashboard-mode)
          (cube-dashboard--render)
          (let ((text (buffer-string)))
            (should (string-match-p "^Literature (2)" text))
            (should (string-match-p "Temporal knowledge graph embeddings" text))))))))

(ert-deftest cube-literature-section-empty-message ()
  (cube-test-with-local
    (cube-test-with-clean-rolodex
      (cube-test-with-dashboard
        (cube-test-dashboard-load-fixtures)
        (setf (alist-get 'literature cube-dashboard--data)
              (list :json '((entries . [])) :time (current-time) :error nil))
        (with-current-buffer (get-buffer-create "*cube*")
          (cube-dashboard-mode)
          (cube-dashboard--render)
          (should (string-match-p "no new relevant preprints" (buffer-string))))))))

(ert-deftest cube-literature-visit-opens-the-digest-markdown ()
  (cube-test-with-dashboard
    (setf (alist-get 'literature cube-dashboard--data)
          (list :json (cube-test-read-fixture "literature.json")
                :time (current-time) :error nil))
    (let ((opened nil))
      (cl-letf (((symbol-function 'cube-open-file)
                 (lambda (file &optional _line) (setq opened file))))
        (cube-dashboard--visit-literature "arxiv:2609.01234v1" nil))
      (should (equal opened "briefings/literature/2026-09-04.md")))))

(ert-deftest cube-literature-o-opens-the-paper-url ()
  (let* ((entry (car (cube-literature-test--entries)))
         (item (cube-dashboard--normalize-literature entry))
         (visited nil))
    (cl-letf (((symbol-function 'cube-dashboard--current-item) (lambda () item))
              ((symbol-function 'browse-url) (lambda (url) (setq visited url))))
      (cube-dashboard-open-url))
    (should (equal visited "https://arxiv.org/abs/2609.01234v1"))))

(ert-deftest cube-literature-o-falls-back-to-visit-without-a-url ()
  (let ((item (cube-dashboard--normalize-bead '((id . "cube-1") (title . "x"))))
        (visited nil))
    (cl-letf (((symbol-function 'cube-dashboard--current-item) (lambda () item))
              ((symbol-function 'cube-dashboard-visit-item)
               (lambda (it) (setq visited (plist-get it :id))))
              ((symbol-function 'browse-url) (lambda (_url) (ert-fail "browsed a bead"))))
      (cube-dashboard-open-url))
    (should (equal visited "cube-1"))))

(ert-deftest cube-literature-is-a-dashboard-call-and-section ()
  (should (assq 'literature cube-dashboard--calls))
  (should (equal (cdr (assq 'literature cube-dashboard--calls)) '("literature")))
  (should (memq 'literature cube-dashboard-sections))
  (should (assq 'literature cube-dashboard-visit-table)))

(ert-deftest cube-literature-key-legend-names-o ()
  (should (equal (cdr (assoc "o" cube-dashboard-mode-key-help)) "url"))
  (should (eq (lookup-key cube-dashboard-mode-map (kbd "o"))
              #'cube-dashboard-open-url))
  (should (string-match-p "o url" (cube-key-legend-string 'cube-dashboard-mode))))

(provide 'cube-literature-test)
;;; cube-literature-test.el ends here
