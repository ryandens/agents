# Fitness log foundations

The Fitness page at `/fitness` is a shared, authenticated log, consistent with the
site's existing pantry. All allowed users see and edit the same workouts. It is
not a separate private log per Google account.

## Domain

- **Exercise**: a reusable identity and display name. Use separate identities for
  equipment or movement variants that should not be compared. Exercise names describe the logged movement;
  a name alone does not establish equipment or technique.
- **Workout**: a UUID, local calendar date, notes, and the original source note.
  More than one workout can occur on the same day. A date is not a UTC timestamp.
- **Workout exercise**: an ordered occurrence of an exercise within a workout.
  Repeating an exercise in a session is allowed. Notes can preserve an observation
  even when the number of sets is unknown.
- **Set**: an ordered record within that occurrence. Actual reps, optional target
  reps, load, unit, load basis, duration in seconds, reported failure, phase
  (work/warmup/cooldown), and notes. Null is unknown; zero reps is a recorded
  unsuccessful attempt. Failure is tri-state: yes, no, or not recorded.

Load basis is `total`, `per_hand`, `machine`, `bodyweight`, or `unspecified`.
Bodyweight has a null external load, not a made-up zero-pound resistance.
Machine setting and dumbbell weight are recorded values, not estimates of force.
Rep conventions such as "both arms" are retained in notes and never multiplied.

Four normalized PostgreSQL tables store these entities. Ordered entry/set
positions are identities within their parent; editing replaces a workout's
children atomically. Exercise IDs and workout IDs persist. No set-level external
references or edit audit history are promised yet. Offline edits carry expected revisions and reject stale writes. The legacy PUT
endpoint increments revisions; it retains last-write-wins behavior for its callers. The log reads all workouts for now, appropriate to this
small personal dataset; pagination can be added when necessary.

## Synthetic demo data

The page's **Import demo workouts** button imports three entirely fictional
sessions dated January 2000, with invented exercises, loads, rep counts,
durations, and source notes. They do not reproduce a person's workout history
or original prose. These examples cover actual versus target reps, reported
failure, unknown load, ambiguous set counts, undoubled dumbbell reps, and
separate cycling work and cooldown records.

The import runs in a single transaction. A database ledger makes retries and
simultaneous imports idempotent. It does not insert demo data in schema
migrations. Deleting a demo workout does not reset that ledger or cause it to
reappear. Demo records are ordinary editable workouts and contribute to the
overview until deleted.

Replacing the bundled fixtures does not modify previously imported database
records. Existing real workout logs remain unchanged.

## First aggregate

The overview derives session count, recorded set count, actual rep sum, recorded
duration, and latest date for each exercise. A session is counted once per
exercise even if it contains multiple occurrences. Workouts containing only an
ambiguous note still count as sessions, but contribute no invented sets or reps.
Recorded sets include work, warmup, and cooldown; timed sets count as sets.
Duration includes cooldown and does not estimate total time spent in the gym.
Missing rep counts on untimed sets are shown as unknown.

There is deliberately no combined volume, estimated one-rep maximum, strength
score, or cross-exercise ranking. Comparing those later requires confirmed
movement/equipment identity and compatible load and rep conventions.

## API and running

Migration `0003` creates the tables. Apply it with `just db-migrate` (or use
`just dev`, which migrates before starting). Open `/fitness` and import the demo workouts
or log a workout. Nothing in this change deploys or writes to production.

All routes require the existing authentication:

- `GET/POST /api/fitness/exercises`
- `GET/POST /api/fitness/workouts`
- `PUT/DELETE /api/fitness/workouts/{uuid}`
- `GET /api/fitness/summary`
- `POST /api/fitness/import-samples`

PUT replaces the full workout. Invalid values are rejected before storage;
unknown exercise references return 422. Missing workouts return 404 and duplicate
exercise IDs return 409. Source notes remain available when editing imported
workouts. Tests exercise the real migrations and persistence, authentication,
synthetic examples, aggregates, and the logging UI.


## Offline iPhone / home-screen use

After deployment, open Fitness once with the VPN connected and sign in. Wait for
**Ready to open offline**. The production build precaches the Fitness HTML plus
all exported JS, CSS, fonts, and app icons. The web manifest opens at `/fitness/`;
older home-screen shortcuts pointing to `/` fall back to Fitness if the server
cannot be reached. Development mode deliberately does not install a worker.

Workouts and the exercise catalog live in IndexedDB, partitioned by Google
subject ID. Each save/delete and its outgoing mutation commit in one transaction.
A save is reported successful only after the transaction commits. New exercises
can also be created offline and are queued before the workouts that reference
them. Summaries use the local records immediately.

The form saves an unfinished draft locally as fields change. Closing/reloading
the app leaves a **Resume draft** action. Drafts do not sync until **Save workout**
is pressed. A local backup export includes the draft, workouts, catalog, and
outbox; the form also offers a direct draft export if storage fails. Backup import
is not implemented; the JSON is a recovery artifact.

