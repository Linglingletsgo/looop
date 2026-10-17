---
name: project-adapter
description: Adapt an existing project for shared agent state, standalone project conversations and optional Paperclip scheduling. Preserve its rules and roles; do not enable autonomous development merely by adapting it.
---

# Project adaptation

Inspect the project's native AGENTS instructions, role/workflow files, HANDOFF/backlog, environment/dependencies and Git/worktree status. Preserve existing work. Reuse project roles; defaults fill missing responsibilities. Do not force frontend, test-only or Acceptance workflows onto unrelated projects.

Create `.agent/project.json` using the existing adapter schema: version=1, role_discovery, roles, rules, workflow, allowed_paths and checks. Map existing rules rather than duplicating them. Use build → review by default; add explicit project-required roles only. Keep native AGENTS effective. Runtime tools/checks must actually be supported; report missing system requirements. A manifest is not permission to execute or publish.

Copy `assets/project-session.py` `assets/project_state.py` and `assets/product_goals.py` into `.agent/tools/`. These files are self-contained Python standard-library code. Add `.agent/local/` to the project's ignore rules without replacing existing entries. It holds machine bindings, cached state and pending events; do not commit it or credentials. Keep portable rules/tools and concise durable product decisions available with the project. Current state is primary; event history is bounded by the scheduler retention policy. Do not append logs, transcripts or repeated handoff documents to project state. Migrate existing HANDOFF conclusions once as context; do not invent runtime completion from historical prose.

Initialize state:

- Standalone: `python3 .agent/tools/project-session.py init --repo .`
- Existing registered scheduler project: same command plus `--runtime /absolute/controller/root --lane PROJECT_ID`.

For a previously standalone project, `connect --repo . --runtime /absolute/controller/root --lane PROJECT_ID` imports its independent progress into the registered scheduler state, preserving local history. Each project owns its current-state database at .agent/local/runtime/data/project-state/state.sqlite. The scheduler stores only a routing entry in data/project-state/locations.json; both entrances must address the same project database. Do not create another authority for an already linked project. For a new scheduler project, use the existing profile/configuration procedure first; link only after its lane is registered and state initialized. Review role mappings, checks, repository and mandate; do not enable scheduling or publication without existing authorization. A configured project can inherit execution settings with `python3 bin/delivery-control.py configure LANE` from the looop checkout; this preserves existing policies and does not start a loop. Use project workflow/checks and explicit scope restrictions when present; otherwise task-specific paths and global workflow defaults apply. Declare `backlog_paths` for pending checklists, or put confirmed requirements in current state. Selection defaults to backlog_only; backlog_and_research additionally allows new requirements within existing direction. Do not infer pending tasks from historical prose or enable a context-only adapter without resolving its mapping.

Add a short, nonconflicting pointer to the project's existing AGENTS file (create only if absent):

> Read `python3 .agent/tools/project-session.py context --repo .` at conversation start and before work/decisions. Follow `.agent/project.json` and native project rules. For independent development, record start/progress/finish with a stable work ID and concise evidence. Start must be accepted before assuming scheduler exclusivity. Cached/offline progress does not reserve execution. Never edit state directly or treat self-reported completion as reviewed/merged.

Independent progress commands use `start|progress|finish|cancel --repo . --id WORK_ID --summary TEXT`. `context` reads current/cached state; `cached` reads without connecting; `sync` retries pending records. Summaries include actual changed scope and verification, not transcripts or secrets. On version conflict, inspect current state and pending records; do not silently rewrite revision numbers or drop events. Active scheduler tasks must drain before independent start can acquire the project. Stale external sessions are not released merely because time elapsed.

Validate in a disposable copy first: manifest/rule discovery, standalone context/progress, linked state and pending-event behavior. Do not use a real product change to test integration. Report supported capabilities, missing integrations and exact invocation. Git commits/pushes are separate actions, not implied by adaptation.


## Product goals and research

Keep the project's existing PM responsibility and approval boundaries. Discover relevant PM research skills in the project; do not copy them globally. Optionally declare canonical paths in `.agent/project.json` as `"research":{"skill_paths":[".agents/skills/example/SKILL.md"]}`; absent an explicit list, looop scans the project's `.agents`, `.claude` and `.codex` skill roots. Include any required research manifest/reference rules in the adapter rule mapping. Do not replace a research-only PM with a role that approves or dispatches its own proposals.

The project-owned current state stores `product_goal`: user-facing title, user benefit, success criteria, remaining outcomes, current progress and verified slice count. Native conversations and Paperclip read this same bounded state. Do not create an ever-growing progress diary or mark a whole requirement complete when one PR merges. Existing active tasks keep their original contract; new goals require a research brief with source evidence and counterevidence before binding. Project-specific discovery/approval outputs take precedence; an incompatible workflow stays observation-only until explicitly mapped.

When no project method covers the question, looop supplies reviewed personal-use defaults from `pm-skills/manifest.json`. Prefer project methods; record the specific gap before loading defaults. Default methods are not project roles and never override project authority. For standalone conversations, read the relevant method and investigation protocol from the looop checkout, apply it to existing project state, and retain original skill licenses when exporting. `research` holds the latest bounded research brief, including an insufficient-evidence result; do not append a research diary.
