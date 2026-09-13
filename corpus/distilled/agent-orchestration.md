---
topic: agent-orchestration
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Agent orchestration

Sources
- anthropic-building-effective-agents (proprietary; summary only)
- anthropic-multi-agent-research (proprietary; summary only)
- anthropic-writing-tools (proprietary; summary only)
- anthropic-context-engineering (proprietary; summary only)
- agentskills-spec (proprietary; short excerpts of field names only)

## What the evidence says

### Workflows versus agents

- A workflow is a system in which language-model calls and tools follow code paths fixed in advance; an agent is a system in which the model decides its own steps and tool use at run time. Both count as agentic systems, but the architectural distinction matters for predictability and cost [anthropic-building-effective-agents].
- Workflows suit well-defined tasks where predictability and consistency matter. Agents suit open-ended problems where the number of steps cannot be predicted and a fixed path cannot be hardcoded. For many applications a single well-tuned model call with retrieval and examples is enough [anthropic-building-effective-agents].
- Agentic systems trade latency and cost for task performance. The recommendation is to find the simplest solution that works and to add complexity only when it measurably improves outcomes [anthropic-building-effective-agents].
- Frameworks simplify boilerplate but add abstraction that hides prompts and responses and makes debugging harder. Start with direct API calls; if a framework is used, understand the code beneath it [anthropic-building-effective-agents].
- Five composable workflow patterns are described. Prompt chaining runs fixed steps in sequence with optional programmatic gates between them. Routing classifies an input and sends it to a specialized downstream prompt. Parallelization either sections a task into independent pieces or votes by running the same task several times. Orchestrator-workers has a central model decompose a task dynamically, delegate to workers, and synthesize. Evaluator-optimizer loops a generator against a critic [anthropic-building-effective-agents].
- Orchestrator-workers differs from parallelization in flexibility: the subtasks are not fixed in advance but chosen by the orchestrator for the specific input. It fits multi-file code changes and multi-source information gathering [anthropic-building-effective-agents].
- Routing can also assign easy or common inputs to smaller, cheaper models and hard or unusual inputs to more capable ones, which is a way to match model tier to task difficulty [anthropic-building-effective-agents].
- Evaluator-optimizer pays off only when there are clear evaluation criteria and iteration brings measurable gains; the test is whether a human's articulated feedback would improve the output and whether a model can supply that feedback [anthropic-building-effective-agents].
- Fully autonomous agents need ground truth from the environment at each step (tool results, test output), checkpoints for human feedback, and stopping conditions such as a maximum number of iterations. Autonomy raises cost and lets errors compound, so sandboxed testing and guardrails are needed [anthropic-building-effective-agents].
- Three design principles are offered: keep the design simple, make planning steps visible, and invest in the agent-computer interface through tool documentation and testing [anthropic-building-effective-agents].
- Coding agents are singled out as a good fit because tests verify solutions, the problem space is structured, and output quality can be measured; human review is still needed for alignment with broader system requirements [anthropic-building-effective-agents].

### The orchestrator-worker pattern in practice

