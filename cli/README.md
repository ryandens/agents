# cli — Safari history export

Operational and design findings from production debugging are collected in
[`LESSONS_LEARNED.md`](LESSONS_LEARNED.md).

Exports Safari's browsing history to one CSV per day and posts it to the agents API as a
Google service account.

```
~/Safari-History-Exports/Safari History - 2026-07-29.csv
```

```csv
visited_at,title,url
2026-07-29T08:14:22-04:00,Example Domain,https://example.com/
2026-07-29T08:15:03-04:00,"Ruby, Rails and rest",https://example.org/post
```

Run it manually with `just cli-run` to export through yesterday, catch up on missed
days, and upload each day to `POST /api/browser-history`. Nothing runs in the background.

The first run, with no state yet, backfills from a fixed start date — `FIRST_EXPORT_DATE`
in `src/safari_history/state.py`, currently **2026-07-01** — rather than from yesterday.
That backfill obeys `--max-catchup-days` (default 30) like any other catch-up, so a span
longer than the cap takes more than one run; the tool says so when it stops short.
Days before the start date are still reachable by naming them: `export-safari-history
2026-06-14`.

- **Private Browsing is never exported.** Safari does not write those windows to the
  history database at all, so there is nothing here to filter and no way for this tool
  to leak them.
- **No administrator privileges.** Everything installs under your home directory.
- **Full Disk Access depends on the launcher.** macOS may attribute access to Rex Server
  or your terminal app. See [Full Disk Access](#full-disk-access) for setup and verification.

## How it works

```
just cli-run (on demand)
  └── cli/.venv/bin/python3 -m safari_history
        ├── 1. copy  ~/Library/Safari/History.db (+ -wal, -shm) to a temp dir   ← needs FDA
        ├── 2. query history_visits ⋈ history_items for one local day
        ├── 3. write ~/Safari-History-Exports/Safari History - YYYY-MM-DD.csv   (atomic)
        ├── 4. mint a Google ID token from the service account key
        └── 5. POST the visits to /api/browser-history
```

Safari holds `History.db` open in WAL mode all day, so the exporter never reads it in
place: it copies the database and both sidecar files to a temporary directory and reads
the copy. That avoids fighting Safari's locks, picks up visits still sitting in the
write-ahead log (the last few minutes of browsing), and makes it impossible for a bug
here to modify your real history.

The exporter reads available history without opening Safari or attempting a sync.
Empty or stale days are deferred without writing a CSV or advancing the catch-up mark
past the gap. Later runs retry them. Existing CSVs are preserved if a re-export finds
no visits, and even legacy header-only CSVs are never posted or acknowledged.

Every export run also retries pending uploads, including when there are no new days.
If a Tailscale host cannot be reached, the upload sweep stops and leaves the CSVs
pending for a later manual run. These deferrals exit successfully; configuration,
credential, and API errors still report failures.

Timestamps come out of SQLite as `CFAbsoluteTime` — seconds since 2001-01-01 UTC — and
are converted to local time with an explicit UTC offset, so a visit at 23:30 belongs to
the day it felt like rather than to UTC's day.

Two independent records live in
`~/Library/Application Support/safari-history-export/state.json`:

| Record | Meaning |
| --- | --- |
| `last_exported_date` | how far through the calendar the exporter has got |
| `uploads` | which days the API has acknowledged, and the digest of the CSV it saw |

Keeping them separate is what lets an API outage leave exports running and be
repaired later with `export-safari-history upload`, rather than stalling the whole
pipeline behind the network.

## Install

Requires macOS and Python 3.15+. From the repo root:

```sh
just cli-install
```

This creates a dedicated virtualenv at `cli/.venv` in this checkout and installs
the package editably. `just cli-run`, `just cli-upload`, and `just cli-status` use
that environment and the current source, so Python edits need no reinstall.
Re-run `just cli-install` after dependency changes; it preserves the interpreter
binary and any interpreter-specific Full Disk Access grant. The state and CSV locations
are unchanged.

The equivalent by hand:

```sh
VENV="$PWD/cli/.venv"
# Create once; reuse this interpreter on subsequent package installs.
"$(uv python find --no-config --no-project --system "$(cat .python-version)")" -m venv --copies "$VENV"
"$VENV/bin/pip" install --upgrade --editable ./cli
```

`--copies` gives the virtualenv its own Python binary at a stable path. This is
useful when macOS attributes access to the interpreter itself; it does not isolate
access granted through Rex Server or a terminal app. See
[Why a dedicated virtualenv](#why-a-dedicated-virtualenv).

### uvx

`uvx` can run the CLI without installing it into this checkout:

```sh
uvx --from ./cli export-safari-history upload
uvx --from ./cli export-safari-history status
```

Exports still require Full Disk Access in the execution context used. An authorized
launcher may provide that access, but avoid granting it directly to uv's shared cache
interpreter: other tools use that interpreter, and its path can change on upgrades.
The Just recipes use the dedicated editable environment for a stable local setup.

## Full Disk Access

Safari's history is protected by macOS's privacy system (TCC). Unix file permissions say
you may read `~/Library/Safari/History.db`, and reading it still fails:

```sh
$ sqlite3 ~/Library/Safari/History.db "select count(*) from history_items"
Error: unable to open database "…/History.db": authorization denied
```

macOS attributes access to the **responsible code**, which can be the app that
launched the command rather than Python itself. Apple describes this attribution in
[On File System Permissions](https://developer.apple.com/forums/thread/678819).
For commands launched through Rex, the chain is typically:

```text
Rex Server → shell → just → Python → Safari History.db
```

During debugging on this machine, macOS attributed the denied access to **Rex Server**.
Enabling Python's grant alone did not resolve it; enabling Rex Server's grant did.
Commands launched from Warp or another terminal can instead use that app's grant.

1. Open **System Settings → Privacy & Security → Full Disk Access**.
2. Enable **Rex Server** when running through Rex, or the terminal app used to run
   the command. Restart the launcher if macOS requests it.
3. Run `just cli-status` from that same launcher and check for `database: readable`.

If the launcher's grant authorizes access, Python generally needs no separate grant.
To verify, disable the Python entry and run `just cli-status` again from the same
launcher. If it still reports `readable`, the Python entry is redundant. Test each
execution context you use; success in a terminal does not establish access under
`launchd` or another launcher.

If macOS attributes access to Python itself, grant the exact interpreter used by the
Just recipes: `cli/.venv/bin/python3`. Click **+**, press **⌘⇧G**, and paste its absolute
path. Choose `python3`; the picker may disable the versioned `python3.15` file.
Adding the `export-safari-history` script does not identify the Python interpreter.

`just cli-status` prints the interpreter path and checks database readability. It does
not identify the responsible app or establish that a separate Python grant is required.

### Why a dedicated virtualenv

The dedicated environment provides a stable interpreter and an editable install of
this checkout. When access is granted directly to that interpreter, a copied binary
avoids granting it to a shared system or uv interpreter. Any code run by the granted
interpreter can use its access; the grant is not limited to this exporter.

When Rex Server or a terminal app supplies Full Disk Access, the dedicated Python copy
does **not** narrow that app's permission. Other commands launched by the authorized
app can also receive access. Choose the launcher you intend to trust with that access.

Keep the virtualenv's permissions tight (`just cli-install` does this):

```sh
chmod -R go-rwx cli/.venv
```

This limits other users' ability to modify the environment. It does not restrict
commands launched by an app with Full Disk Access, or code run by your own account.

## Configure

The uploader needs the API endpoint and a Google service account key.

```sh
export SAFARI_HISTORY_API_URL="https://agents.example.com/api/browser-history"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/safari-history-export/service-account.json"
```

Create the key in the Google Cloud console (**IAM → Service Accounts → Keys → Add key →
JSON**), save it somewhere only your user can read (`chmod 600`), and add the service
account's email to the backend's `ALLOWED_SERVICE_ACCOUNTS`. Without that, the API
returns 401 no matter how valid the token is — the allowlist is deliberately separate
from `ALLOWED_EMAILS` so authorising a batch job does not create an identity that can
sign in and browse.

The tool signs a short-lived JWT with the service account key, exchanges it with Google
for an ID token, and sends only that ID token. The API never trusts anything this machine
signed; it verifies Google's signature against Google's published certificates. The
token's audience is the origin of `--api-url`, and it must equal the backend's
`APP_BASE_URL` exactly — that is what stops a token minted for this API being replayed
against another service the same account can reach.

## Test it

```sh
CLI="$PWD/cli/.venv/bin/python3"

"$CLI" -m safari_history status                          # config, permissions, pending work
"$CLI" -m safari_history 2026-07-29 --no-upload          # export one day, write no network traffic
"$CLI" -m safari_history upload --dry-run                # what would be sent, without sending
"$CLI" -m safari_history 2026-07-29                      # export and upload one day
"$CLI" -m safari_history               # catch up through yesterday
```

Exporting an explicit date never moves the catch-up high-water mark, so re-exporting last
Tuesday to fix something will not make the next manual run re-do everything since.

Exit codes, for scripting around it:

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | export or state failure |
| 2 | bad arguments or missing configuration |
| 3 | Full Disk Access required |
| 4 | history database not found |
| 5 | history database unreadable or locked |
| 6 | upload or credential failure |

## Manual workflow

Configure `SAFARI_HISTORY_API_URL` and `GOOGLE_APPLICATION_CREDENTIALS` in the
repository's ignored `.env` file (loaded by Just), or export them in your shell.
Direct CLI invocations do not load `.env`.

```sh
just cli-status                  # configuration, permissions, pending work
just cli-run                     # catch up through yesterday and retry uploads
just cli-run --max-catchup-days 365  # larger catch-up after a long gap
just cli-run 2026-07-29           # export and upload a specific day
just cli-upload --dry-run        # inspect pending uploads
just cli-upload                  # retry uploads; no Safari database access needed
```

The existing CSVs and upload ledger are reused. Header-only legacy CSVs remain
pending because the tool refuses to upload or acknowledge empty days; a pending
count alone does not prove that populated history failed to upload.

### Migrate from the former scheduled task

Before removing an existing agent, copy its `SAFARI_HISTORY_API_URL` and
`GOOGLE_APPLICATION_CREDENTIALS` settings from
`~/Library/LaunchAgents/com.ryandens.safari-history-export.plist` into `.env`
or your shell environment. The agent's configuration was a snapshot and may be
the only place those settings were stored.

```sh
just cli-uninstall-agent
```

This unloads the former job and removes its plist, preserving the dedicated
interpreter, state, exports, and historical logs. Installing or updating the CLI
never schedules a background task.

## Uninstall

```sh
just cli-uninstall
```

Or by hand:

```sh
launchctl bootout "gui/$(id -u)/com.ryandens.safari-history-export"
rm ~/Library/LaunchAgents/com.ryandens.safari-history-export.plist
rm -rf cli/.venv
rm -rf "$HOME/Library/Application Support/safari-history-export"     # legacy install + state
rm -f ~/Library/Logs/safari-history-export*.log
```

Remove any exporter-specific Python Full Disk Access entry in **System Settings →
Privacy & Security → Full Disk Access**. Review a Rex Server or terminal app grant
separately: it may also be used by other commands.

Exported CSVs in `~/Safari-History-Exports/` are left alone; delete them yourself.

## Troubleshooting

**`permission denied by macOS privacy protection (TCC)` (exit 3)**
macOS denied access in the current execution context. Follow
[Full Disk Access](#full-disk-access): check the responsible launcher (Rex Server or
your terminal app) before adding a Python grant. Run `just cli-status` from the same
launcher to verify access. If an interpreter-specific grant stopped working after
recreating the virtualenv, remove that Python entry and add the current binary again.

**`no Safari history database` (exit 4)**
Safari has not been used on this account, or the path differs — pass `--database`. macOS
sometimes reports a protected file as missing rather than denied, so if the file is
visibly there, treat this as a Full Disk Access problem.

**`is locked by another process` (exit 5)**
Unusual, since the exporter reads a private copy. Quitting Safari clears it; so does the
next run.

**`could not be read as a SQLite database` (exit 5)**
The copy was taken mid-write. The next run usually succeeds. If it persists, the file may
be damaged.

**`the history query failed` (exit 5)**
Safari's schema changed — normally a macOS upgrade that renamed something in
`history_visits` or `history_items`. The query lives in `src/safari_history/safari_db.py`.

**History export deferred**
Safari has not synced the requested day, or the query returned no visits. A later run
will retry; the exporter never records an empty day on the server.

**Tailscale host is not reachable**
Uploads remain pending until a later run with VPN connectivity. No destination fallback
is used.

**`the API rejected this service account` (401/403, exit 6)**
Either the account's email is missing from the backend's `ALLOWED_SERVICE_ACCOUNTS`, or
the token audience does not match the backend's `APP_BASE_URL`. `status` prints the
audience being used; it must be the scheme and host only, with no trailing path.

**A day exported but never uploaded**
`export-safari-history upload` re-sends everything the API has not acknowledged. The API
deduplicates on (timestamp, url), so re-uploading a day is safe and stores nothing twice.

**Yesterday's CSV is missing entirely**
An empty or stale day is deferred without creating a CSV. Check the command output
for a deferral message. Run `just cli-run` after history has synced; the CLI does not
open Safari or force synchronization.

## Development

See the [development guide](../docs/dagger.md) for setup and checks. CLI tests use
synthetic Safari data and do not require access to your browsing history.
