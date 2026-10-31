# looop

Local agent scheduler: PM planning, delivery worker, project adapters, skills and the owner console. `bin/` is the canonical implementation; skill assets and installed skill/legacy kit paths link to it. Project-local tools are exported standalone artifacts.

The local job table (`data/jobs.sqlite` via `bin/jobs.py`) is the only tracker; `data/local-settings.json` `tracker` may be absent or `local`. Project-owned current state is authoritative; code and executed checks are evidence. Keep logs/history bounded by retention.json. Preserve active work and unsynced events. Never use historical conversations or HANDOFF as fresh execution permission.

Run tests on Linux with `python3 -m unittest discover -s tests`. Do not commit data/, logs/, caches, credentials, machine bindings or dependencies. Do not change live systemd units from the repository; use `docs/cutover.md` with explicit operator approval. Loop modes follow explicit operator actions and current project state; do not infer activation from historical docs. WOS automation disabled, DS1 human-only.

Read `python3 .agent/tools/project-session.py context --repo .` at conversation start and before work/decisions. Follow `.agent/project.json` and native project rules. For independent development, record start/progress/finish with a stable work ID and concise evidence. Start must be accepted before assuming scheduler exclusivity. Cached/offline progress does not reserve execution. Submit structured role evidence with result --result-file when applicable; never edit shared state directly or treat self-reported completion as reviewed/merged. This adapter is standalone: looop is not registered as its own scheduler lane.
