# Agent Control

Maintain Paperclip customization, scheduling, project adapters and skills in this repository. `bin/` is the canonical implementation; skill assets and installed skill/legacy kit paths link to it. Project-local tools are exported standalone artifacts.

Project-owned current state is authoritative; code and executed checks are evidence. Keep logs/history bounded by retention.json. Preserve active work and unsynced events. Never use historical conversations or HANDOFF as fresh execution permission.

Run tests on Linux with `python3 -m unittest discover -s tests`. Do not commit data/, logs/, caches, credentials, machine bindings or dependencies. Keep Paperclip in place. GTP autonomy remains paused, WOS automation disabled, DS1 human-only.
