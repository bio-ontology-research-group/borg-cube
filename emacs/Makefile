# borg-cube Emacs cockpit: byte-compile with warnings as errors, run ert.
#
#   make check      compile + test
#   make compile    byte-compile every *.el (warnings are errors)
#   make test       run the ert suites in test/
#   make contract   run real-backend cockpit payload contracts
#   make clean      remove .elc files
#
# The installed transient-20231103 (0.4.3) shadows the built-in 0.7.2 for
# the user's magit; compile and test against it so the menu stays on the
# 0.4-compatible API. magit-section (2023 snapshot, needs dash and compat)
# and markdown-mode come from the same elpa directory. Override the *_DIR
# variables if they live elsewhere.

EMACS      ?= emacs
ELPA       ?= $(HOME)/.emacs.d/elpa
TRANSIENT_DIR ?= $(firstword $(wildcard $(ELPA)/transient-20231103*))
COMPAT_DIR    ?= $(firstword $(wildcard $(ELPA)/compat-*))
DASH_DIR      ?= $(firstword $(wildcard $(ELPA)/dash-*))
MAGIT_SECTION_DIR ?= $(firstword $(wildcard $(ELPA)/magit-section-*))
MARKDOWN_DIR  ?= $(firstword $(wildcard $(ELPA)/markdown-mode-*))

LOAD_PATH  := -L . $(if $(TRANSIENT_DIR),-L $(TRANSIENT_DIR)) $(if $(COMPAT_DIR),-L $(COMPAT_DIR)) \
              $(if $(DASH_DIR),-L $(DASH_DIR)) $(if $(MAGIT_SECTION_DIR),-L $(MAGIT_SECTION_DIR)) \
              $(if $(MARKDOWN_DIR),-L $(MARKDOWN_DIR))
BATCH      := $(EMACS) -Q --batch $(LOAD_PATH)

SRC   := cube-core.el cube-term.el cube-rolodex.el cube-server.el cube-beads.el \
         cube-org.el cube-project.el cube-roster.el cube-review.el cube-decisions.el cube-people.el cube-goals.el \
         cube-agents.el cube-pipeline.el cube-dashboard.el cube-tier.el cube-cockpit.el cube-watch.el cube-menu.el \
         borg-cube.el
ELC   := $(SRC:.el=.elc)
TESTS := $(wildcard test/*-test.el)

.PHONY: all check compile test contract clean transient-version

all: check

check: compile test

compile: $(ELC)

%.elc: %.el
	$(BATCH) --eval '(setq byte-compile-error-on-warn t)' -f batch-byte-compile $<

test: compile
	$(BATCH) -L test \
	  $(foreach t,$(TESTS),-l $(t)) \
	  -f ert-run-tests-batch-and-exit

contract: compile
	$(BATCH) -L test -l cube-contract-test.el -f ert-run-tests-batch-and-exit

transient-version:
	$(BATCH) --eval '(progn (require (quote transient)) (princ (format "transient from %s\n" (locate-library "transient"))))'

clean:
	rm -f $(ELC) test/*.elc
