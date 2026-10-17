# looop

Personal agent scheduler and Paperclip customization. One maintained repository for scheduling, adapters, default roles and skills.

- `bin/`: controller, standalone state tools and Paperclip integration.
- `skills/project-adapter/`: project onboarding skill; assets link to canonical code.
- `default-roles/`: concise fallback roles; project roles take precedence.
- `runtime/`: pinned Paperclip npm manifest and lockfile.
- `retention.json`: bounded diagnostic retention.
- `tests/`: Linux verification.

Each project owns `.agent/local/runtime/data/project-state/state.sqlite` and `current.json`. Paperclip and independent conversations use this same state. Controller `locations.json` stores local routing only. `.agent/project.json`, `.agent/tools/` and a short AGENTS entry provide the portable project interface. Historical HANDOFF is reference, not current state.

Independent project: `python3 .agent/tools/project-session.py context --repo .`. Use start/progress/finish to update current work; start must be accepted before assuming scheduler exclusivity. No periodic handoff or conversation transcript is required.

Install from a clone on Linux: `python3 bin/setup.py` (Node24+, Python3, Git). Reconnect local credentials and project paths; these are intentionally excluded from Git. GitHub preserves the scheduler code, not secrets or live business state. To move active work, transfer each project's ignored state directory securely and relink it; do not run two schedulers against divergent copies.

Existing installation: `/home/agentdev/projects/looop`. Legacy compatibility paths have been removed. Paperclip remains at its existing Tailscale address. The owner landing page is `/looop`, an authenticated project-loop console. `/?paperclip=1` opens the original Paperclip UI. The version-checked `bin/install-ui.py` mounts source-managed UI routes after Paperclip authentication; setup reapplies it after dependency installation. It does not edit minified UI bundles. Opening the console never resumes planning. Owner actions use same-origin JSON, project revision checks and the same project-owned state as independent conversations.

Retention: log/trace tails ≤2MiB each; 500 recent acknowledged project events plus up to5000 pending events; latest20 self-reported completions; terminal current-state summaries retained as needed. Completed diagnostic workspaces compact after14 days,20 runs or1GiB. Active tasks, unresolved decisions and unsynced events are protected. Current-state mutation never requires replaying full logs. Legacy pilot snapshots are not execution truth and will be separately inventoried.

Run `python3 -m unittest discover -s tests` and `node tests/console-http.mjs` (after runtime setup). `docs/history/` is migration reference, not required reading or the current operating contract.

Console operations:
- **Execution settings** default to unlimited daily autonomous proposals. Each project can set a positive daily count or clear it for unlimited; `loop_limits` in project-owned state is authoritative. Custom daily limits reset on UTC dates and exclude confirmed requirements. Settings do not change loop mode, scope or review gates.
- **Once / continuous / pause** update `loop_control` in project-owned state. Once claims at most one PM attempt and waits through delivery/mainline verification before stopping; no-work also stops. Pause drains started work and prevents new selection. The timer launches configured lanes in separate tmux sessions. Legacy `enabled` is only the fallback before an explicit state switch; CLI and UI then share the same state. No total-duration kill is imposed.
- **Product input** stores confirmed requirements or decisions; it never resumes a paused loop or expands execution authority. Requirements enter PM priority selection; decisions constrain planning. Independent conversations read the same state.
- **Attention** resolves existing change requests (keep the original scope or follow up separately), returns deferred requirements to PM, and shows bounded task evidence. Explicit retry uses existing worker/lock/baseline/publication checks, retains evidence and reruns gates. Unknown publication/PM effects are not blindly replayed; provider auth/credit issues still need verification.
- **Onboarding** previews arbitrary project roles, mapped workflow, checks, lockfiles and CLI availability without executing project scripts. Explicit connection preserves existing rules and creates a context-only adapter when missing, standalone state tools, a short AGENTS entry and an ignored project-owned state directory. It adds an observation project without agents, execution policy, credentials, installs, commits or pushes. Linked worktrees remain preview-only. Complex/conflicting mappings and existing state/tool mismatches must be resolved in the project conversation using the adapter skill. A version fingerprint prevents using stale previews. Ambiguous board creation results are reconciled by marker rather than reposted.

Keep company/agent configuration in advanced Paperclip views. Dependency preview is static: a detected CLI does not prove services/system libraries are operational. Activation of a new automatic project still requires a reviewed project-specific execution policy and verified environment.