- Anthropic's research system uses a lead agent that analyzes a query, forms a strategy, spawns subagents to search in parallel, synthesizes their returns, and decides whether more work is needed; a separate citation pass runs at the end [anthropic-multi-agent-research].
- Subagents act as compressors: each explores in its own context window and returns only the most important findings to the lead. Separate tools, prompts, and trajectories per subagent reduce path dependence [anthropic-multi-agent-research].
- Multi-agent systems win mainly by spending more tokens on the problem. In the reported analysis, token usage explained most of the performance variance on a browsing benchmark, with tool-call count and model choice next. The multi-agent setup beat a single-agent baseline by about 90 percent on an internal research evaluation, and excelled on breadth-first queries with many independent directions [anthropic-multi-agent-research].
- The cost is high: agents used about four times the tokens of a chat, and multi-agent systems about fifteen times. Tasks with many dependencies or that need all agents to share one context are a poor fit; most coding tasks have fewer truly parallel pieces than research does [anthropic-multi-agent-research].
- Early failure modes were spawning far too many subagents for simple queries, searching endlessly for sources that did not exist, and agents distracting each other with excessive updates [anthropic-multi-agent-research].
- Delegation must be taught. Each subagent needs an objective, an output format, guidance on tools and sources, and clear task boundaries. One-line briefs that only name a topic caused subagents to misread the task or run the same searches as their peers, leaving gaps and duplicating work [anthropic-multi-agent-research].
- Effort must be scaled to task complexity by explicit rules in the prompt, because agents judge effort poorly on their own. The reported heuristics were one agent with a handful of tool calls for a fact lookup, two to four subagents for a comparison, and more than ten subagents with divided responsibilities for complex research [anthropic-multi-agent-research].
- Good prompts for these systems are frameworks for collaboration: division of labor, problem-solving approach, and effort budget, rather than rigid step lists. Small changes to the lead prompt changed subagent behavior in unpredictable ways [anthropic-multi-agent-research].
- Search strategy should start wide and narrow down: agents default to long, over-specific queries that return little, so prompts push them to open with short broad queries and then focus [anthropic-multi-agent-research].
- Visible extended thinking works as a controllable scratchpad: the lead uses it to choose tools, judge complexity, set the subagent count, and define each role; subagents use interleaved thinking after tool results to assess quality and find gaps [anthropic-multi-agent-research].
- The lead agent saves its plan to memory before spawning workers so the plan survives context truncation; subagents write large outputs to a filesystem and pass back lightweight references, which avoids loss of fidelity when results are relayed through the coordinator [anthropic-multi-agent-research].
- Parallelism at two levels (lead spawns several subagents at once; each subagent calls several tools at once) cut research time by up to 90 percent for complex queries [anthropic-multi-agent-research].
- Synchronous execution (the lead waits for a batch of subagents) simplifies coordination but blocks the whole system on the slowest worker and prevents mid-task steering [anthropic-multi-agent-research].

### Evaluation and observability

- Agents take different valid paths to the same goal, so evaluation must judge outcomes and the reasonableness of the process rather than adherence to a prescribed step list. For agents that mutate state, evaluate the end state, or discrete checkpoints where a state change should have occurred [anthropic-multi-agent-research].
- Start evaluating immediately with small samples (about twenty representative queries) because early effect sizes are large; do not wait for hundreds of cases [anthropic-multi-agent-research].
- A single model-as-judge call scoring a rubric (factual accuracy, citation accuracy, completeness, source quality, tool efficiency) with a pass/fail grade was more consistent than multiple specialized judges [anthropic-multi-agent-research].
- Human testing still catches what automation misses, such as a bias toward search-optimized content over authoritative but lower-ranked sources [anthropic-multi-agent-research].
- Full production tracing of decisions and interaction structure, not conversation contents, was needed to diagnose user reports that an agent had missed obvious information [anthropic-multi-agent-research].
- Agents are stateful and errors compound; the system needs resume-from-checkpoint, retry logic, and the ability to tell the agent a tool is failing so it can adapt [anthropic-multi-agent-research].
- Because agents may be mid-task whenever code is deployed, updates are rolled out gradually with old and new versions running side by side rather than switching every agent at once [anthropic-multi-agent-research].
- Tool evaluations should use realistic multi-step tasks paired with verifiable outcomes, avoid overly strict verifiers, and track runtime, tool-call counts, token consumption, and error rates alongside accuracy. Reading agents' reasoning and raw transcripts reveals confusion that summary metrics hide [anthropic-writing-tools].
- Agents can improve their own tools: given a failing tool and its transcripts, a model can diagnose the failure and rewrite the description. One such loop cut task completion time by about 40 percent for later agents [anthropic-multi-agent-research, anthropic-writing-tools].

### Tool design

- Tool definitions deserve the same prompt-engineering attention as the main prompt. Good definitions include example usage, edge cases, input format requirements, and clear boundaries from neighboring tools. Formats should be close to what the model has seen in natural text and free of overhead such as line counts or heavy escaping [anthropic-building-effective-agents].
- Change arguments so mistakes are harder to make; requiring absolute file paths removed a whole class of errors in a coding agent [anthropic-building-effective-agents].
- Build a few tools for high-impact workflows rather than wrapping every API endpoint. Prefer tools that search or consolidate (search_contacts, schedule_event) over tools that list everything and leave the filtering to the agent's context [anthropic-writing-tools].
- Namespace related tools under a common prefix by service and by resource so that agents can pick among many tools; prefix versus suffix placement measurably affects results and should be chosen by evaluation [anthropic-writing-tools].
- Return high-signal context: natural-language names over opaque identifiers, with an optional concise/detailed response format so the agent can ask for identifiers only when it needs them for a follow-up call [anthropic-writing-tools].
- Bound tool output with pagination, filtering, or truncation and sensible defaults; write truncation notices and error messages that tell the agent what to do next rather than returning raw codes [anthropic-writing-tools].
- Describe tools as you would for a new hire: make implicit context explicit, name parameters unambiguously (user_id rather than user), and enforce inputs with strict data models. Small description changes produced large benchmark gains [anthropic-writing-tools].
- If a human engineer cannot say which of two tools applies, the agent will not do better; bloated or overlapping tool sets are a common failure mode [anthropic-context-engineering].
- Bad tool descriptions send agents down wrong paths; each tool needs a distinct purpose, and agents benefit from explicit heuristics such as examining all tools first and preferring specialized tools over generic ones [anthropic-multi-agent-research].

