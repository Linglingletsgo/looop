# Standalone architecture (Paperclip removal)

Status: approved direction, implemented in slices on `refactor/standalone`. Live cutover needs a separate operator step.

## Goal

looop runs without Paperclip. One source of truth (project state + a local job table), its own worker launcher, its own console server and login. Paperclip, if still running, is at most a one-way mirror during migration and is then removed.

## What Paperclip did, and its replacement

| Paperclip role | Replacement |
|---|---|
| Issue = job id and job status | `jobs` table, local ids (`uuid4().hex`); legacy issue UUIDs stay valid as job ids |
| Agent assignment + heartbeat wake (60s, wakeOnDemand, maxConcurrentRuns 1) | `launch_loops.py` starts `looop-delivery-<lane>` tmux session when the lane has a `todo` delivery job; worker claims with a lease |
| `PAPERCLIP_AGENT_ID` identity check | job lease owned by `process_owner.identity()` (boot_id + start_ticks) |
| `auth/get-session` owner id | constant owner `"owner"` from local config |
| Issue comments | bounded `job_events` rows (latest 50 per job) |
| Web host + login | standalone console server (slice P3) |
| cost-events | usage stays in run receipts (`metrics.py` writes locally) |

## Job model (`bin/jobs.py`)

Stored in `data/jobs.sqlite` (WAL, one connection per call, same style as `project_state.Store`).

```
jobs(id TEXT PRIMARY KEY, lane TEXT, kind TEXT,          -- kind: planning | delivery | status
     title TEXT, status TEXT, assignee TEXT,              -- assignee: 'lane:role' key, 'owner', or NULL
     description TEXT, created REAL, updated REAL,
     lease_owner TEXT, lease_until REAL)
job_events(job TEXT, at REAL, kind TEXT, body TEXT)        -- comment / status, bounded per job
```

Statuses keep the existing vocabulary so call sites change mechanically: `backlog todo in_progress in_review blocked done cancelled`.

API (all raise `KeyError` for unknown ids, `ValueError` for invalid status):

- `Jobs(root)`
- `create(lane, kind, title, description='', status='backlog', assignee=None, job_id=None) -> dict` — returns `{'id','identifier','lane',...}`; `identifier` = `LANE-<first 8 of id>`. `job_id` lets migration import legacy ids; duplicate id with different payload raises.
- `get(id) -> dict | None`
- `update(id, status=None, assignee=<unchanged>, comment=None, description=None) -> dict`
- `list(lane=None, status=(...), assignee=None, kind=None) -> list[dict]`
- `claim(id, owner, ttl) -> bool` / `release(id, owner)` / `holder(id)`; a lease whose owner is no longer alive (`process_owner.alive`) is free.
- `owner() -> 'owner'`

Creation is local and atomic, so the `binding-request.json` "posting / unknown remote result" journal collapses into: write journal → `create(job_id=preallocated)` → bind. Reconciliation remains for crash between steps but never queries a remote.

## Tracker seam during migration

Planning and delivery call sites use the `tracker` seam (`bin/tracker.py`), never `Board`: `PaperclipTracker` (default) maps lanes/roles through `data/control.json` and keeps the current HTTP calls unchanged; `LocalTracker` uses `jobs.Jobs`. `data/local-settings.json` `{"tracker": "local"}` opts in; missing or invalid settings stay on Paperclip. In local mode there is no Paperclip agent to import usage for, so `delivery-worker.py` and `health.py` skip cost events (usage stays in run receipts) and `delivery-control.py configure` writes the policy without creating an agent. A `PaperclipMirror` (optional `{"mirror": {"paperclip": true}}`) may replay job events to Paperclip from `state-sync.py`; default off. Removing Paperclip = leaving the mirror off and deleting the mirror module.

## Slices

- **P1a** `bin/jobs.py` + tests. No call-site changes.
- **P1b** planning path via the tracker seam: `autonomy.py`, `binding_requests.py`, `loop-status.py`, `planning_intervention.py`, `planning-recovery.py`. Local mode is not end-to-end until P1c.
- **P1c** delivery path: `delivery-worker.py` (lease, no `PAPERCLIP_AGENT_ID`), `dispatch.py`, `delivery-control.py`, `restart-recovery.py`, `health.py`, `launch_loops.py` worker launch.
- **P1c+** local-mode Paperclip-free paths: `state-sync.py` never constructs `Board` locally and acknowledges each lane's outbox through the current revision (so the 5000-row `Held` limit cannot stall writes); in Paperclip mode it still mirrors and adds the board session `assigneeUserId` to `in_progress` payloads. `onboarding.py connect` creates no company/project locally, records `company/project: null`, and local lanes carry no Paperclip ids. Maintenance, console and launch paths use the tracker seam in local mode.
- **P1d** `scripts/migrate-jobs.py --root PATH [--board] [--apply]`: import existing bindings / deliveries / autonomy receipts / status-board issues into `jobs` with their legacy ids and derived status. Dry-run by default; `--apply` takes `data/locks/migrate-jobs`, creates only missing jobs, reports an existing same-lane/same-kind job as `existing` (never updated) plus any `differs` fields, and treats only a different lane/kind as a conflict (exit 1, nothing updated). Malformed or invalid source files are skipped and listed under `errors` (also exit 1 on `--apply`) without blocking other rows. `--board` overlays Paperclip issue status/title through GET only and never signs in; an id whose board request fails is reported as `board_error` and is not created so a later rerun can import board values. Run a `--board` dry run first, then `--apply --board`; the first successful apply fixes the imported values and later runs only report differences. Idempotent; no network without `--board`.
- **P1e** delete Paperclip-only modules (`bridge.py` logic moved where still needed, `gtp_worker.py`, `fixture_worker.py`, `gtp_resume.py`, `provision*.py`, `setup_fixture.py`, `control.py` agent creation), optional mirror in `state-sync.py`.
- **P3** console server (Python stdlib), login: loopback default, scrypt owner password, optional `tailscale serve` identity.
- **P4** de-personalize (lanes, providers, paths, strings into config).
- **P5** single `looop recover TASK`, package layout.

