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

Planning call sites use the `tracker` seam (`bin/tracker.py`), never `Board`: `PaperclipTracker` (default) maps lanes/roles through `data/control.json` and keeps the current HTTP calls unchanged; `LocalTracker` uses `jobs.Jobs`. `data/local-settings.json` `{"tracker": "local"}` opts in; missing or invalid settings stay on Paperclip. A `PaperclipMirror` (optional `{"mirror": {"paperclip": true}}`) may replay job events to Paperclip from `state-sync.py`; default off. Removing Paperclip = leaving the mirror off and deleting the mirror module.

## Slices

- **P1a** `bin/jobs.py` + tests. No call-site changes.
- **P1b** planning path via the tracker seam: `autonomy.py`, `binding_requests.py`, `loop-status.py`, `planning_intervention.py`, `planning-recovery.py`. Local mode is not end-to-end until P1c.
- **P1c** delivery path: `delivery-worker.py` (lease, no `PAPERCLIP_AGENT_ID`), `dispatch.py`, `delivery-control.py`, `restart-recovery.py`, `health.py`, `launch_loops.py` worker launch.
- **P1d** `scripts/migrate-jobs.py`: import existing bindings / deliveries / autonomy receipts into `jobs` with their legacy ids and derived status; idempotent, dry-run by default.
- **P1e** delete Paperclip-only modules (`bridge.py` logic moved where still needed, `gtp_worker.py`, `fixture_worker.py`, `gtp_resume.py`, `provision*.py`, `setup_fixture.py`, `control.py` agent creation), optional mirror in `state-sync.py`.
- **P3** console server (Python stdlib), login: loopback default, scrypt owner password, optional `tailscale serve` identity.
- **P4** de-personalize (lanes, providers, paths, strings into config).
- **P5** single `looop recover TASK`, package layout.

## Invariants (unchanged by the refactor)

- Project-owned state stays authoritative; jobs table holds dispatch state only.
- Immutable bindings, SHA checks, independent review, merge policy, retention.
- Pause stops new selection; operator stop is respected; no paid fallback.
- No model call when there is no job.
