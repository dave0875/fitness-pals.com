# Canonical training evidence

Athlete Orbit Phase 2 keeps `Activity` as the stable deduplicated workout identity and adds one provider-neutral `ActivityTrainingEvidence` companion row for richer workload evidence.

The companion stores only normalized, bounded fields needed by product behavior: modality, provider sport/sub-sport provenance, timing distinctions, heart rate, energy, cycling power, cadence, Garmin-supplied training-effect observations, and bounded normalized lap/set structure. Raw FIT record streams are not copied into product storage.

## Unknown semantics

Absent HR, power, distance, laps, sets, or training-effect values remain null/unavailable. Strength is classified as strength and its unsupported distance remains null. No universal Fitness-Pals training-load score is derived in Phase 2.

## Provenance

Each evidence row links to the canonical Activity and ingest run and retains the source provider plus Drive object ID/name/version/content hash when available. `observed_fields` identifies directly observed source fields; `modality` is explicitly listed as derived. `field_provenance` records the exact source object for each observed field so a later sparse JSON replay cannot relabel HR or power that actually came from FIT.

## Replay and backfill

The existing Garmin archive ingest is the replay seam. Re-decoding the same Drive FIT is idempotent: canonical Activity fingerprinting remains unchanged and the one-to-one evidence row is enriched in place. Historical enrichment must re-decode FIT rather than infer rich evidence from lossy Activity rows. `scripts/backfill_training_evidence.py` is dry-run by default and selects a deterministic bounded FIT set. Apply mode requires an exact athlete email + UUID, an expected file count, and a durable JSON checkpoint. It records before/after evidence counts and per-file failures; replay uses the same canonical fingerprint seam and one-to-one evidence upsert.

For Fenix 8 history, `Garmin/Fenix8_Backup` remains the durable source of truth. PulsAI is not a fill source.