### Local worker launch (P1c)

`launch_loops.py` runs on the short timer. In local mode, for each lane with `data/delivery-policies/<lane>.json` and a `todo` delivery job assigned to `<lane>:delivery`, it starts one detached tmux session `looop-delivery-<lane>`:

```
/usr/bin/python3 <root>/bin/delivery-worker.py <lane> >> logs/delivery-<lane>.log 2>&1
```

The session is skipped when one already exists or the job already holds a live lease. Planning pause does not gate this: an already bound Packet keeps running, exactly like the Paperclip heartbeat did. The worker handles one pass and exits, so the timer re-launches it on the next tick. Paperclip mode starts no delivery sessions; the Paperclip agent heartbeat still runs the same worker.

## Invariants (unchanged by the refactor)

- Project-owned state stays authoritative; jobs table holds dispatch state only.
- Immutable bindings, SHA checks, independent review, merge policy, retention.
- Pause stops new selection; operator stop is respected; no paid fallback.
- No model call when there is no job.

### Console server (P3)

The standalone console is a Python standard-library server (`bin/console-server.py`) that serves `ui/index.html`, `ui/app.js` and `ui/style.css`, proxies the two existing API routes to `bin/console.py` / `bin/console_actions.py`, and adds its own owner login. The Paperclip-hosted console (`ui/server.mjs`, `bin/install-ui.py`) is unchanged.

1. Set the owner password (minimum 12 characters; never printed):
   `python3 bin/console-auth.py set-password`
   This writes `data/console-auth.json` (mode 0600, scrypt N=16384 r=8 p=1, random generation id) and invalidates every existing console session. `python3 bin/console-auth.py status` reports whether a password is set without printing the hash.
2. Start the server: `python3 bin/console-server.py` (defaults to `127.0.0.1:3120`). Use `--host` / `--port` to override. A non-loopback bind requires a configured password; a loopback bind without one is refused unless `--insecure-local-dev` is passed (login disabled, loopback only, loud warning). The server trusts only `Host` values derived from its configured origins, never the request header: the defaults are `http://127.0.0.1:<port>` and `http://localhost:<port>` (plus `http://[::1]:<port>` for an IPv6 loopback bind). A reverse proxy therefore needs an explicit origin, for example `data/local-settings.json`:

```json
{"console": {"origins": ["https://box.tailnet.ts.net"]}}
```

   Any other `Host` gets `421` before routing. POSTs additionally require `Origin` to equal one configured origin. `Secure` cookies are used only for an `https` origin (`X-Forwarded-Proto` is not trusted). Sessions expire after 12 hours idle or 7 days absolute; failed logins are limited to 5 per client address and 30 globally per 15 minutes, reserved before password verification. Changing the password rotates a stored generation, so every session (including a login racing the change) is rejected. Child output is capped at 1 MiB and 60 seconds; header/body reads time out after 15 seconds and at most 16 requests run concurrently (excess gets `503`).
3. systemd user unit example (not installed by this repository), `~/.config/systemd/user/looop-console.service`:

```
[Unit]
Description=looop standalone console
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/projects/looop
ExecStart=/usr/bin/python3 %h/projects/looop/bin/console-server.py
Restart=on-failure

[Install]
WantedBy=default.target
```

Then `systemctl --user daemon-reload` and `systemctl --user enable --now looop-console.service`.

Remote access uses Tailscale, not a public bind: `tailscale serve --bg --https=<port> http://127.0.0.1:3120` exposes the loopback console on the tailnet with Tailscale's TLS (pick a port not already served; serve needs root or `tailscale set --operator`). Add the resulting `https://<host>.ts.net:<port>` to `console.origins`, otherwise every request gets `421`. Tailscale identity login is a later slice; today the owner password remains the only login method. Do not combine remote exposure with `--insecure-local-dev`.
