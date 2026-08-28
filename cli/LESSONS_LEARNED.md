# Safari history exporter: lessons learned

This document records durable engineering and operational lessons from diagnosing a
stale-history incident and extending the exporter. Examples deliberately avoid personal
paths, service URLs, account identifiers, and browsing details.

## Incident runbook: missing history

Start by identifying the first layer where data disappears. Do not rewind state or
re-upload repeatedly until the source condition is understood.

### Establish the evidence

Set reusable paths without putting machine-specific values in the commands:

```sh
DB="$HOME/Library/Safari/History.db"
STATE="$HOME/Library/Application Support/safari-history-export/state.json"
EXPORTS="$HOME/Safari-History-Exports"
LOG="$HOME/Library/Logs/safari-history-export.log"
ERROR_LOG="$HOME/Library/Logs/safari-history-export.error.log"
```

Then check, in order:

```sh
launchctl print "gui/$(id -u)/<launch-agent-label>"
stat "$DB"
jq '{last_exported_date, updated_at}' "$STATE"
tail -n 50 "$LOG"
tail -n 50 "$ERROR_LOG"
```

For a suspect exported day, count all visits before counting a specific URL family:

```sh
wc -l "$EXPORTS/Safari History - YYYY-MM-DD.csv"
rg -c 'youtube\.com/shorts/' "$EXPORTS/Safari History - YYYY-MM-DD.csv"
```

The CSV has one header row, so a line count of one means the source query returned no
visits at all. That is materially different from a populated CSV with no matching URLs.

### Recognize a closed or unsynced Safari database

Typical signals:

- `History.db` and its WAL have modification times older than the requested day.
- A sequence of recent exports is empty even though activity is expected.
- The export process itself reports that the database is stale or that refresh timed
  out.
- Opening Safari causes the database timestamp or size to change substantially.
- Re-exporting the same days after that refresh produces visits where empty CSVs existed.

Interpretation: the database was a valid SQLite file, but it was not a current view of
Safari history. Zero rows were not evidence of zero activity.

Recovery:

1. Open Safari and allow history to load or sync, or let the exporter perform its
   managed refresh.
2. Confirm the database or WAL timestamp advanced.
3. Rewind the high-water mark only to the day before the first bad export, preserving
   the upload ledger.
4. Run catch-up again and verify that the replacement CSVs contain plausible counts.

Do not accept or upload new header-only CSVs when the database still predates the day.
The exporter should fail without advancing state.

### Recognize cleared Safari history

Typical signals:

- Safari has just refreshed and the database modification time is current.
- The database contains a bounded historical gap: normal visit volume before the gap,
  zero total visits during it, and normal volume afterward.
- Reopening or resyncing Safari does not repopulate the missing interval.
- Re-exporting produces the same header-only CSVs for that interval.
- The API reports successful uploads of zero visits because the source really supplied
  no rows.

Interpretation: the current database no longer contains those records. Clearing history
can remove a selected interval while older and newer records remain, so a bounded gap is
an important clue. The exporter cannot reconstruct deleted URLs or timestamps.

Recovery: none from the current Safari database. Check an authorized backup or another
device only if policy and privacy expectations permit it. Do not fabricate zero-versus-
unknown semantics: record that the interval is unavailable because source history was
cleared.

### Recognize a genuinely quiet day

Typical signals:

- The database was refreshed during or after the day.
- The empty day is isolated rather than a long unexplained run.
- Adjacent days have plausible activity.
- There is corroborating context that Safari was not used, without assuming that lack of
  evidence alone proves inactivity.

Interpretation: a header-only CSV can legitimately mean no recorded Safari browsing,
but only after source freshness has been established.

### Recognize another browser, Private Browsing, or a Safari profile

- Private Browsing is never written to Safari history and cannot be recovered by this
  exporter.
- Activity in another browser will not appear in any Safari database.
- Safari profiles can keep separate history databases. A gap in the default database is
  not proof that every profile is empty; enumerate authorized profile databases before
  concluding that history was cleared.
- Compare total visits, not only target URLs. A populated day with no target URLs is a
  content result; an entirely empty day is a source result.

### Recognize an upload or API problem

Typical signals:

- The CSV is populated, but the UI or API aggregation is empty.
- The state reports pending uploads.
- The error log contains DNS, authentication, authorization, or request failures.
- A retry reports newly stored rows.

Recovery: use the dedicated upload command, then verify `pending upload: 0`. An export
run with no new source days may correctly do nothing and therefore may not retry an old
pending upload.

### Recognize a display or aggregation problem

Typical signals:

- The source CSV is populated.
- The upload ledger acknowledges the exact CSV digest.
- The API contains the visits, but the graph omits or shifts them.

Only at this point investigate date-window limits, timezone boundaries, URL matching,
deduplication keys, API filtering, caching, and frontend rendering.

### Decision table

