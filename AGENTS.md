# looop

Local agent scheduler: PM planning, delivery worker, project adapters, skills and the owner console. `bin/` is the canonical implementation; skill assets and installed skill/legacy kit paths link to it. Project-local tools are exported standalone artifacts.

The local job table (`data/jobs.sqlite` via `bin/jobs.py`) is the only tracker; `data/local-settings.json` `tracker` may be absent or `local`. Project-owned current state is authoritative; code and executed checks are evidence. Keep logs/history bounded by retention.json. Preserve active work and unsynced events. Never use historical conversations or HANDOFF as fresh execution permission.

Run tests on Linux with `python3 -m unittest discover -s tests`. Do not commit data/, logs/, caches, credentials, machine bindings or dependencies. Do not change live systemd units from the repository; use `docs/cutover.md` with explicit operator approval. Loop modes follow explicit operator actions and current project state; do not infer activation from historical docs. WOS automation disabled, DS1 human-only.
