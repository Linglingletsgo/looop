# Cutover: Paperclip tracker → local jobs

Status: executed on the live install (steps 1–9). Kept as the procedure for other installs; every step needs explicit operator approval at the time it is run. Nothing here is permission by itself.

## Preconditions

- `refactor/standalone` merged to `main` after review; full test suite passes on the live checkout.
- No delivery in flight: no `data/deliveries/*/state.json` with an active state and a live owner; no `looop-loop-*` / `looop-delivery-*` tmux session running; the latest migration dry run shows no `todo`/`in_progress` delivery (2026-10-23: 37 done, 1 blocked, none active).
- GTP loop stays paused (`loop_control.mode` paused). The cutover does not resume it.

## Steps

1. **Stop the timers.** `systemctl --user stop paperclip-autonomy.timer paperclip-pr-sync.timer`, then wait for any running `paperclip-autonomy.service` / `paperclip-pr-sync.service` to finish (`systemctl --user is-active`).
2. **Pause the Paperclip delivery agents** (`<lane>:delivery` in `data/control.json` `agents`) in the Paperclip UI, so the heartbeat cannot start `delivery-worker.py` while the tracker changes. (In local mode the worker would read local jobs; leases prevent double execution, but no second launcher is wanted.)
3. **Back up runtime state** (not the Paperclip DB): `tar -C data -cf data/backups/cutover-<UTC>.tar control.json local-settings.json delivery-bindings deliveries autonomy delivery-policies autonomy-policies loop-dashboard project-state operator-requests` (only existing paths).
4. **Migration dry run with board overlay:** `python3 scripts/migrate-jobs.py --board`. Check `errors`, `conflicts`, `board_error`, `orphans` and every row whose `board.result` is `board_differs`. A `board_error` for a 401 means signing in to Paperclip first.
5. **Apply:** `python3 scripts/migrate-jobs.py --apply --board`. Exit 0 and `counts.created` equal to the dry run's `planned` (minus skipped `board_error`s) is expected. A dry run never reads `data/jobs.sqlite` and always reports `planned`; verify instead by re-running `--apply --board` (every row `existing`, nothing created) or by comparing `data/jobs.sqlite` with the dry-run rows.
6. **Switch settings** in `data/local-settings.json` (keep `board_url`):
   ```json
   {"board_url": "...", "tracker": "local", "pm_skills": {"noncommercial": true}}
   ```
   `pm_skills.noncommercial` keeps GTP's current PM base method (looop:investigation) and its saved receipts valid.
7. **Smoke checks (timers still stopped):**
   - `python3 bin/console.py` returns JSON with `"tracker": "local"`.
   - `python3 bin/maintenance.py` exits 0.
   - `python3 bin/launch_loops.py` starts no session (GTP paused, no pending delivery).
8. **Start the timers again:** `systemctl --user start paperclip-autonomy.timer paperclip-pr-sync.timer` (names kept for now; renaming them is part of P1e). Watch two cycles in `journalctl --user -u paperclip-pr-sync.service`.
9. **Console:** `python3 bin/console-auth.py set-password`, then start `bin/console-server.py` (systemd user unit in docs/standalone-architecture.md).

Paperclip itself (`paperclip-board.service`) keeps running until P1e, as a read-only history.

## Rollback

Possible as long as no job was created or changed in local mode after step 6:

1. Stop the timers.
2. Remove `"tracker"` from `data/local-settings.json` (back to Paperclip). `data/jobs.sqlite` is then unused; leave it or move it aside.
3. Resume the Paperclip delivery agents and start the timers.

After local-mode jobs exist, Paperclip no longer reflects them; rolling back then needs a reverse sync, which is not implemented. Decide before step 8 whether to keep going.

In local mode `state-sync.py` acknowledges the project-state outbox without mirroring to Paperclip, so after switching back the board stays stale until the next state change, which then mirrors the full current snapshot (existing issues are matched by marker, so no duplicates).

## After cutover (P1e)

Delete Paperclip-only modules, the Paperclip mirror in `state-sync.py`, the agent provisioning in `delivery-control.py`, `ui/server.mjs` + `bin/install-ui.py`; rename the timers; stop `paperclip-board.service` with operator approval.
