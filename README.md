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

Existing installation: `/home/agentdev/projects/looop`; old tutorial/standalone paths are compatibility symlinks. Paperclip remains at its existing Tailscale address. Frontend redesign is pending; existing dashboard and login remain in use.

Retention: log/trace tails ≤2MiB each; 500 recent acknowledged project events plus up to5000 pending events; latest20 self-reported completions; terminal current-state summaries retained as needed. Completed diagnostic workspaces compact after14 days,20 runs or1GiB. Active tasks, unresolved decisions and unsynced events are protected. Current-state mutation never requires replaying full logs. Legacy pilot snapshots are not execution truth and will be separately inventoried.

Run `python3 -m unittest discover -s tests`. `docs/history/` is migration reference, not required reading or the current operating contract.