| Evidence | Most likely condition | Correct action |
| --- | --- | --- |
| Database predates the requested day | Safari closed or unsynced | Refresh Safari; do not advance state |
| Database becomes current and re-export fills the gap | Previously stale database | Replace bad exports and re-upload |
| Current database has a bounded gap unchanged by refresh | Cleared source history | Mark interval unavailable; seek backups only if appropriate |
| Current database has an isolated empty day | Possibly no recorded Safari use | Accept only after corroborating freshness |
| Default database is empty but a profile database has rows | Separate Safari profile | Export and deduplicate all intended profiles |
| CSV populated, pending upload nonzero | Delivery failure | Run upload retry and verify the ledger |
| CSV and upload are populated, graph empty | API/UI issue | Debug aggregation and presentation |

## A successful query is not proof of complete history

Safari can leave `History.db` untouched while the application is closed. History from
other devices may also remain unsynced until Safari starts. In that state, SQLite can
successfully return zero rows even though browsing occurred.

- Treat source freshness and query results as separate facts.
- Consider both `History.db` and `History.db-wal`; recent committed visits commonly live
  in the WAL before checkpointing.
- If both files predate the requested day, fail closed. Do not write an empty CSV or
  advance the export high-water mark.
- A refresh timeout is a failure, not success. Otherwise a database touched earlier in
  the day can still be mistaken for a complete view.
- Keep status diagnostics distinct: readability checks should validate access and
  schema without reporting a readable-but-stale database as corrupt or inaccessible.

## Refresh Safari without taking ownership of the user's session

Opening Safari before export is a practical way to load and sync history, but application
lifecycle management has user-visible consequences.

- If Safari is already running, leave it entirely alone.
- Launch a directly owned process and retain its exact PID. Do not later quit by
  application name; a user can open Safari between the initial process check and launch.
- Terminate only the process created by the exporter, including on timeout and error
  paths.
- Do not claim the launch is hidden unless the implementation can guarantee that without
  requiring additional Automation or Accessibility permissions.
- Guard lifecycle control with a macOS platform check. The database reader remains
  portable for Linux tests and packaged smoke checks, where `/usr/bin/open` may exist but
  has unrelated semantics.

## Full Disk Access belongs to an exact executable

macOS privacy protection is more specific than ordinary Unix permissions.

- Grant Full Disk Access to the dedicated virtual environment's exact versioned Python
  executable, not the console script, an unversioned launcher, Terminal, or a shared
  interpreter.
- A command working from one execution context does not prove it will work under
  `launchd`, and the reverse is also true. Test the same path and context used in
  production.
- Recreating the virtual environment can replace the executable and invalidate its
  privacy grant. To deploy package-only changes, reinstall the local package into the
  existing environment without replacing the interpreter.
- Temporary diagnostics that need protected history must also use the exact granted
  executable. A neighboring `python` symlink may still be denied.

## LaunchAgent configuration is a snapshot

`launchd` does not read shell profiles or a repository `.env` file.

- Render required environment values into the LaunchAgent plist during installation.
- Removing a value from `.env` later does not alter an already-loaded agent.
- Conversely, reinstalling the agent requires those values to be supplied again.
- Ad-hoc shell commands and the scheduled LaunchAgent can therefore have different
  configuration and privacy behavior; documentation should make that distinction clear.

## Keep progress and delivery state independent

The exporter correctly maintains two separate records:

- `last_exported_date`: the contiguous source-processing high-water mark.
- `uploads`: the digest ledger acknowledged by the API.

This separation enables safe recovery:

- Rewind only `last_exported_date` to backfill an older range while preserving upload
  acknowledgements.
- Back up the state file before editing it, update it atomically, and retain restrictive
  permissions.
- Respect the per-run catch-up cap and monitor each run before starting the next.
- Re-exported visits are safe when the API deduplicates on its stable visit key.
- A normal export run with no new days does not necessarily retry a previously failed
  upload; use the dedicated upload command and verify `pending upload: 0`.

## Diagnose the pipeline one layer at a time

Avoid attributing a missing graph segment to the UI before checking the source.

1. Confirm the LaunchAgent ran and inspect its last exit code.
2. Check timestamped stdout and stderr logs.
3. Inspect the state high-water mark and pending-upload count.
4. Count total visits and target URL matches in each exported CSV.
5. Compare upload responses: newly stored rows distinguish a real backfill from a
   deduplicated replay.
6. Only then investigate API aggregation, timezone grouping, and frontend rendering.

A header-only CSV means the queried database contained no rows for that day. It does not
identify why. Possible causes include cleared history, Private Browsing, another browser,
or a separate Safari profile database. Private Browsing is never recoverable from Safari
history because Safari does not record it. Cleared records are likewise unavailable from
the current database.

## Test environmental assumptions explicitly

- Mock application lifecycle operations in unit tests; never open or close a real user
  application from the test suite.
- Cover the timeout, cleanup, already-running, non-macOS, stale-source, and stale-status
  paths independently.
- Tests for missing configuration must explicitly remove relevant environment variables.
  Local task runners may automatically load `.env`, while CI does not.
- Run both the focused CLI suite and the packaged Docker smoke test. Unit tests can mock
  away platform behavior that later breaks the real command in a Linux container.

## Operational completion criteria

A backfill is complete only when all of the following are true:

- The LaunchAgent exits successfully.
- The high-water mark reaches the intended final day.
- Exported CSV counts are plausible and any gaps are explained at the source layer.
- The upload ledger reports no pending days.
- Replayed days report zero newly stored rows unless their source CSV genuinely changed.
