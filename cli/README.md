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

Run nightly by a LaunchAgent, it exports yesterday, catches up on any days the Mac was
asleep or switched off for, and uploads each day to `POST /api/browser-history`.

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
- **One grant.** Full Disk Access goes to a dedicated interpreter this tool owns — see
  [Full Disk Access](#full-disk-access), which is the only fiddly part of the setup.

## How it works

```
launchd (00:15 daily)
  └── ~/Library/Application Support/safari-history-export/venv/bin/export-safari-history
        ├── 1. briefly open Safari in the background if it is not already running
        ├── 2. copy  ~/Library/Safari/History.db (+ -wal, -shm) to a temp dir   ← needs FDA
        ├── 3. query history_visits ⋈ history_items for one local day
        ├── 4. write ~/Safari-History-Exports/Safari History - YYYY-MM-DD.csv   (atomic)
        ├── 5. mint a Google ID token from the service account key
        └── 6. POST the visits to /api/browser-history
```

Safari holds `History.db` open in WAL mode all day, so the exporter never reads it in
place: it copies the database and both sidecar files to a temporary directory and reads
the copy. That avoids fighting Safari's locks, picks up visits still sitting in the
write-ahead log (the last few minutes of browsing), and makes it impossible for a bug
here to modify your real history.

Before exporting pending days, the exporter checks whether Safari is running. If it is
closed, the exporter starts a directly-owned Safari process, waits for history to load
or sync, and terminates only that process. An already-running Safari—or one the user
starts concurrently—is never closed by the exporter. If the database does not update
before the refresh timeout, the export fails without advancing its high-water mark.

Timestamps come out of SQLite as `CFAbsoluteTime` — seconds since 2001-01-01 UTC — and
are converted to local time with an explicit UTC offset, so a visit at 23:30 belongs to
the day it felt like rather than to UTC's day.

Two independent records live in
`~/Library/Application Support/safari-history-export/state.json`:

| Record | Meaning |
| --- | --- |
| `last_exported_date` | how far through the calendar the exporter has got |
| `uploads` | which days the API has acknowledged, and the digest of the CSV it saw |

Keeping them separate is what lets an API outage leave the nightly export running and be
repaired later with `export-safari-history upload`, rather than stalling the whole
pipeline behind the network.

## Install

Requires macOS and Python 3.14+, matching the backend. From the repo root:

```sh
just cli-install
```

That is the whole install. It creates a dedicated virtualenv at
`~/Library/Application Support/safari-history-export/venv` and installs this package
into it, giving you `.../venv/bin/export-safari-history`.

The equivalent by hand:

```sh
VENV="$HOME/Library/Application Support/safari-history-export/venv"
python3 -m venv --copies "$VENV"
"$VENV/bin/pip" install --upgrade ./cli
```

`--copies` matters, and is the reason this is not a `uvx` one-liner. It gives the
virtualenv its own copy of the Python binary at a stable path that nothing else uses,
which is the thing that receives Full Disk Access below. See
[Why a dedicated virtualenv](#why-a-dedicated-virtualenv).

### uvx

`uvx` is fine for the subcommands that do not touch Safari's database:

```sh
uvx --from ./cli export-safari-history upload
uvx --from ./cli export-safari-history status
```

It is the wrong tool for the scheduled export, because `uvx` runs your code with a
shared interpreter from uv's cache — a path that changes when the Python version does,
and that every other `uvx` tool also runs under. Granting Full Disk Access there would
hand it to all of them, and the grant would break on the next Python upgrade.

## Full Disk Access

Safari's history is protected by macOS's privacy system (TCC). Unix file permissions say
you may read `~/Library/Safari/History.db`, and reading it still fails:

```sh
$ sqlite3 ~/Library/Safari/History.db "select count(*) from history_items"
Error: unable to open database "…/History.db": authorization denied
```

The grant is keyed to **the executable that opens the file**. For a Python program that
executable is the interpreter, not the script — adding `export-safari-history` to the
Full Disk Access list does nothing at all, because macOS never sees that path.

Grant it to this tool's own interpreter:

```sh
"$HOME/Library/Application Support/safari-history-export/venv/bin/export-safari-history" status
# interpreter (needs Full Disk Access): /Users/you/Library/Application Support/safari-history-export/venv/bin/python3.14
```

1. **System Settings → Privacy & Security → Full Disk Access**
2. Click **+**, press **⌘⇧G**, and paste the path `status` printed.
3. Make sure the toggle is on.

`status` prints that path precisely so there is no guessing, and warns if it resolves to
a shared interpreter instead of this tool's own.

### Why a dedicated virtualenv

Full Disk Access on an interpreter extends to every script that interpreter runs. Granted
to `/opt/homebrew/bin/python3.14`, `/usr/bin/python3`, or a `uvx` cache binary, any
Python script anyone runs — including one downloaded and executed by mistake — inherits
the ability to read every file on the machine, silently. That is the same objection as
granting it to `/bin/zsh`.

A `--copies` virtualenv gives this tool a private copy of the interpreter binary at a
path nothing else uses, so the grant covers this one program. It is a real reduction in
blast radius, and it is the best available in Python.

It is not as tight as a compiled, signed binary would be, and the difference is worth
being explicit about: anything that can write into that virtualenv — your user account,
without a password prompt — can run code under the grant. A compiled executable's grant
is bound to its code signature, so modifying the binary invalidates the grant instead of
inheriting it. If that difference matters more than staying in Python, a small Swift
executable is the stronger option.

Keep the virtualenv's permissions tight (`just cli-install` does this):

```sh
chmod -R go-rwx "$HOME/Library/Application Support/safari-history-export"
```

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
CLI="$HOME/Library/Application Support/safari-history-export/venv/bin/export-safari-history"

"$CLI" status                          # config, permissions, pending work
"$CLI" 2026-07-29 --no-upload          # export one day, write no network traffic
"$CLI" upload --dry-run                # what would be sent, without sending
"$CLI" 2026-07-29                      # export and upload one day
"$CLI"                                 # what the LaunchAgent runs: catch up
```

Exporting an explicit date never moves the catch-up high-water mark, so re-exporting last
Tuesday to fix something will not make the next scheduled run re-do everything since.

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

## LaunchAgent

```sh
just cli-install-agent    # render the plist with your paths, then load it
```

That writes `~/Library/LaunchAgents/com.ryandens.safari-history-export.plist` from
[`launchd/com.ryandens.safari-history-export.plist`](launchd/com.ryandens.safari-history-export.plist)
and loads it. `launchd` does not expand `~`, so the template's placeholders are replaced
with absolute paths at install time.

By hand — the substitution is deliberately not `sed`. In a `sed` replacement `&` means
"the text that matched", so an API URL carrying a query string (`...?a=1&b=2`) writes
the `__API_URL__` placeholder back into the plist instead of the URL, and `|` or a
backslash breaks the expression outright. The result is a plist `launchctl` rejects with
a message that points nowhere near the cause. The values also land inside XML, so `&`
and `<` need escaping there too:

```sh
venv="$HOME/Library/Application Support/safari-history-export/venv"

AGENT_HOME="$HOME" \
AGENT_API_URL="$SAFARI_HISTORY_API_URL" \
AGENT_CREDENTIALS="$GOOGLE_APPLICATION_CREDENTIALS" \
  "$venv/bin/python" -m safari_history.launch_agent \
  cli/launchd/com.ryandens.safari-history-export.plist \
  > ~/Library/LaunchAgents/com.ryandens.safari-history-export.plist

plutil -lint ~/Library/LaunchAgents/com.ryandens.safari-history-export.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.ryandens.safari-history-export.plist
```

Managing it:

```sh
launchctl print "gui/$(id -u)/com.ryandens.safari-history-export"   # state, last exit code
launchctl kickstart -p "gui/$(id -u)/com.ryandens.safari-history-export"   # run it now
launchctl bootout "gui/$(id -u)/com.ryandens.safari-history-export"        # unload
```

`bootstrap`/`bootout` are the current verbs; `launchctl load`/`unload` still work but are
deprecated and report less.

The job runs at **00:15** local time. If the Mac is asleep, `launchd` runs it once on
wake; if it was switched off, at next login. Either way the run catches up every day it
missed, up to 30 per run (`--max-catchup-days` to go further back in one go).

### Logs

```sh
tail -f ~/Library/Logs/safari-history-export.log
tail -f ~/Library/Logs/safari-history-export.error.log
```

Every line is timestamped, because the only question anyone asks of this log is "did last
night's run happen?".

## Uninstall

```sh
just cli-uninstall
```

Or by hand:

```sh
launchctl bootout "gui/$(id -u)/com.ryandens.safari-history-export"
rm ~/Library/LaunchAgents/com.ryandens.safari-history-export.plist
rm -rf "$HOME/Library/Application Support/safari-history-export"     # venv + state
rm -f ~/Library/Logs/safari-history-export*.log
```

Then remove the Full Disk Access entry: **System Settings → Privacy & Security → Full
Disk Access**, select the interpreter, click **−**. macOS keeps the grant keyed to the
path, so deleting the virtualenv without removing the entry leaves a stale grant that a
future virtualenv at the same path would inherit.

Exported CSVs in `~/Safari-History-Exports/` are left alone; delete them yourself.

## Troubleshooting

**`permission denied by macOS privacy protection (TCC)` (exit 3)**
The interpreter has no Full Disk Access. Run `status`, and add exactly the path it
prints. If it is already listed and enabled, remove the entry with **−** and add it
again — reinstalling the virtualenv replaces the binary the grant was keyed to.

**It works in Terminal but fails under launchd**
Terminal's own Full Disk Access covers anything you run from it, which masks a missing
grant on the interpreter. Test the way `launchd` runs it, with
`launchctl kickstart -p gui/$(id -u)/com.ryandens.safari-history-export`, and read the
error log.

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

**`history database ... was last updated ... before YYYY-MM-DD` (exit 5)**
Safari has not loaded or synced history for the day being exported. The exporter does
not turn that stale view into an empty CSV or advance its high-water mark. Open Safari,
then run the exporter again; the same day will be retried.

**`the API rejected this service account` (401/403, exit 6)**
Either the account's email is missing from the backend's `ALLOWED_SERVICE_ACCOUNTS`, or
the token audience does not match the backend's `APP_BASE_URL`. `status` prints the
audience being used; it must be the scheme and host only, with no trailing path.

**A day exported but never uploaded**
`export-safari-history upload` re-sends everything the API has not acknowledged. The API
deduplicates on (timestamp, url), so re-uploading a day is safe and stores nothing twice.

**Yesterday's CSV is missing entirely**
A day with no browsing still produces a header-only CSV — that is the difference between
"exported and empty" and "never exported". If the file is absent, the run did not happen:
check `launchctl print` and the error log.

## Development

```sh
just cli-check      # lint, format check, tests
just cli-test
```

The tests build a synthetic database with Safari's schema and timestamp convention, so
they need neither Safari nor Full Disk Access and run in CI.
