# Canonical training evidence

Athlete Orbit Phase 2 keeps `Activity` as the stable deduplicated workout identity and adds one provider-neutral `ActivityTrainingEvidence` companion row for richer workload evidence.

The companion stores only normalized, bounded fields needed by product behavior: modality, provider sport/sub-sport provenance, timing distinctions, heart rate, energy, cycling power, cadence, Garmin-supplied training-effect observations, and bounded normalized lap/set structure. Raw FIT record streams are not copied into product storage.

## Unknown semantics

Absent HR, power, distance, laps, sets, or training-effect values remain null/unavailable. Strength is classified as strength and its unsupported distance remains null. No universal Fitness-Pals training-load score is derived in Phase 2.

## Provenance

Each evidence row links to the canonical Activity and ingest run and retains the source provider plus Drive object ID/name/version/content hash when available. `observed_fields` identifies directly observed source fields; `modality` is explicitly listed as derived.

## Replay and backfill

The existing Garmin archive ingest is the replay seam. Re-decoding the same Drive FIT is idempotent: canonical Activity fingerprinting remains unchanged and the one-to-one evidence row is enriched in place. Historical backfill should therefore replay bounded athlete-owned Drive archive objects, preferably dry-run/checkpointed through the existing archive job path, rather than infer rich evidence from lossy Activity rows.

For Fenix 8 history, `Garmin/Fenix8_Backup` remains the durable source of truth. PulsAI is not a fill source.
