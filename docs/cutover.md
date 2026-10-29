# Cutover: Paperclip tracker → local jobs

Status: executed on the live install (steps 1–9). Kept as the procedure for other installs; every step needs explicit operator approval at the time it is run. Nothing here is permission by itself. P1e (below) removes Paperclip from the code; installs that still run Paperclip must finish steps 1–9 on tag `paperclip-last` before upgrading past P1e, because the `--board` migration overlay and the unit names only exist there.

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

Paperclip itself (`paperclip-board.service`) kept running until P1e, as a read-only history.

## Rollback

Possible as long as no job was created or changed in local mode after step 6:

1. Stop the timers.
2. Remove `"tracker"` from `data/local-settings.json` (back to Paperclip). `data/jobs.sqlite` is then unused; leave it or move it aside.
3. Resume the Paperclip delivery agents and start the timers.

After local-mode jobs exist, Paperclip no longer reflects them; rolling back then needs a reverse sync, which is not implemented. Decide before step 8 whether to keep going.

`state-sync.py` acknowledges the project-state outbox without mirroring, so after switching back the board stays stale; a reverse sync is not implemented.

## P1e upgrade

P1e deletes the Paperclip code, so an install cannot go back to the board tracker after it. Do all of this in one approved maintenance window, on the upgraded checkout (branch `refactor/p1e` or later), with the loops paused:

1. **Preconditions.** `data/local-settings.json` has `"tracker": "local"` (or no `tracker` key); `python3 bin/console.py` prints `"tracker": "local"`; the migration from steps 4–5 was run on `paperclip-last`; no delivery in flight and no `looop-loop-*` / `looop-delivery-*` tmux session. Every later step needs explicit operator approval at the time it is run.
2. **Stop the old timers:** `systemctl --user stop paperclip-autonomy.timer paperclip-pr-sync.timer`, then wait for any running `paperclip-autonomy.service` / `paperclip-pr-sync.service` to finish (`systemctl --user is-active`).
3. **Install the new units** from `deployment/systemd/` (copy, replacing `@ROOT@` with the install path, into `~/.config/systemd/user/`): `looop-loops.service`, `looop-loops.timer`, `looop-maintenance.service`, `looop-maintenance.timer`. **Do not overwrite an existing `looop-console.service`:** an install that already runs the standalone console (for example bound to the tailnet address with `--host`, `After=tailscaled.service`, `Restart=always`) keeps its installed unit; copy the template only when no console unit exists, and then apply the local bind settings to the installed copy. Do not edit the repository templates for one machine; edit the installed copies. Then `systemctl --user daemon-reload`.
4. **Disable and remove the old units:** `systemctl --user disable --now paperclip-autonomy.timer paperclip-pr-sync.timer`, then delete the four old unit files. Their names no longer exist in the repository.
5. **Stop `paperclip-board.service`** (stop and disable). looop no longer calls it.
6. **Start the new units:** `systemctl --user enable --now looop-loops.timer looop-maintenance.timer` and `systemctl --user enable --now looop-console.service` if it is not already running (set the console password first: `python3 bin/console-auth.py set-password`; a remote bind also needs its address in `console.origins`).
7. **Verify.** `systemctl --user list-timers 'looop-*'` shows both timers with the next run; `journalctl --user -u looop-maintenance.service` shows two clean cycles; `python3 bin/maintenance.py` exits 0; `python3 bin/console.py` reports `"tracker": "local"`; `curl -s -o /dev/null -w '%{http_code}\n' <console origin>/login` returns 200 for every origin you use (loopback `http://127.0.0.1:3120`, or the tailnet address for a tailnet bind); `/looop` loads through the console login and no header link leaves the console.
8. **Paperclip data stays untouched by P1e.** Deleting `data/instances`, `.runtime/` and any Paperclip database is a separate, separately approved step, and only after archiving the final database backup: take the backup, verify it restores in a scratch location, archive it off the machine's working tree, and only then delete. Keep it out of Git.
9. **Rollback** is only practical before step 4: re-enable the old timers (from tag `paperclip-last` if the unit files were already deleted) and start `paperclip-board.service`. Local jobs written after step 6 are not mirrored back, and the old code cannot run against them.