### Context engineering

- Context is a finite resource with diminishing returns. As the token count grows, recall accuracy drops (context rot), so every token added spends part of a limited attention budget [anthropic-context-engineering].
- The goal is the smallest set of high-signal tokens that makes the desired behavior most likely. System prompts should sit at the right altitude: concrete enough to guide, not brittle if-else logic, and not vague guidance that assumes shared context. Organize prompts into labeled sections and start minimal, adding instructions only for observed failures [anthropic-context-engineering].
- Prefer a few diverse canonical examples over an exhaustive list of edge cases [anthropic-context-engineering].
- Just-in-time retrieval keeps lightweight references (paths, queries, links) in context and loads data through tools when needed; folder names, file names, and timestamps carry signal. A hybrid of some up-front context plus autonomous exploration fits many tasks [anthropic-context-engineering].
- For long-horizon work, three techniques address context limits: compaction (summarize and restart, keeping decisions and open issues while dropping stale tool output), structured note-taking (persist progress and plans outside the window and read them back), and sub-agent architectures (isolate detailed exploration in workers that return short distilled summaries) [anthropic-context-engineering].
- Compaction suits long back-and-forth; note-taking suits iterative work with milestones; multi-agent suits research where parallel exploration pays. Clearing old tool results is the safest, lightest compaction [anthropic-context-engineering].
- Workers may spend tens of thousands of tokens but return roughly one to two thousand, keeping the lead focused on synthesis [anthropic-context-engineering].

### Skill format and progressive disclosure

- A skill is a directory with a SKILL.md carrying YAML frontmatter (required `name` and `description`, optional `license`, `compatibility`, `metadata`, `allowed-tools`) followed by Markdown instructions; `scripts/`, `references/`, and `assets/` are the conventional optional directories [agentskills-spec].
- The `description` must say both what the skill does and when to use it, with keywords that help an agent match tasks; `name` must match the directory name [agentskills-spec].
- The body has no required format; the spec recommends step-by-step instructions, examples of inputs and outputs, and common edge cases, and advises splitting long bodies into referenced files because the whole SKILL.md is loaded on activation [agentskills-spec].
- Loading is progressive: name and description for every skill at startup (about 100 tokens each), the SKILL.md body only on activation (under 5000 tokens recommended, under 500 lines), and resource files only when needed. Reference files should stay focused and one level deep [agentskills-spec].

## Rules we adopt

