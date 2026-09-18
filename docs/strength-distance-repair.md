# Scoped Garmin strength-distance repair (operator runbook)

Do **not** run against production as part of this MMF. Code-side filtering protects readers before a data repair. A later operator needs explicit approval, a database backup, and a maintenance window. Never delete activities, sleep sessions, or source/provenance rows.

The only repair target is `users.email = 'dave0875@gmail.com'`, joined by `activities.user_id`, with a Garmin source row, a Strength sport, and the exact sentinel `distance_m = 21474836`. Record the resolved user UUID from the first query; do not substitute an account or widen the predicate. The initial target count is expected to be 12; a rerun after successful repair should be 0. Any other count stops the procedure for investigation.

## Dry run (transaction is always rolled back)

Run these statements in `psql` on the intended database. Save the output as change evidence. The first query also gives the before counts; compare all three counts after the update. The historical backfill had 3,522 canonical activities and 3,420 sleep days, but concurrent ingest may increase those totals, so preserve the *measured* before counts rather than requiring those historical numbers.

```sql
BEGIN;
SELECT id, email FROM users WHERE email = 'dave0875@gmail.com';
SELECT (SELECT count(*) FROM activities) AS activities_before,
       (SELECT count(*) FROM sleep_sessions) AS sleep_before,
       (SELECT count(*) FROM activity_sources) AS sources_before;
CREATE TEMP TABLE repair_targets ON COMMIT DROP AS
SELECT a.id, a.user_id, a.distance_m AS old_distance_m
FROM activities a
JOIN users u ON u.id = a.user_id
WHERE u.email = 'dave0875@gmail.com'
  AND lower(a.sport) IN ('strength', 'strength_training', 'weight_training')
  AND a.distance_m = 21474836
  AND EXISTS (
    SELECT 1 FROM activity_sources s
    WHERE s.activity_id = a.id AND s.provider IN ('garmin', 'garmin_archive')
  )
FOR UPDATE OF a;
SELECT count(*) AS targets_before FROM repair_targets;
SELECT DISTINCT user_id AS scoped_user_id FROM repair_targets;
DO $$ BEGIN
  IF (SELECT count(*) FROM repair_targets) NOT IN (0, 12) THEN
    RAISE EXCEPTION 'Unexpected strength sentinel count; refusing repair';
  END IF;
END $$;
SELECT id, user_id, old_distance_m FROM repair_targets ORDER BY id;
UPDATE activities a SET distance_m = NULL
FROM repair_targets t
WHERE a.id = t.id AND a.user_id = t.user_id AND a.distance_m = t.old_distance_m;
SELECT count(*) AS remaining_targets FROM activities a
JOIN repair_targets t ON t.id = a.id
WHERE a.distance_m = 21474836;
SELECT (SELECT count(*) FROM activities) AS activities_after,
       (SELECT count(*) FROM sleep_sessions) AS sleep_after,
       (SELECT count(*) FROM activity_sources) AS sources_after;
ROLLBACK;
```

## Approved apply and rollback

After approval, take a database backup and repeat the transaction above. Immediately after listing the targets and **before** the update, export them with `\copy repair_targets (id, user_id, old_distance_m) TO '/restricted/approved-backup.csv' WITH CSV HEADER` (replace the path with a restricted, operator-controlled location). Verify the 12 IDs, account UUID, three unchanged row counts, and zero remaining target sentinels. Replace only the final `ROLLBACK` with `COMMIT`. The `distance_m = old_distance_m` predicate makes a replay a no-op: a second run has zero targets and changes zero rows. Keep the backup and query output under the deployment change record; source rows retain provenance.

To reverse an approved apply, use the saved CSV in a new transaction. Substitute the same restricted path and the recorded user UUID; do not infer either from the current login. Confirm the affected count is 12, all three table counts are unchanged, and then commit. This update touches only still-null rows; investigate rather than overwrite a row that has since gained a valid distance.

```sql
BEGIN;
CREATE TEMP TABLE restore_targets (id uuid PRIMARY KEY, user_id uuid, old_distance_m double precision) ON COMMIT DROP;
-- In psql: \copy restore_targets (id, user_id, old_distance_m) FROM '/restricted/approved-backup.csv' WITH CSV HEADER
SELECT count(*) AS saved_count, count(DISTINCT user_id) AS saved_users FROM restore_targets;
DO $$ BEGIN
  IF (SELECT count(*) FROM restore_targets) <> 12
     OR (SELECT count(DISTINCT user_id) FROM restore_targets) <> 1
     OR EXISTS (SELECT 1 FROM restore_targets WHERE old_distance_m <> 21474836)
     OR EXISTS (
       SELECT 1 FROM restore_targets t
       LEFT JOIN activities a ON a.id = t.id AND a.user_id = t.user_id
       LEFT JOIN users u ON u.id = t.user_id
       WHERE a.id IS NULL OR u.email IS DISTINCT FROM 'dave0875@gmail.com'
          OR lower(a.sport) NOT IN ('strength', 'strength_training', 'weight_training')
          OR a.distance_m IS NOT NULL
          OR NOT EXISTS (
            SELECT 1 FROM activity_sources s
            WHERE s.activity_id = t.id AND s.provider IN ('garmin', 'garmin_archive')
          )
     ) THEN
    RAISE EXCEPTION 'Rollback targets do not match approved backup';
  END IF;
END $$;
UPDATE activities a SET distance_m = t.old_distance_m
FROM restore_targets t
WHERE a.id = t.id AND a.user_id = t.user_id AND a.distance_m IS NULL;
-- Verify 12 restored rows and unchanged activities/sleep_sessions/activity_sources counts.
-- COMMIT only after verification; otherwise ROLLBACK.
ROLLBACK;
```

Rolling back the application code alone does **not** undo a committed data repair.
