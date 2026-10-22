# Verified preview

Preview updates are opt-in per project through the machine-local file `data/preview-policies/<lane>.json`. PR sync invokes `bin/preview.py` after mainline reconciliation. It consumes only the passed `data/mainline-verification/<lane>.json` receipt and snapshots that SHA from the managed execution repository. Delivery drafts and original workspaces are never preview sources.

A policy specifies service argv, cwd, environment, loopback health URLs/status, tmux sessions/ports, runtime links, npm install directories, fallback checkout and hashes of reviewed compatibility files. Keep credentials in existing private files linked into the release, never in policy argv or Git. Schema changes invalidate the reviewed hash and leave the previous preview serving until compatibility is reviewed; this updater does not migrate databases.

Dependencies install from lockfiles in a new release before stopping services. Services restart together at the same SHA; readiness failures restart the prior release. `data/previews/<lane>/state.json` records the serving SHA and `failure.json` records update/health failures. Initial rollback uses the existing checkout. Releases retain the current and prior generated versions; installation output is overwritten, service logs use the existing retention limit and rotate on updates. Original runtime data is shared without copying or removal.

For this Linux host, GTP uses frontend 127.0.0.1:3100 and API 127.0.0.1:3010 in tmux. Inngest remains the existing runtime service on 8288. Existing SSH forwarding continues to work. Run `python3 bin/preview.py` for an explicit reconciliation; normally PR sync runs it automatically. No WOS preview policy is enabled.