1. Decompose a goal into beads only when the goal cannot be done in one well-scoped call; start with the simplest structure and add orchestration when a measured failure requires it. Enforced by Robert in delegation review (from [anthropic-building-effective-agents], [anthropic-context-engineering]).
2. Use a fixed workflow (chain, route, or section) when the subtasks are known in advance; use orchestrator-workers only when the subtasks depend on the input. Record which pattern a plan uses. Enforced by the delegation skill template (from [anthropic-building-effective-agents]).
3. One bead has exactly one owner role and at least one acceptance criterion that a script, test, or reviewer can check as pass or fail. Beads with no testable criterion are rejected by lint (from [anthropic-building-effective-agents], [anthropic-multi-agent-research]).
4. Every worker brief states the objective, the output format, the tools and sources the worker may use, and the task boundaries (what is out of scope and which neighboring beads own it). Lint fails a brief missing any field (from [anthropic-multi-agent-research]).
5. Set an explicit effort budget per bead (approximate tool calls or wall time) scaled to complexity: a lookup gets one worker and a few calls, a comparison a handful of workers, a broad survey many workers with disjoint scopes. The orchestrator records the budget in the bead (from [anthropic-multi-agent-research]).
6. Give a worker no more context than its task needs: a scoped brief plus paths or references to read on demand, never the orchestrator's full history. Workers return a condensed summary plus a path to any large artifact. Checked in review (from [anthropic-context-engineering], [anthropic-multi-agent-research]).
7. Run independent beads in parallel and declare dependencies explicitly; a bead whose input is another bead's output waits on that bead. The orchestrator saves its plan to a file before spawning workers (from [anthropic-multi-agent-research], [anthropic-building-effective-agents]).
8. Gate every bead with a review by a tier at least as capable as the worker, judging outcome against the acceptance criteria and reasonableness of process, not step-by-step conformance. Use evaluator-optimizer loops only where criteria are clear and iteration measurably helps (from [anthropic-building-effective-agents], [anthropic-multi-agent-research]).
9. Keep a small evaluation set (about twenty realistic goals with verifiable outcomes) for the delegation skill itself and rerun it after every prompt or template change; also collect a human spot check per release (from [anthropic-multi-agent-research], [anthropic-writing-tools]).
10. Log each bead's decisions, tool calls, tokens, and outcome so failures can be traced to a cause; never log conversation contents that contain personal data. Enforced by the orchestration harness (from [anthropic-multi-agent-research], [anthropic-writing-tools]).
11. Every tool exposed to workers has a distinct purpose, an unambiguous name and parameter names, a namespace prefix, bounded output with actionable truncation and error messages, and a description written for a new team member. Tool changes are evaluated with an agent before adoption (from [anthropic-writing-tools], [anthropic-building-effective-agents]).
12. Orchestrator and worker system prompts are minimal, sectioned, and at the right altitude; new instructions are added only in response to an observed failure, and canonical examples replace edge-case lists. Checked in review (from [anthropic-context-engineering]).
13. Long runs use compaction or structured notes: the orchestrator keeps a progress file with completed beads, open issues, and decisions, and reads it back after any context reset (from [anthropic-context-engineering], [anthropic-multi-agent-research]).
14. Skills follow progressive disclosure: trigger phrases in `description`, procedure in a SKILL.md under 500 lines, evidence in `references/`, templates in `assets/`; references stay one level deep. Enforced by skills_lint (from [agentskills-spec], [anthropic-context-engineering]).
15. Every autonomous run has a stopping condition (iteration cap or budget) and a human checkpoint before irreversible actions such as publishing, sending, or deleting (from [anthropic-building-effective-agents]).

## Where sources disagree

- How much to parallelize: [anthropic-multi-agent-research] reports large gains from many parallel subagents on breadth-first research, while [anthropic-building-effective-agents] and [anthropic-context-engineering] repeat that the simplest solution that works is best and that agentic complexity should be added only when measured. [anthropic-multi-agent-research] itself notes that coding tasks have few truly parallel pieces and that multi-agent runs cost about fifteen times a chat. We follow the conservative position: default to a single worker or a fixed chain, and open parallel beads only when the plan shows independent subtasks and the goal's value justifies the token cost.
- Judge structure: [anthropic-multi-agent-research] found one judge with a rubric more consistent than several specialized judges, while [anthropic-building-effective-agents] lists voting with several evaluator prompts as a valid parallelization pattern. We use one rubric-based reviewer per bead by default and reserve multi-reviewer voting for high-stakes gates such as release or publication.
- Retrieval up front versus just in time: [anthropic-context-engineering] describes both static pre-retrieval and just-in-time loading and settles on a hybrid. We adopt the hybrid: the brief names the files and sources a worker may read, and the worker loads them on demand.

## Not covered

- None of the sources address orchestrating a mix of human and agent workers, such as a bead owned by a student with an agent assistant; the ownership and review rules above are our extension.
- The sources give no guidance on how acceptance criteria should be written for research outputs that have no single correct answer beyond rubric-based judging; criteria design for scientific writing beads is left to the writing skills.
- Asynchronous orchestration (workers that steer each other or spawn workers mid-task) is described as future work in [anthropic-multi-agent-research]; the sources give no tested pattern, so we keep synchronous batches.
- Cost accounting and budgeting across a group's many concurrent projects is not discussed; token and time budgets per bead are our own rule of thumb pending measurement.
- Security of tool access for workers (least privilege, sandboxing beyond a general recommendation to test in a sandbox) is only mentioned in passing; the `allowed-tools` field in [agentskills-spec] is marked experimental and we do not rely on it.
- The sources are all from one vendor and describe that vendor's models and products; independent replication of the reported effect sizes is not available in this corpus.
- None of the sources say how to choose the reviewer tier relative to the worker tier; the rule that the reviewer is at least as strong as the worker is our own extension of the routing-by-difficulty idea.
