;;; cube-menu.el --- Menus and command metadata for the cockpit  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Robert Hoehndorf

;; Author: Robert Hoehndorf
;; Keywords: tools, convenience

;;; Commentary:

;; This is the command catalogue for the Emacs cockpit.  Global bindings,
;; the Cube menu, the keyboard transient, mode menus and item context menus
;; all consume this table.  Data menus such as live sessions and projects
;; use their already cached payloads and never fetch while a menu is opening.

;;; Code:

(require 'cl-lib)
(require 'seq)
(require 'subr-x)
(require 'easymenu)
(require 'cus-edit)
(require 'transient)
(require 'cube-core)
(require 'cube-term)
(require 'cube-rolodex)
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
(require 'cube-watch)
(require 'cube-agents)
(require 'cube-pipeline)

(declare-function cube-doctor "borg-cube" ())
(declare-function cube-refresh "borg-cube" ())
(declare-function cube-send "borg-cube" (start end))
(declare-function cube--start-timers "borg-cube" ())
(defvar cube-mode)

(defvar cube-mode-map
  (make-sparse-keymap)
  "Keymap of `cube-mode'.")

(defconst cube-command-table
  '((:command cube-dashboard :label "Open dashboard" :key "d"
     :help "Open the live borg-cube dashboard." :group dashboard :global t)
    (:command cube-cockpit :label "Cockpit layout" :key "C"
     :help "Arrange fleet, session and dashboard panes." :group dashboard :global t)
    (:command cube-fleet-list :label "Fleet" :key "l"
     :help "List local and host sessions." :group dashboard :global t)
    (:command cube-attention :label "Loudest attention item" :key "!"
     :help "Open the loudest cached attention item." :group dashboard :global t)
    (:command cube-attention-1 :label "Attention item 1" :key "1"
     :help "Open the first cached attention item." :group dashboard :global t)
    (:command cube-attention-2 :label "Attention item 2" :key "2"
     :help "Open the second cached attention item." :group dashboard :global t)
    (:command cube-attention-3 :label "Attention item 3" :key "3"
     :help "Open the third cached attention item." :group dashboard :global t)
    (:command cube-budget :label "Budget" :key "U"
     :help "Show cached tier and runner budget information." :group dashboard :global t)
    (:command cube-watch :label "Watch a task" :key "f"
     :help "Follow one bead: its run, live tool trail and result." :group work :global t)
    (:command cube-watch-new :label "New task and watch" :key "F"
     :help "Create a bead (dry-run, confirm, apply) and open its watch buffer."
     :group work :global t)

    (:command cube-watch-refresh :label "Refresh" :key "g"
     :help "Refetch the bead, its newest run and the event backlog." :group work
     :mode cube-watch-mode)
    (:command cube-watch-show-prompt :label "Show prompt" :key "p"
     :help "Dry-run the role on this bead and show the assembled prompt, runner and model."
     :group work :mode cube-watch-mode)
    (:command cube-watch-start :label "Start run" :key "s"
     :help "Dry-run, confirm and start the role on this bead attached in tmux."
     :group work :mode cube-watch-mode)
    (:command cube-watch-resume :label "Resume run" :key "S"
     :help "Start with --resume for the bead's stored session." :group work
     :mode cube-watch-mode)
    (:command cube-watch-attach :label "Attach session" :key "a"
     :help "Jump to the attached run session in the rolodex." :group work
     :mode cube-watch-mode)
    (:command cube-watch-open-run :label "Open run directory" :key "o"
     :help "Open runs/<id>/ on the host." :group work :mode cube-watch-mode)
    (:command cube-watch-open-artifact :label "Open artifact" :key "O"
     :help "Open audit.md, notes.md or result.json of the run." :group work
     :mode cube-watch-mode)
    (:command cube-watch-open-bead :label "Open bead" :key "l"
     :help "Open the bead view." :group work :mode cube-watch-mode)
    (:command cube-watch-review :label "Preview review gate" :key "r"
     :help "cube review ID --dry-run: who must review, what would change." :group work
     :mode cube-watch-mode)
    (:command cube-watch-approvals :label "Approvals" :key "A"
     :help "Open the approval queue; empty means nothing outbound was requested."
     :group work :mode cube-watch-mode)

    (:command cube-agent-talk :label "Talk to agent" :key "@"
     :help "Attach to the coordinator, or choose a standing agent with C-u."
     :group agents :global t :context t :item-types (agent))
    (:command cube-agent-tell :label "Tell agent" :key "."
     :help "Send text to a standing agent's durable inbox."
     :group agents :global t :context t :item-types (agent))
    (:command cube-ask-coordinator :label "Ask the coordinator" :key ","
     :help "Send a request to the coordinator agent's inbox."
     :group agents :global t)
    (:command cube-agent-new :label "New agent" :key "menu"
     :help "Create a standing agent through a guarded transient."
     :group agents :menu-only t)
    (:command cube-agent-workday :label "Run workday" :key "menu"
     :help "Preview and confirm the selected agent's workday now."
     :group agents :menu-only t :context t :item-types (agent))
    (:command cube-agent-report :label "Weekly report" :key "menu"
     :help "Show the selected standing agent's weekly report."
     :group agents :menu-only t :context t :item-types (agent))
    (:command cube-agent-pause-resume :label "Pause or resume" :key "menu"
     :help "Preview and confirm pausing or resuming a standing agent."
     :group agents :menu-only t :context t :item-types (agent))
    (:command cube-agent-inbox :label "Read inbox now" :key "menu"
     :help "Preview and confirm an inbox-only workday for the selected agent."
     :group agents :menu-only t :context t :item-types (agent))

    (:command cube-rolodex-next :label "Next session" :key "n"
     :help "Show the next session in the rolodex ring." :group sessions :global t)
    (:command cube-rolodex-prev :label "Previous session" :key "N"
     :help "Show the previous session in the rolodex ring." :group sessions :global t)
    (:command cube-rolodex-jump :label "Jump to session" :key "j"
     :help "Choose a live session by name." :group sessions :global t)
    (:command cube-rolodex-toggle :label "Toggle previous session" :key "b"
     :help "Switch between the current and previous session buffer."
     :group sessions :global t :enable-predicate cube-menu-toggle-available-p)
    (:command cube-rolodex-new-claude :label "New Claude session" :key "c"
     :help "Start a new Claude Code session." :group sessions :global t)
    (:command cube-rolodex-new-codex :label "New Codex session" :key "x"
     :help "Start a new Codex session." :group sessions :global t)
    (:command cube-rolodex-new-hermes :label "New Hermes session" :key "h"
     :help "Start a new Hermes session." :group sessions :global t)
    (:command cube-rolodex-new-shell :label "New shell session" :key "$"
     :help "Start a new shell session." :group sessions :global t)
    (:command cube-rolodex-list-remote :label "Attach tmux session" :key "L"
     :help "List cube tmux sessions on the remote host and attach one."
     :group sessions :global t)
    (:command cube-rolodex-adopt :label "Adopt session" :key "E"
     :help "Preview and adopt an existing tmux session into a project."
     :group sessions :global t)
    (:command cube-rolodex-kill :label "Kill session" :key "k"
     :help "Close the selected session buffer; remote tmux keeps running."
     :group sessions :global t :enable-predicate cube-menu-session-available-p
     :item-types (session))
    (:command cube-rolodex-restart :label "Restart or resume session" :key "R"
     :help "Restart the selected session, optionally with a resume id."
     :group sessions :global t :enable-predicate cube-menu-session-available-p
     :item-types (session))
    (:command cube-rolodex-toggle-pin :label "Pin or unpin session" :key "t"
     :help "Pin the selected session to the front of its group."
     :group sessions :global t :enable-predicate cube-menu-session-available-p
     :item-types (session))
    (:command cube-send :label "Send region" :key "y"
     :help "Send the region or an @file:line reference to a session."
     :group sessions :global t :enable-predicate cube-menu-session-available-p)

    (:command cube-run-role :label "Run role" :key "r"
     :help "Preview the effective profile, then start a role runner."
     :group work :global t)
    (:command cube-beads-assign :label "Assign bead" :key "a"
     :help "Choose a bead and prepare its guarded assignment." :group work :global t)
    (:command cube-beads-claim-current :label "Claim bead" :key "q"
     :help "Claim the selected bead after the write confirmation."
     :group work :global t :enable-predicate cube-menu-bead-available-p
     :item-types (bead))
    (:command cube-beads-close-current :label "Close bead" :key "Q"
     :help "Close the selected bead after asking for a reason." :group work :global t
     :enable-predicate cube-menu-bead-available-p :item-types (bead))
    (:command cube-beads-ready :label "Ready beads" :key "w"
     :help "List ready beads from the backend." :group work :global t)
    (:command cube-beads-create :label "Create bead" :key "W"
     :help "Create a bead with acceptance and provenance fields." :group work :global t)
    (:command cube-beads-from-heading :label "Bead from org heading" :key "i"
     :help "Create a bead from the org heading at point." :group work :global t)

    (:command cube-goals :label "Goals" :key "O"
     :help "Open cached goals and refresh them asynchronously." :group goals :global t)
    (:command cube-goal-new :label "New goal" :key "G"
     :help "Create a new goal through the backend." :group goals :global t)
    (:command cube-goal-decompose :label "Decompose goal" :key "menu"
     :help "Break a cached goal into actionable work." :group goals :menu-only t)
    (:command cube-goal-spin-agent :label "Spin agent" :key "menu"
     :help "Start an agent for a cached goal." :group goals :menu-only t)

    (:command cube-pipeline-new :label "New pipeline" :key "P n"
     :help "Create a research pipeline from sent mail through a preview."
     :group pipelines :global t)
    (:command cube-pipeline-list :label "List pipelines" :key "P l"
     :help "List research pipeline epics and their next actions."
     :group pipelines :global t)
    (:command cube-pipeline-show :label "Show pipeline" :key "P s"
     :help "Choose and inspect one research pipeline."
     :group pipelines :global t)
    (:command cube-pipeline-advance :label "Advance pipeline" :key "P a"
     :help "Apply one confirmed deterministic pipeline transition."
     :group pipelines :global t)
    (:command cube-pipeline-rehearse :label "Rehearsal" :key "P r"
     :help "Run the offline pipeline rehearsal in a visible shell session."
     :group pipelines :global t)

    (:command cube-roster :label "Roster" :key "p"
     :help "Compare people across the roster sources." :group people :global t)
    (:command cube-people :label "People board" :key "u"
     :help "Open the operational board for current group members." :group people :global t)
    (:command cube-org-edit :label "Org editing" :key "o"
     :help "Open the guarded org editing commands." :group people :global t)
    (:command cube-student-session :label "Student session" :key "s"
     :help "Start or show an advisor session for a student." :group people :global t)
    (:command cube-student-dossier :label "Student dossier" :key "S"
     :help "Open a student's dossier." :group people :global t)
    (:command cube-org-meeting-note :label "Meeting note" :key "m"
     :help "Insert today's meeting note for a person." :group people :global t)
    (:command cube-org-pull-notes :label "Pull agent notes" :key "M"
     :help "Pull the latest advisor notes into a draft subtree." :group people :global t)
    (:command cube-papers :label "Papers" :key "P p"
     :help "List tracked papers." :group people :global t)
    (:command cube-org-papers-sync :label "Papers state sync" :key "A"
     :help "Compare and guardedly synchronize papers.org states." :group people :global t
     :item-types (paper))

    (:command cube-project-list :label "Projects list" :key "e"
     :help "Open the cached projects list and refresh it." :group projects :global t)

    (:command cube-review-queue :label "Review queue" :key "v"
     :help "Open the approval queue; outbound actions remain gated."
     :group review :global t)
    (:command cube-decisions :label "Decisions" :key "D"
     :help "Open everything the agents are waiting for you to answer."
     :group review :global t)

    (:command cube-tier-menu :label "Tier controls" :key "T"
     :help "Inspect and change model tier routing through dry-run plans."
     :group control :global t)
    (:command cube-refresh :label "Refresh" :key "g"
     :help "Refresh the cached attention list." :group control :global t)
    (:command cube-brief :label "Brief" :key "B"
     :help "Show the morning brief." :group control :global t)
    (:command cube-doctor :label "Doctor report" :key "H"
     :help "Run the backend doctor checks." :group control :global t)
    (:command cube-laptop-worker-run-once :label "Laptop worker: run once now" :key "menu"
     :help "Run cube worker --once --host laptop locally." :group control :menu-only t)
    (:command cube-kill-switch-toggle :label "Kill switch on or off" :key "K"
     :help "Toggle the backend kill switch after confirmation." :group control :global t)

    (:command cube-menu :label "Command menu" :key "?"
     :help "Open the keyboard command menu; this is also the Cube menu."
     :group help :global t)

    ;; Dashboard mode actions.
    (:command cube-dashboard-refresh :label "Refresh dashboard" :key "g"
     :help "Refresh every dashboard section." :group dashboard :mode cube-dashboard-mode)
    (:command cube-dashboard-visit :label "Open item or toggle section" :key "RET"
     :help "Open the row at point, or toggle its section." :group dashboard
     :mode cube-dashboard-mode :item-types (bead session student paper repo project goal pipeline agent incident approval run file)
     :context t)
    (:command cube-dashboard-visit :label "Open item or toggle section" :key "o"
     :help "Open the row at point, or toggle its section." :group dashboard
     :mode cube-dashboard-mode)
    (:command magit-section-forward :label "Next row" :key "n"
     :help "Move to the next dashboard section." :group dashboard :mode cube-dashboard-mode)
    (:command magit-section-backward :label "Previous row" :key "p"
     :help "Move to the previous dashboard section." :group dashboard :mode cube-dashboard-mode)
    (:command magit-section-toggle :label "Fold or unfold" :key "TAB"
     :help "Fold or unfold the section at point." :group dashboard :mode cube-dashboard-mode)
    (:command cube-dashboard-approve :label "Answer or approve item" :key "a"
     :help "Answer the decision at point, or approve the approval at point."
     :group dashboard :mode cube-dashboard-mode
     :item-types (approval decision) :context t)
    (:command cube-dashboard-yes :label "Yes" :key "y"
     :help "Answer the decision at point affirmatively." :group dashboard
     :mode cube-dashboard-mode :item-types (approval decision) :context t)
    (:command cube-dashboard-no :label "No" :key "n"
     :help "Answer the decision at point negatively." :group dashboard
     :mode cube-dashboard-mode :item-types (decision) :context t)
    (:command cube-decisions :label "Decisions" :key "D"
     :help "Open the decisions buffer from the dashboard." :group dashboard
     :mode cube-dashboard-mode)
    (:command cube-dashboard-reject :label "Reject item" :key "x"
     :help "Reject the approval at point." :group dashboard :mode cube-dashboard-mode
     :item-types (approval) :context t)
    (:command cube-dashboard-student-session :label "Student session" :key "s"
     :help "Start the advisor session for the student at point." :group dashboard
     :mode cube-dashboard-mode :item-types (student person bead) :context t)
    (:command cube-dashboard-student-dossier :label "Student dossier" :key "S"
     :help "Open the dossier for the student at point." :group dashboard
     :mode cube-dashboard-mode :item-types (student person bead) :context t)
    (:command cube-dashboard-meeting-note :label "Meeting note" :key "m"
     :help "Insert a meeting note for the student at point." :group dashboard
     :mode cube-dashboard-mode :item-types (student person bead) :context t)
    (:command cube-dashboard-assign :label "Assign item bead" :key "A"
     :help "Open assignment for the bead at point." :group dashboard
     :mode cube-dashboard-mode :item-types (bead) :context t)
    (:command cube-dashboard-claim :label "Claim bead" :key "c"
     :help "Claim the bead at point." :group dashboard :mode cube-dashboard-mode
     :item-types (bead) :context t)
    (:command cube-dashboard-kill :label "Close bead or kill session" :key "k"
     :help "Close the bead or kill the session at point." :group dashboard
     :mode cube-dashboard-mode :item-types (bead session) :context t)
    (:command cube-review-queue :label "Review queue" :key "v"
     :help "Open the approval queue from the dashboard." :group dashboard
     :mode cube-dashboard-mode)
    (:command cube-beads-list :label "Ready beads" :key "w"
     :help "Open the ready bead list." :group dashboard :mode cube-dashboard-mode)
    (:command cube-cockpit-restore :label "Restore layout" :key "q"
     :help "Restore the window layout saved before the cockpit." :group dashboard
     :mode cube-dashboard-mode)
    (:command cube-mode-help :label "Dashboard help" :key "?"
     :help "Show the dashboard actions and their bindings." :group dashboard
     :mode cube-dashboard-mode)

    ;; Project mode actions.
    (:command cube-project-revert :label "Refresh project" :key "g"
     :help "Refresh this project and its ready beads." :group projects :mode cube-project-mode)
    (:command cube-project--visit :label "Open bead or toggle section" :key "RET"
     :help "Open the bead at point, or toggle the project section." :group projects
     :mode cube-project-mode)
    (:command cube-project-assign :label "Assign project bead" :key "a"
     :help "Start an assignment preselected for this project." :group projects
     :mode cube-project-mode)
    (:command quit-window :label "Quit project" :key "q"
     :help "Close the project buffer." :group projects :mode cube-project-mode)
    (:command cube-mode-help :label "Project help" :key "?"
     :help "Show the project actions and their bindings." :group projects
     :mode cube-project-mode)

    ;; Roster mode actions.
    (:command cube-roster-refresh :label "Refresh roster" :key "g"
     :help "Refresh the roster comparison." :group people :mode cube-roster-mode)
    (:command cube-roster-visit :label "Open person or conflict" :key "RET"
     :help "Open the person, or show conflicting source values." :group people
     :mode cube-roster-mode)
    (:command cube-roster-sync-dry-run :label "Preview roster sync" :key "s"
     :help "Show the people.yaml diff without applying it." :group people
     :mode cube-roster-mode)
    (:command cube-roster-sync-apply :label "Apply roster sync" :key "S"
     :help "Apply the roster sync after confirmation." :group people :mode cube-roster-mode)
    (:command quit-window :label "Quit roster" :key "q"
     :help "Close the roster buffer." :group people :mode cube-roster-mode)
    (:command cube-mode-help :label "Roster help" :key "?"
     :help "Show the roster actions and their bindings." :group people :mode cube-roster-mode)

    ;; People board actions.
    (:command cube-people-refresh :label "Refresh people" :key "g"
     :help "Refresh the operational people board." :group people :mode cube-people-mode)
    (:command cube-people-visit :label "Open extended dossier" :key "RET"
     :help "Open the person dossier with owed items and agenda." :group people
     :mode cube-people-mode :item-types (person) :context t)
    (:command cube-people-open-org :label "Open notes" :key "o"
     :help "Open the person's org notes." :group people :mode cube-people-mode
     :item-types (person) :context t)
    (:command cube-people-meeting-note :label "Meeting note" :key "m"
     :help "Add a dated meeting note for the person." :group people :mode cube-people-mode
     :item-types (person) :context t)
    (:command quit-window :label "Quit people board" :key "q"
     :help "Close the people board." :group people :mode cube-people-mode)
    (:command cube-mode-help :label "People board help" :key "?"
     :help "Show people board actions and bindings." :group people :mode cube-people-mode)

    ;; Focused goal actions.
    (:command cube-goal-revert :label "Refresh goal" :key "g"
     :help "Refresh this goal and its child work." :group goals :mode cube-goal-mode)
    (:command cube-goal-new :label "New goal" :key "G"
     :help "Set a new goal through the guarded transient." :group goals :mode cube-goal-mode)
    (:command cube-goal-visit :label "Open selected item" :key "RET"
     :help "Open the selected bead or person dossier." :group goals :mode cube-goal-mode)
    (:command cube-goal-spin-agent :label "Spin ready agent" :key "s"
     :help "Preview then spin the ready agent bead at point." :group goals :mode cube-goal-mode)
    (:command cube-goal-run-agent :label "Run ready agent" :key "r"
     :help "Preview its runner profile, then attach the ready agent bead."
     :group goals :mode cube-goal-mode :item-types (agent) :context t)
    (:command cube-goal-add-to-agenda :label "Add owed item to agenda" :key "m"
     :help "Preview then add the selected owed item to the next meeting agenda."
     :group goals :mode cube-goal-mode)
    (:command cube-goal-decompose :label "Decompose for review" :key "d"
     :help "Create a dry-run decomposition proposal and open the review queue."
     :group goals :mode cube-goal-mode)
    (:command cube-goal-edit :label "Edit target or criteria" :key "e"
     :help "Edit when the backend advertises goal update." :group goals :mode cube-goal-mode
     :enable-predicate cube-goal--update-supported-p)
    (:command quit-window :label "Quit goal" :key "q"
     :help "Close the goal buffer." :group goals :mode cube-goal-mode)
    (:command cube-mode-help :label "Goal help" :key "?"
     :help "Show goal actions and bindings." :group goals :mode cube-goal-mode)

    ;; Research-pipeline mode actions.
    (:command cube-pipeline-revert :label "Refresh pipeline" :key "g"
     :help "Refresh the focused pipeline or pipeline list." :group pipelines
     :mode cube-pipeline-mode)
    (:command cube-pipeline-visit :label "Open bead or pipeline" :key "RET"
     :help "Open the selected bead or pipeline, or toggle its section."
     :group pipelines :mode cube-pipeline-mode)
    (:command cube-pipeline-advance :label "Advance pipeline" :key "A"
     :help "Apply one confirmed deterministic transition." :group pipelines
     :mode cube-pipeline-mode)
    (:command cube-pipeline-advance-dry-run :label "Preview advance" :key "d"
     :help "Show the dry-run plan for the next transition." :group pipelines
     :mode cube-pipeline-mode)
    (:command cube-pipeline-talk :label "Talk to coordinator" :key "T"
     :help "Attach to the coordinator session." :group pipelines :mode cube-pipeline-mode)
    (:command cube-pipeline-tell :label "Tell coordinator" :key "t"
     :help "Send a durable inbox message to the coordinator." :group pipelines
     :mode cube-pipeline-mode)
    (:command cube-pipeline-open-plan :label "Open plan" :key "o"
     :help "Open plan-v2.yaml, falling back to plan-v1.yaml, over TRAMP."
     :group pipelines :mode cube-pipeline-mode)
    (:command quit-window :label "Quit pipeline" :key "q"
     :help "Close the pipeline buffer." :group pipelines :mode cube-pipeline-mode)
    (:command cube-mode-help :label "Pipeline help" :key "?"
     :help "Show pipeline actions and their bindings." :group pipelines
     :mode cube-pipeline-mode)

    ;; Standing-agent mode actions.
    (:command cube-agent-revert :label "Refresh agent" :key "g"
     :help "Refresh the standing agent details." :group agents :mode cube-agent-mode)
    (:command cube-agent-visit :label "Open selected item or toggle group" :key "RET"
     :help "Open the item at point, or fold the group." :group agents
     :mode cube-agent-mode)
    (:command cube-agent-talk :label "Talk" :key "T"
     :help "Attach to this standing agent's session." :group agents :mode cube-agent-mode
     :context t :item-types (agent))
    (:command cube-agent-tell :label "Tell" :key "t"
     :help "Send this standing agent a durable inbox message." :group agents
     :mode cube-agent-mode :context t :item-types (agent))
    (:command cube-agent-workday :label "Run workday now" :key "w"
     :help "Preview and confirm this agent's workday." :group agents :mode cube-agent-mode
     :context t :item-types (agent))
    (:command cube-agent-pause-resume :label "Pause or resume" :key "p"
     :help "Preview and confirm pausing or resuming this agent." :group agents
     :mode cube-agent-mode :context t :item-types (agent))
    (:command cube-agent-report :label "Weekly report" :key "r"
     :help "Show this agent's weekly report." :group agents :mode cube-agent-mode
     :context t :item-types (agent))
    (:command cube-agent-edit-charter :label "Edit charter" :key "e"
     :help "Open this agent's charter over TRAMP." :group agents :mode cube-agent-mode
     :context t :item-types (agent))
    (:command cube-agent-approve :label "Route proposal to review" :key "a"
     :help "Open the proposal in the normal approval review queue." :group agents
     :mode cube-agent-mode :context t :item-types (proposal))
    (:command quit-window :label "Quit agent" :key "q"
     :help "Close the standing-agent buffer." :group agents :mode cube-agent-mode)
    (:command cube-mode-help :label "Agent help" :key "?"
     :help "Show standing-agent actions and bindings." :group agents :mode cube-agent-mode)

    ;; Review mode actions.
    (:command cube-review-refresh :label "Refresh queue" :key "g"
     :help "Refresh the approval queue." :group review :mode cube-review-mode)
    (:command cube-review-show-body :label "Load body" :key "RET"
     :help "Load the approval body at point." :group review :mode cube-review-mode)
    (:command cube-review-approve :label "Approval" :key "a"
     :help "Approve the approval at point." :group review :mode cube-review-mode)
    (:command cube-review-reject :label "Reject" :key "x/r"
     :help "Reject the approval at point with a reason." :group review :mode cube-review-mode)
    (:command cube-review-edit :label "Edit body" :key "e"
     :help "Edit the body before approving it." :group review :mode cube-review-mode)
    (:command cube-review-jump-session :label "Jump to session" :key "j"
     :help "Open the run session behind the approval." :group review :mode cube-review-mode)
    (:command cube-review-open-target :label "Open target" :key "o"
     :help "Open the approval's bead or recipient." :group review :mode cube-review-mode)
    (:command quit-window :label "Quit review" :key "q"
     :help "Close the review queue." :group review :mode cube-review-mode)
    (:command cube-mode-help :label "Review help" :key "?"
     :help "Show the review actions and their bindings." :group review :mode cube-review-mode)

    ;; Decisions mode actions.
    (:command cube-decisions-refresh :label "Refresh decisions" :key "g"
     :help "Refetch everything waiting for you." :group review
     :mode cube-decisions-mode)
    (:command cube-decisions-visit :label "Open bead or approval" :key "RET"
     :help "Open the bead or approval behind the decision at point." :group review
     :mode cube-decisions-mode :item-types (decision) :context t)
    (:command cube-decisions-yes :label "Yes" :key "y"
     :help "Answer yes, approve or accept." :group review :mode cube-decisions-mode
     :item-types (decision) :context t)
    (:command cube-decisions-no :label "No" :key "n"
     :help "Answer no or reject." :group review :mode cube-decisions-mode
     :item-types (decision) :context t)
    (:command cube-decisions-answer :label "Answer" :key "a"
     :help "Choose an option or type an answer." :group review
     :mode cube-decisions-mode :item-types (decision) :context t)
    (:command cube-decisions-open-evidence :label "Open evidence" :key "o"
     :help "Open the first evidence path of the decision at point." :group review
     :mode cube-decisions-mode)
    (:command cube-decisions-apply-policy :label "Apply policy" :key "P"
     :help "Answer now what the policy would answer at the next patrol tick."
     :group review :mode cube-decisions-mode)
    (:command quit-window :label "Quit decisions" :key "q"
     :help "Close the decisions buffer." :group review :mode cube-decisions-mode)
    (:command cube-mode-keys :label "Decisions help" :key "?"
     :help "Show the decision actions and their bindings." :group review
     :mode cube-decisions-mode)

    ;; Ready-bead list mode actions.
    (:command cube-beads--refresh :label "Refresh beads" :key "g"
     :help "Refresh the ready bead list." :group work :mode cube-beads-list-mode)
    (:command cube-beads-list-show :label "Open bead" :key "RET"
     :help "Show the bead at point." :group work :mode cube-beads-list-mode)
    (:command cube-beads-list-claim :label "Claim bead" :key "c"
     :help "Claim the bead at point." :group work :mode cube-beads-list-mode)
    (:command cube-beads-list-close :label "Close bead" :key "k"
     :help "Close the bead at point." :group work :mode cube-beads-list-mode)
    (:command cube-beads-list-run :label "Run agent bead" :key "r"
     :help "Preview its effective runner profile, then attach the bead runner."
     :group work :mode cube-beads-list-mode :item-types (bead) :context t)
    (:command cube-beads-create :label "Create bead" :key "+"
     :help "Create a new bead." :group work :mode cube-beads-list-mode)
    (:command cube-beads-list-student :label "Open student" :key "s"
     :help "Open the student behind the bead." :group work :mode cube-beads-list-mode)
    (:command cube-mode-help :label "Bead list help" :key "?"
     :help "Show the ready-bead actions and their bindings." :group work
     :mode cube-beads-list-mode)

    ;; Fleet mode actions.
    (:command cube-fleet-visit :label "Open session" :key "RET"
     :help "Open the session at point." :group sessions :mode cube-fleet-mode)
    (:command cube-fleet-adopt :label "Adopt session" :key "A"
     :help "Preview and adopt the session at point into a project."
     :group sessions :mode cube-fleet-mode :item-types (session) :context t)
    (:command cube-fleet-kill :label "Kill session" :key "k"
     :help "Kill the session at point." :group sessions :mode cube-fleet-mode)
    (:command cube-rolodex-list-remote :label "Attach tmux session" :key "r"
     :help "List remote tmux sessions and attach one." :group sessions
     :mode cube-fleet-mode)
    (:command cube-mode-help :label "Fleet help" :key "?"
     :help "Show the fleet actions and their bindings." :group sessions :mode cube-fleet-mode)

    ;; The terminal owns the major mode; this is a minor-mode menu.
    (:command cube-session-send-escape :label "Send ESC" :key "<escape>"
     :help "Send ESC to interrupt the terminal agent." :group sessions
     :mode cube-session-mode)
    (:command cube-session-send-backtab :label "Send S-TAB" :key "<backtab>"
     :help "Send S-TAB to cycle the agent mode." :group sessions
     :mode cube-session-mode)
    (:command cube-session-open-context :label "Open session context" :key "C-c C-o"
     :help "Open the session bead, run log or working directory." :group sessions
     :mode cube-session-mode)
    (:command cube-session-adopt :label "Adopt this session" :key "A"
     :help "Preview and adopt this attached tmux session into a project."
     :group sessions :mode cube-session-mode :item-types (session) :context t)
    (:command cube-mode-help :label "Session help" :key "?"
     :help "Show the session actions and their bindings." :group sessions
     :mode cube-session-mode))
  "Command and mode-action metadata for the cockpit.
Each entry has a command, label, key, help and group.  Global entries also
have `:global'; mode entries have `:mode'.")

(defun cube-menu--global-entries ()
  "Return the entries that become bindings under `C-c b'."
  (seq-filter (lambda (entry) (plist-get entry :global)) cube-command-table))

(defun cube-menu--define-command-map ()
  "Build the global prefix map from `cube-command-table'."
  (let ((map (make-sparse-keymap)))
    (dolist (entry (cube-menu--global-entries))
      (define-key map (kbd (plist-get entry :key)) (plist-get entry :command)))
    map))

(defvar cube-command-map (cube-menu--define-command-map)
  "Commands of the cockpit, bound under `cube-prefix-key'.")

(defun cube-menu-session-available-p ()
  "Return non-nil when a session action has a target."
  (or (cube-rolodex-session-for-buffer)
      (cube-rolodex-live-sessions)))

(defun cube-menu-toggle-available-p ()
  "Return non-nil when there is a previous or last session buffer."
  (or (buffer-live-p cube-rolodex--previous-buffer)
      (buffer-live-p cube-rolodex--last-session)))

(defun cube-menu-bead-available-p ()
  "Return non-nil when the current buffer has a bead target."
  (or (and (boundp 'cube-bead--id) cube-bead--id)
      (and (fboundp 'cube-dashboard--current-item)
           (let ((item (cube-dashboard--current-item)))
             (eq (plist-get item :type) 'bead)))
      (and (fboundp 'tabulated-list-get-id)
           (or (derived-mode-p 'cube-beads-mode)
               (derived-mode-p 'cube-beads-list-mode))
           (tabulated-list-get-id))))

(defun cube-menu--key-description (key &optional prefix)
  "Return a readable KEY description, prepending PREFIX when supplied."
  (if (equal key "menu")
      "menu"
    (condition-case nil
        (key-description
         (vconcat (and prefix (kbd prefix)) (kbd key)))
      (error key))))

(defun cube-menu--help (entry &optional prefix)
  "Return the displayed help for ENTRY, including its binding."
  (format "%s Key: %s."
          (string-trim-right (plist-get entry :help) "\\.")
          (cube-menu--key-description (plist-get entry :key) prefix)))

(defun cube-menu--item (entry &optional prefix)
  "Turn ENTRY into an easy-menu item, with its help and key."
  (let* ((label (plist-get entry :label))
         (command (plist-get entry :command))
         (pred (plist-get entry :enable-predicate))
         (item (list label command
                     :keys (cube-menu--key-description (plist-get entry :key) prefix)
                     :help (cube-menu--help entry prefix))))
    (when pred
      (setq item (append item (list :enable (list pred)))))
    (when (eq command 'cube-review-queue)
      (setq item (append item (list :label '(cube-menu--review-label)))))
    (vconcat item)))

(defun cube-menu--entries-for-group (group &optional mode)
  "Return table entries for GROUP, globally or for MODE."
  (seq-filter
   (lambda (entry)
     (and (eq (plist-get entry :group) group)
          (if mode
              (eq (plist-get entry :mode) mode)
            (plist-get entry :global))))
   cube-command-table))

(defun cube-menu--menu-entries-for-group (group)
  "Return global and menu-only entries for GROUP."
  (seq-filter
   (lambda (entry)
     (and (eq (plist-get entry :group) group)
          (or (plist-get entry :global) (plist-get entry :menu-only))))
   cube-command-table))

(defun cube-menu--group (title group &optional prefix)
  "Return a static submenu TITLE for GROUP."
  (cons title
        (cons :help
              (cons (format "Commands in the %s group." title)
                    (mapcar (lambda (entry) (cube-menu--item entry prefix))
                            (cube-menu--entries-for-group group))))))

(defun cube-menu--review-label ()
  "Return the review menu label with the cached approval count."
  (format "Review queue (%d)" (length cube-review--approvals)))

(defun cube-menu--cached-projects ()
  "Return cached projects without starting a backend call."
  (or cube-project--cache
      (and (fboundp 'cube-dashboard--json)
           (cube-get (cube-dashboard--json 'projects) 'projects))))

(defun cube-menu--session-item (session)
  "Return a dynamic menu item for SESSION."
  (let ((label (format "%s %s" (cube-rolodex--state-glyph (cube-session-state session))
                       (cube-rolodex--label session)))
        (help (format "Jump to the %s session."
                      (cube-rolodex--label session))))
    (vector label
            (lambda ()
              (interactive)
              (cube-rolodex--show (cube-session-buffer session)))
            :keys "menu"
            :help (format "%s Key: menu." help))))

(defun cube-menu--project-item (project)
  "Return a dynamic menu item for PROJECT."
  (let ((label (format "Open %s" (cube--string (cube-get project 'name))))
        (slug (cube--string (cube-get project 'slug))))
    (vector label
    (lambda ()
              (interactive)
              (cube-project-open slug project))
            :keys "menu"
            :help (format "Open project %s. Key: menu." slug))))

(defun cube-menu--goal-item (goal)
  "Return a dynamic menu item for GOAL."
  (vector (format "Open %s" (cube-goal--label goal))
          (lambda ()
            (interactive)
            (cube-goal-open goal))
          :keys "menu"
          :help (format "Open the cached goal %s. Key: menu." (cube-goal--id goal))))

(defun cube-menu--sessions-filter (items)
  "Prepend cached live sessions to the Sessions menu ITEMS."
  (let ((sessions (cube-rolodex-live-sessions)))
    (append (if sessions
            (mapcar #'cube-menu--session-item (cube-rolodex--ordered sessions))
            (list ["No live sessions (refreshing...)" ignore
                   :keys "menu" :help "No live sessions are cached yet. Key: menu."]))
            (when sessions (list "---"))
            items)))

(defun cube-menu--projects-filter (items)
  "Prepend cached projects to the Projects menu ITEMS."
  (let ((projects (cube-menu--cached-projects)))
    (append (if projects
                (mapcar #'cube-menu--project-item projects)
              (list ["No projects (refreshing...)" ignore
                     :keys "menu" :help "No projects are cached yet. Key: menu."]))
            (when projects (list "---"))
            items)))

(defun cube-menu--goals-filter (items)
  "Prepend cached goals to the Goals menu ITEMS."
  (let ((goals (seq-remove
                (lambda (goal)
                  (member (cube-get goal 'status) '("closed" "done" "ended" "inactive")))
                cube-goals--cache)))
    (append (if goals
                (mapcar #'cube-menu--goal-item goals)
            (list ["No goals (refreshing...)" ignore
                   :keys "menu" :help "No goals are cached yet. Key: menu."]))
            (when goals (list "---"))
            items)))

(defun cube-menu--cached-agents ()
  "Return cached standing agents without starting a backend call."
  (or cube-agent--cache
      (and (fboundp 'cube-dashboard--json)
           (cube-agents--list (cube-dashboard--json 'agents)))))

(defun cube-menu--agent-item (agent)
  "Return a dynamic menu item for standing AGENT."
  (let ((name (cube-agent--name agent)))
    (vector (format "%s %s  %s" (cube-agent--kind-glyph agent) name
                    (cube--string (cube-get agent 'title)))
            (lambda () (interactive) (cube-agent-talk nil name))
            :keys "menu"
            :help (format "Talk to standing agent %s. Key: menu." name))))

(defun cube-menu--agent-host-group (host agents)
  "Return the Agents submenu for HOST containing cached AGENTS."
  (cons host (mapcar #'cube-menu--agent-item agents)))

(defun cube-menu--agents-filter (items)
  "Prepend cached standing agents to the Agents menu ITEMS."
  (let ((agents (cube-menu--cached-agents)))
    (append (if agents
                (mapcar
                 (lambda (host)
                   (cube-menu--agent-host-group
                    host
                    (seq-filter (lambda (agent)
                                  (equal (cube-agent--host agent) host))
                                agents)))
                 (sort (delete-dups (mapcar #'cube-agent--host agents)) #'string<))
              (list ["No standing agents (refreshing...)" ignore
                     :keys "menu" :help "No standing agents are cached yet. Key: menu."]))
            (when agents (list "---"))
            items)))

(defun cube-menu--laptop-worker-timer-label ()
  "Return the cached laptop-worker timer indicator for the Control menu."
  (cond ((null cube--doctor-json) "Laptop timer: unknown (run Doctor)")
        ((cube-laptop-worker-timer-installed-p) "Laptop timer: installed")
        (t "Laptop timer: not installed")))

(defun cube-menu--control-filter (items)
  "Prepend the cached laptop-worker timer indicator to Control ITEMS."
  (append
   (list (vector (cube-menu--laptop-worker-timer-label) #'ignore
                 :enable nil :keys "menu"
                 :help "Reported by the latest cube doctor --json result. Key: menu.")
         "---")
   items))

;;;; Configuration menu

(defvar cube-menu--changed-settings nil
  "Variables changed through Configure and not saved yet.")

(defun cube-menu--set-setting (variable value)
  "Set VARIABLE to VALUE and remember it for the Save menu action."
  (set variable value)
  (cl-pushnew variable cube-menu--changed-settings)
  (when (memq variable '(cube-refresh-interval cube-dashboard-auto-refresh))
    (when (and (boundp 'cube-mode) cube-mode (fboundp 'cube--start-timers))
      (cube--start-timers)))
  (force-mode-line-update t))

(defun cube-menu-use-local-machine ()
  "Use this machine for backend calls."
  (interactive)
  (cube-menu--set-setting 'cube-remote-host nil))

(defun cube-menu-set-remote-host ()
  "Set the remote backend host."
  (interactive)
  (let ((host (read-string "Remote host (empty for this machine): "
                           cube-remote-host)))
    (cube-menu--set-setting 'cube-remote-host
                            (unless (string-empty-p (string-trim host)) host))))

(defun cube-menu-set-terminal-backend (backend)
  "Set the terminal BACKEND."
  (interactive)
  (cube-menu--set-setting 'cube-terminal-backend backend))

(defun cube-menu-set-dashboard-section (section)
  "Toggle dashboard SECTION."
  (interactive)
  (let ((sections (copy-sequence cube-dashboard-sections)))
    (cube-menu--set-setting
     'cube-dashboard-sections
     (if (memq section sections) (delq section sections)
       (append sections (list section))))))

(defun cube-menu-set-auto-refresh (value)
  "Set dashboard auto refresh to VALUE."
  (interactive)
  (cube-menu--set-setting 'cube-dashboard-auto-refresh value))

(defun cube-menu-set-refresh-interval ()
  "Set the automatic refresh interval."
  (interactive)
  (let* ((text (read-string "Refresh interval seconds (empty disables): "
                            (and cube-refresh-interval
                                 (number-to-string cube-refresh-interval))))
         (value (unless (string-empty-p (string-trim text))
                  (max 0 (string-to-number text)))))
    (cube-menu--set-setting 'cube-refresh-interval value)))

(defun cube-menu-set-notify-method (method)
  "Set desktop notification METHOD."
  (interactive)
  (cube-menu--set-setting 'cube-notify-method method))

(defun cube-menu-set-claude-tui (mode)
  "Set Claude TUI MODE."
  (interactive)
  (cube-menu--set-setting 'cube-claude-tui mode))

(defun cube-menu-set-attention-count ()
  "Set the number of attention items shown."
  (interactive)
  (cube-menu--set-setting
   'cube-attention-count
   (max 0 (string-to-number (read-string "Attention items (3): "
                                         (number-to-string cube-attention-count))))))

(defun cube-menu-save-settings ()
  "Save settings changed through the Configure menu."
  (interactive)
  (dolist (variable cube-menu--changed-settings)
    (customize-save-variable variable (symbol-value variable)))
  (setq cube-menu--changed-settings nil)
  (message "cube: settings saved"))

(defun cube-menu-all-settings ()
  "Open all borg-cube settings."
  (interactive)
  (customize-group 'borg-cube))

(defun cube-menu--selected (variable value)
  "Return an easy-menu selected expression for VARIABLE equal to VALUE."
  (if (null value)
      (list 'null variable)
    (list 'eq variable (list 'quote value))))

(defun cube-menu--radio-item (label function variable value help)
  "Return a radio item LABEL calling FUNCTION for VARIABLE VALUE."
  (vector label function
          :style 'radio
          :selected (cube-menu--selected variable value)
          :keys "menu"
          :help (format "%s Key: menu." help)))

(defun cube-menu--toggle-item (label function selected help)
  "Return a toggle item LABEL calling FUNCTION when SELECTED."
  (vector label function :style 'toggle :selected selected :keys "menu"
          :help (format "%s Key: menu." help)))

(defun cube-menu--configure-menu ()
  "Return the dynamic Configure submenu."
  (list
   "Configure" :help "Change borg-cube settings and save them to custom-file."
   (list "Remote host"
         (cube-menu--radio-item "This machine" #'cube-menu-use-local-machine
                                'cube-remote-host nil
                                "Run cube locally on this machine.")
         (vector "Set remote host..." #'cube-menu-set-remote-host
                 :keys "menu"
                 :help "Set cube-remote-host for remote backend calls. Key: menu."))
   (list "Terminal backend"
         (cube-menu--radio-item "Auto" (lambda () (interactive)
                                          (cube-menu-set-terminal-backend 'auto))
                                'cube-terminal-backend 'auto
                                "Prefer eat, falling back to vterm.")
         (cube-menu--radio-item "eat" (lambda () (interactive)
                                         (cube-menu-set-terminal-backend 'eat))
                                'cube-terminal-backend 'eat
                                "Use the eat terminal backend.")
         (cube-menu--radio-item "vterm" (lambda () (interactive)
                                           (cube-menu-set-terminal-backend 'vterm))
                                'cube-terminal-backend 'vterm
                                "Use the vterm terminal backend."))
   (cons "Dashboard sections"
         (mapcar
          (lambda (section)
            (cube-menu--toggle-item
             (capitalize (symbol-name section))
             (lambda () (interactive) (cube-menu-set-dashboard-section section))
             (list 'memq (list 'quote section) 'cube-dashboard-sections)
             (format "Show or hide the %s dashboard section." section)))
          '(goals work pipelines agents attention fleet projects ready students papers repos budget)))
   (cube-menu--toggle-item
    "Auto refresh dashboard"
    (lambda () (interactive)
      (cube-menu-set-auto-refresh (not cube-dashboard-auto-refresh)))
    'cube-dashboard-auto-refresh
    "Refresh the dashboard when the attention cache changes.")
   (vector "Refresh interval..." #'cube-menu-set-refresh-interval
           :keys "menu"
           :help "Set the seconds between attention polls, or disable polling. Key: menu.")
   (cons "Notification method"
         (mapcar
          (lambda (method)
            (let ((label (if (null method) "Silent" (capitalize (symbol-name method)))))
              (cube-menu--radio-item
               label (lambda () (interactive) (cube-menu-set-notify-method method))
               'cube-notify-method method
               (format "Use %s for desktop notifications."
                       (if method (symbol-name method) "no notifications")))))
          '(auto notify-send message nil)))
   (cons "Claude TUI mode"
         (mapcar
          (lambda (mode)
            (cube-menu--radio-item
             (capitalize (symbol-name mode))
             (lambda () (interactive) (cube-menu-set-claude-tui mode))
             'cube-claude-tui mode
             (format "Use Claude TUI mode %s." (symbol-name mode))))
          '(inherit inline fullscreen)))
   (vector "Attention count..." #'cube-menu-set-attention-count
           :keys "menu"
           :help "Set how many attention items the header shows. Key: menu.")
   (cube-menu--toggle-item
    "Kill switch active"
    #'cube-kill-switch-toggle
    'cube-kill-switch-active
    "Toggle the backend kill switch; confirmation is always required.")
   (vector "Kill switch on" #'cube-kill-switch-on
           :keys "menu"
           :help "Enable the backend kill switch after confirmation. Key: menu.")
   (vector "Kill switch off" #'cube-kill-switch-off
           :keys "menu"
           :help "Disable the backend kill switch after confirmation. Key: menu.")
   "---"
   (vector "Save these settings" #'cube-menu-save-settings
           :keys "menu"
           :help "Save settings changed through this menu to custom-file. Key: menu.")
   (vector "All settings..." #'cube-menu-all-settings
           :keys "menu"
           :help "Open the complete borg-cube Customize group. Key: menu.")))

;;;; Help and control commands

(defun cube-describe-keys ()
  "Describe the global cockpit keymap."
  (interactive)
  (describe-keymap 'cube-command-map))

(defun cube-open-readme ()
  "Open the cockpit README."
  (interactive)
  (find-file (cube-host-file-name "emacs/README.org")))

(defun cube-open-interface ()
  "Open the cockpit/backend JSON contract."
  (interactive)
  (find-file (cube-host-file-name "emacs/INTERFACE.md")))

(defun cube-about ()
  "Show the version reported by the cube backend."
  (interactive)
  (cube--call-text-async
   (list cube-program "--version")
   (lambda (text)
     (message "cube: %s" (string-trim text)))
   (lambda (code err) (message "cube: version failed (%s): %s" code err))))

(defun cube-kill-switch-on ()
  "Enable the backend kill switch after confirmation."
  (interactive)
  (when (y-or-n-p "Enable the cube kill switch? ")
    (cube--call-json-async
     '("kill" "on")
     (lambda (_json) (setq cube-kill-switch-active t)
       (message "cube: kill switch enabled"))
     (lambda (code err) (message "cube: kill switch failed (%s): %s" code err)))))

(defun cube-kill-switch-off ()
  "Disable the backend kill switch after confirmation."
  (interactive)
  (when (y-or-n-p "Disable the cube kill switch? ")
    (cube--call-json-async
     '("kill" "off")
     (lambda (_json) (setq cube-kill-switch-active nil)
       (message "cube: kill switch disabled"))
     (lambda (code err) (message "cube: kill switch failed (%s): %s" code err)))))

(defun cube-kill-switch-toggle ()
  "Toggle the backend kill switch after confirmation."
  (interactive)
  (if cube-kill-switch-active (cube-kill-switch-off) (cube-kill-switch-on)))

;;;; Mode menus and context menus

(defun cube-menu--mode-entries (mode)
  "Return table entries for MODE."
  (seq-filter (lambda (entry) (eq (plist-get entry :mode) mode)) cube-command-table))

(defun cube-mode-help ()
  "Show the actions and bindings of the current cockpit mode."
  (interactive)
  (let* ((mode (if (and (boundp 'cube-session-mode) cube-session-mode)
                   'cube-session-mode major-mode))
         (entries (cube-menu--mode-entries mode))
         (buffer (get-buffer-create (format "*cube help: %s*" mode))))
    (with-current-buffer buffer
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (format "Cube actions in %s\n\n" mode))
        (dolist (entry entries)
          (insert (format "%-8s %-28s %s\n"
                          (plist-get entry :key)
                          (plist-get entry :label)
                          (plist-get entry :help))))
        (goto-char (point-min)))
      (special-mode)
      (pop-to-buffer (current-buffer)))))

(defun cube-menu--mode-menu (title mode)
  "Return a menu TITLE for MODE's actions."
  (cons title
        (cons :help
              (cons (format "Actions available in the %s buffer." title)
                    (mapcar (lambda (entry) (cube-menu--item entry))
                            (cube-menu--mode-entries mode))))))

(defconst cube-key-legend-groups
  '(("Open" . "\\`cube-[a-z-]*\\(visit\\|show\\|open\\|dossier\\|queue\\|list\\|plan\\)")
    ("Agents" . "\\`cube-\\(agent\\|ask-coordinator\\)")
    ("Navigate" . "\\`\\(quit-window\\|cube-cockpit-restore\\|cube-[a-z-]*re\\(fresh\\|vert\\)\\)"))
  "Group title to command-name regexp for the per-mode key transient.
Anything that matches none of these is an action.")

(defun cube-key-legend-group (command)
  "Return the transient group title for COMMAND."
  (or (car (seq-find (lambda (pair)
                       (string-match-p (cdr pair) (symbol-name command)))
                     cube-key-legend-groups))
      "Act"))

(defun cube-key-legend--transient-layout (mode)
  "Return transient groups for MODE, built from its key legend alist."
  (let ((map (symbol-value (intern (format "%s-map" mode))))
        (buckets nil))
    (dolist (pair (cube-key-legend-alist mode))
      (when-let* ((command (lookup-key map (kbd (car pair))))
                  ((commandp command)))
        (let ((group (cube-key-legend-group command)))
          (setf (alist-get group buckets nil nil #'equal)
                (append (alist-get group buckets nil nil #'equal)
                        (list (list (car pair) (cdr pair) command)))))))
    (seq-keep (lambda (title)
                (when-let* ((rows (alist-get title buckets nil nil #'equal)))
                  (vconcat (list title) rows)))
              '("Open" "Act" "Agents" "Navigate"))))

(defun cube-key-legend-transient-symbol (mode)
  "Return the name of MODE's all-keys transient."
  (intern (format "%s-keys" mode)))

(defun cube-key-legend-define-transient (mode)
  "Define MODE's all-keys transient from its key legend alist."
  (when-let* ((layout (cube-key-legend--transient-layout mode)))
    (eval `(transient-define-prefix ,(cube-key-legend-transient-symbol mode) ()
             ,(format "All keys of %s." mode)
             ,@layout))
    (cube-key-legend-transient-symbol mode)))

(defun cube-mode-keys ()
  "Show every key of this cockpit buffer, grouped, as a transient."
  (interactive)
  (let ((prefix (cube-key-legend-transient-symbol major-mode)))
    (if (fboundp prefix)
        (transient-setup prefix)
      (cube-mode-help))))

(defun cube-menu-install-mode-menu (mode map title)
  "Install the TITLE menu and `?' key binding on MODE MAP."
  (define-key map (kbd "?") #'cube-mode-keys)
  (easy-menu-do-define
   (intern (format "cube-%s-menu" mode)) map
   (format "Menu for %s." title)
   (cube-menu--mode-menu title mode)))

(defun cube-menu--context-items (type)
  "Return a context menu command alist for dashboard item TYPE."
  (mapcar
   (lambda (entry)
     (cons (format "%s [%s]" (plist-get entry :label) (plist-get entry :key))
           (plist-get entry :command)))
   (seq-filter (lambda (entry)
                 (and (plist-get entry :context)
                      (memq type (plist-get entry :item-types))))
               cube-command-table)))

(defun cube-menu--global-menu ()
  "Return the top-level Cube menu definition."
  (list
   "Cube" :help "Learn and run borg-cube cockpit commands."
   (cube-menu--group "Dashboard" 'dashboard cube-prefix-key)
   (append (list "Sessions" :help "Switch to a live session or start one."
                 :filter #'cube-menu--sessions-filter)
           (mapcar (lambda (entry) (cube-menu--item entry cube-prefix-key))
                   (cube-menu--entries-for-group 'sessions)))
   (append (list "Work")
           (mapcar (lambda (entry) (cube-menu--item entry cube-prefix-key))
                   (cube-menu--entries-for-group 'work)))
   (append (list "Goals" :help "Open active cached goals or create one."
                 :filter #'cube-menu--goals-filter)
           (mapcar (lambda (entry) (cube-menu--item entry cube-prefix-key))
                   (cube-menu--menu-entries-for-group 'goals)))
   (cube-menu--group "Pipelines" 'pipelines cube-prefix-key)
   (append (list "Agents" :help "Talk to cached standing agents or manage one."
                 :filter #'cube-menu--agents-filter)
           (mapcar (lambda (entry) (cube-menu--item entry cube-prefix-key))
                   (seq-remove
                    (lambda (entry) (eq (plist-get entry :command) 'cube-agent-talk))
                    (cube-menu--menu-entries-for-group 'agents))))
   (append (list "People")
           (mapcar (lambda (entry) (cube-menu--item entry cube-prefix-key))
                   (cube-menu--entries-for-group 'people)))
   (append (list "Projects" :help "Open cached projects or the project list."
                 :filter #'cube-menu--projects-filter)
           (mapcar (lambda (entry) (cube-menu--item entry cube-prefix-key))
                   (cube-menu--entries-for-group 'projects)))
   (append (list "Review")
           (mapcar (lambda (entry) (cube-menu--item entry cube-prefix-key))
                   (cube-menu--entries-for-group 'review)))
   (append (list "Control" :filter #'cube-menu--control-filter)
           (mapcar (lambda (entry) (cube-menu--item entry cube-prefix-key))
                   (cube-menu--menu-entries-for-group 'control)))
   (cube-menu--configure-menu)
   (list "Help" :help "Read the manual, contract, keymap and diagnostics."
         (vector "Describe keys" #'cube-describe-keys
                 :keys "menu"
                 :help "Describe every C-c b cockpit binding. Key: menu.")
         (vector "Cube manual" #'cube-open-readme
                 :keys "menu"
                 :help "Open emacs/README.org, the cockpit manual. Key: menu.")
         (vector "JSON contract" #'cube-open-interface
                 :keys "menu"
                 :help "Open emacs/INTERFACE.md, the backend contract. Key: menu.")
         (vector "Doctor report" #'cube-doctor
                 :keys "menu"
                 :help "Run cube doctor and show its report. Key: menu.")
         (vector "About" #'cube-about
                 :keys "menu"
                 :help "Show the cube backend version. Key: menu."))
   "---"
   (cube-menu--item (car (cube-menu--entries-for-group 'dashboard)) cube-prefix-key)
   (cube-menu--item (cadr (cube-menu--entries-for-group 'dashboard)) cube-prefix-key)
   (cube-menu--item (seq-find (lambda (entry) (eq (plist-get entry :command) 'cube-goal-new))
                              (cube-menu--entries-for-group 'goals)) cube-prefix-key)))

(easy-menu-define cube-menu-bar cube-mode-map
  "The top-level Cube menu for the global cockpit mode."
  (cube-menu--global-menu))

(defun cube-menu--transient-layout ()
  "Return transient groups generated from global command entries."
  (mapcar
   (lambda (group)
     (vconcat
      (list (capitalize (symbol-name group)))
      (mapcar (lambda (entry)
                (list (plist-get entry :key)
                      (plist-get entry :label)
                      (plist-get entry :command)))
              (cube-menu--entries-for-group group))))
   '(dashboard sessions work goals pipelines agents people projects review control)))

;; `transient-define-prefix' wants literal groups.  Evaluate its generated
;; definition once, using the same table that built the keymap and menu.
(eval `(transient-define-prefix cube-menu ()
         "Cockpit command menu."
         ,@(cube-menu--transient-layout)))

(dolist (spec '((cube-dashboard-mode cube-dashboard-mode-map "Dashboard")
               (cube-project-mode cube-project-mode-map "Project")
               (cube-roster-mode cube-roster-mode-map "Roster")
               (cube-people-mode cube-people-mode-map "People")
               (cube-goal-mode cube-goal-mode-map "Goal")
               (cube-pipeline-mode cube-pipeline-mode-map "Pipeline")
               (cube-agent-mode cube-agent-mode-map "Agent")
               (cube-review-mode cube-review-mode-map "Review")
               (cube-decisions-mode cube-decisions-mode-map "Decisions")
               (cube-beads-list-mode cube-beads-list-mode-map "Ready beads")
               (cube-fleet-mode cube-fleet-mode-map "Fleet")
               (cube-session-mode cube-session-mode-map "Session")))
  (when (boundp (nth 1 spec))
    (cube-menu-install-mode-menu (nth 0 spec) (symbol-value (nth 1 spec))
                                 (nth 2 spec))))

(dolist (mode cube-key-legend-modes)
  (cube-key-legend-define-transient mode)
  (when-let* ((map (intern-soft (format "%s-map" mode)))
              ((boundp map)))
    (define-key (symbol-value map) (kbd "?") #'cube-mode-keys)))

(provide 'cube-menu)
;;; cube-menu.el ends here