The client retries on launch, foreground/focus, the browser's online event, and
every 30 seconds while visible. It also tries immediately after saving or deleting.
It uses bounded API requests, not `navigator.onLine`, because Wi-Fi/cellular
connectivity does not imply VPN access. **Sync now** is available too. The app
does not promise uploads while iOS has suspended or closed it: reopen it with the
VPN connected to finish syncing.

A cached local profile permits opening Fitness when offline or when the session
expires; it does not authenticate API requests. Sync checks the current account
and the server independently checks the `X-Fitness-Owner` header. A 401 pauses
upload and offers sign-in without deleting the queue. Sign-out removes the cached
profile but retains account-partitioned local work for the next sign-in. Cached
workouts remain on the device; anyone with access to that unlocked browser profile
can access its local storage.

`POST /api/fitness/sync` accepts a UUID mutation ID and a save, delete, or exercise
payload. Migration `0004` adds workout revisions and durable receipts. Receipt
and data commit together: replaying a lost acknowledgement does not duplicate a
workout or resurrect a deleted workout. Reusing an ID for different data is
rejected. A stale workout revision returns 409 and leaves the local queue intact.
The UI can preserve the local version as a new workout or explicitly discard its
queued changes and use the server version. Conflicts pause the queue until
resolved, rather than silently replacing someone else's workout.

The worker caches only public build assets, never API responses. Its cache name
is derived from the build contents, and an update waits for existing app pages
to close before activating. The build script in `package.json` runs
`scripts/build-offline.mjs` after static export; deployments must include that
step. A direct `next build` alone is insufficient to generate the offline worker.

Browser storage can still be removed by clearing website data or under storage
pressure. The app requests persistent storage when supported, but shows no
guarantee of permanent storage. Sync regularly and use Export local backup before
clearing/reinstalling the web app. WebKit documents its
[storage persistence policy](https://webkit.org/blog/14403/updates-to-storage-policy/).

### Verification

Automated tests cover offline saves, draft recovery, queue ordering, account
separation, expired sessions, lost acknowledgements, concurrent refresh/save,
conflicts, local validation, service-worker navigation, and API cache exclusion.
Backend integration tests use disposable PostgreSQL to verify receipt rollback,
idempotent replay, revision checks, and account checks.

Before releasing to a phone: open while connected, wait for the offline-ready
label, disconnect VPN/network, reload from the home-screen icon, create an exercise
and workout, close/reopen to recover the draft, save, reconnect VPN, foreground the
app, and verify the pending count clears and the server has exactly one workout.
Desktop Safari was also checked against the production export: unavailable-server
reload, IndexedDB draft recovery, offline save, and automatic retry after restoring
the server all passed with fictional data. Physical iPhone suspension/eviction
behavior still needs device verification.


## Mobile workout entry

All exercises and sets stay editable in place, with compact rep/time and weight
rows. Search an existing exercise or create and add one offline. Optional targets,
load convention, units, phases, and notes remain under set options. Switching
measurement modes preserves recorded values.

**Add set** leaves measurements unknown while retaining the previous unit and
load convention. **Repeat last set** explicitly copies the measurements and phase
but clears failure and set notes. **Remove exercise** is visible in each exercise
header; each set has a visible **Remove** control. Deletion applies immediately
to the draft, with a one-level Undo action that restores only the removed item,
preserving subsequent edits to other sets. Undo is available until another
removal, saving, or closing the form; it is not a persistent deletion history.
Removing a set does not reassign another set's editor state because editor keys
remain stable.

**Save workout** saves directly; **Preview summary** is optional. The bottom bar
keeps saving, closing, and Undo within reach. Numeric keyboards, large touch
targets, safe-area padding, and 16px-or-larger inputs support phone entry. Enter
in an input cannot accidentally submit. Connection and backup controls collapse
while editing. Existing offline draft and sync behavior is unchanged.

Exercise entry now starts with a bundled, offline category browser. Equipment and body area are separate filters; either can be the starting point. Library exercises have stable IDs and only enter the local catalog when selected, with their creation queued before the workout. Existing/custom exercise names are preserved without guessing that they are equivalent to library movements. Library metadata chooses an initial measurement mode and identifies machine/bodyweight loads; it never fills in completed reps, weight, or duration. Free-weight load interpretation remains explicit in set options.

Primary measurements use tap presets or a built-in numeric keypad, including fractional weights, clear, and increment/decrement controls. Opening these controls does not open the device keyboard. Notes and custom exercise creation still support typing. Set and exercise removal with Undo remain available while editing.

New exercise entries prefill their first set from the first recorded working set in the most recent locally saved workout for that exact exercise ID (falling back to a recorded warmup/cooldown only when no working set is recorded). The lookup excludes the workout being edited and dates later than its selected date. No-history and unknown measurements remain blank. A dated history hint makes the starting values visible; they are editable defaults, not a progression recommendation. Existing drafts and saved sets are never rewritten when history refreshes.

Add set copies measurements and units/load basis from the current first set. Repeat last set remains available for a different most recent set. Both actions clear failure, notes, and target reps and create a working set. Later edits affect only the edited set, not previously added sets. These defaults use the account's local history and work offline.
