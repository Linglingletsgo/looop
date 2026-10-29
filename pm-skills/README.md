# PM methods for looop

Distributable skill pack. The repository is MIT; `research-core`, `opportunities`, `backlog-prioritization`, `requirement-brief` and `assumption-testing` are MIT. The Dean Peters adaptations (`investigation`, `competitive-research`) are CC BY-NC-SA 4.0 and live in the opt-in `noncommercial/` pack; see [noncommercial/README.md](noncommercial/README.md).

Adapted 2026-10-17; changes remove fixed counts, human-only menus, default calendars, automatic audit chains and unbounded report creation. Methods return caller-owned state and never extend project authority.

Project-owned skills take precedence. The loader includes relevant default methods only for a stated project-method gap; `research-core` is included with default methods (or `investigation` when the noncommercial pack is enabled). A plan that explicitly selects exactly one base method keeps that choice: the loader never inserts or swaps the other base and never loads both. Exact runtime bytes and pinned upstream versions are in manifest.json. Original reviewed sources and original LICENSE files are retained in upstream/ for audit, not injected wholesale into each run. Consult original sources for background; do not inherit their additional workflow or authority.

Manifest `dependencies` entries carry no runtime meaning; `["looop:base"]` is a placeholder for "the configured base method" used by the MIT methods, while `competitive-research` keeps its concrete `looop:investigation`.

## Attribution and licenses

- looop `research-core`: original MIT method, no upstream.
- Dean Peters, Product-Manager-Skills: investigation and competitive-research adaptations, CC BY-NC-SA 4.0, in the opt-in noncommercial pack. Original copyright and full license are retained in noncommercial/README.md and upstream/deanpeters/LICENSE. Adaptations retain CC BY-NC-SA 4.0; no upstream endorsement is implied.
- Paweł Huryn / phuryn, pm-skills: opportunities, backlog-prioritization and requirement-brief adaptations, MIT; see upstream/phuryn/LICENSE.
- Uxcel, product-skills: assumption-testing adaptation, MIT; see upstream/Uxcel-Lab/LICENSE.

Mixed licenses: MIT for the repository and the default pack; the CC BY-NC-SA material is opt-in and is not relicensed as MIT. Review license conditions before redistributing or changing usage.

## Enabling the noncommercial pack

Set `data/local-settings.json` at the runtime root to `{"pm_skills": {"noncommercial": true}}`. Missing file or key means disabled; the loader and the Magpie export both respect this setting.

Re-run `python3 bin/sync-magpie-subagents.py` after toggling. With the pack disabled the sync exports and installs only the MIT methods, removes the two noncommercial entries from the Magpie library when it owns them, drops them from the `product-manager` skill bindings (other bindings are kept), deletes their export folders, and prints the `removed`, `pruned` and `warnings` lists naming anything left for manual removal.

## Standalone use

From a project conversation, first read the project's rules and current state. If project methods do not cover the question, explicitly read the relevant pm-skills/<method>/SKILL.md and research-core/SKILL.md from your looop checkout. Apply the method to the project's existing state mechanism. No external scheduler is required; do not copy this pack into business projects or replace their roles.
