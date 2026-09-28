# Vital Presence Phase 2A: Pal Identity Contract

The approved Fitness-Pals finalists are no longer treated as interchangeable artwork. The product direction is a **cast of durable coaching identities**: each Pal can look different, sound different, respond differently, and build a relationship with the same athlete without leaking one Pal's private memories into another.

This phase intentionally freezes the architecture before changing myChat's database or live runtime.

## Why a persona identity layer is required

Amanda currently combines a model/system contract, voice behavior, profile-aware memory, authentication boundaries, and a visual presence. Expanding that pattern to five Fitness Pals by copying Amanda five times would create drift and, more seriously, ambiguous memory ownership.

The canonical key is therefore `persona_id`.

One activated `persona_id` binds:

- visual/avatar identity;
- generated model definition;
- system prompt and personality;
- voice profile;
- long-term memory namespace;
- capabilities/version metadata.

The model files may share a base model, but each activated Pal must have its own generated model definition equivalent in role to `Amanda.Modelfile`. Persona-specific instructions are first-class configuration, not frontend decoration.

## Finalist inventory

The approved cast contains **five** finalists.

The repository currently has reliable source identity for:

- **W16**
- **W21**
- **W51 — Tokyo Strength**

Two additional approved finalists exist in the design decision but their canonical ids/names are not present in source control available to this execution. This phase does **not** fabricate them. Those two slots remain intentionally unresolved and cannot be activated until their canonical identity is supplied.

That unresolved state is a contract feature, not a TODO hidden under a fake name.

## Memory ownership

Long-term memory must be owned by the tuple:

`(authenticated_profile_id, persona_id)`

That means:

- the same athlete can build separate histories with different Pals;
- one Pal cannot recall another Pal's private memory by default;
- anonymous/stateless sessions cannot write private long-term memory;
- Fitness-Pals does not copy or replicate the private memory database;
- myChat remains the authority for profile authentication and private memory.

Adding `persona_id` to durable memory is a schema migration. It must use myChat's explicit migration-ledger mechanism after that mechanism is terminal-green. No ad-hoc `CREATE/ALTER IF NEEDED` initialization is allowed as a shortcut.

## Voice ownership

Every activated Pal gets a distinct voice profile keyed by `persona_id`. Voice character and speaking behavior belong to the persona package.

Speaker recognition is not authentication. Fitness-Pals never gains authority to unlock a private myChat profile from a visual Pal selection or a claimed browser profile id. myChat remains authoritative for passkey/trusted-presence/private-profile access.

Microphone use stays explicit. Voice playback stays non-autoplay. Stop/barge-in remains immediate.

## Repository boundary

The intended runtime path remains:

`Fitness-Pals authenticated UI → same-origin Fitness-Pals Pal adapter → separately deployed myChat service`

Fitness-Pals may know public persona metadata and the selected `persona_id`. It must not copy myChat source, databases, user profiles, memories, voice credentials, biometric material, or passkeys.

If the Pal service is unavailable or private profile access is locked, the existing Fitness-Pals text Coach remains usable.

## Incremental implementation

### 2A — Pal Identity Contract
This slice. Freeze identity, isolation, ownership, activation gates, and rollout order. No myChat schema change.

### 2B — Persona Registry and Model Renderer
In myChat, generalize Amanda's prompt/model generation into a persona registry. Produce one generated model definition per activated Pal. Preserve Amanda as a compatibility persona. Re-read then-current myChat main first; do not branch from the discovery SHA blindly.

### 2C — Persona Memory Namespace
Using the migration ledger, evolve durable memory to profile-plus-persona ownership. Migrate Amanda's existing rows to Amanda's persona id with preservation checks and prove that cross-persona recall is impossible by default.

### 2D — Distinct Living Voices
Bind independent voice profiles and speaking behavior to each persona while preserving user-initiated microphone/playback and current authentication guarantees.

### 2E — Fitness-Pals Pal Adapter
Implement versioned same-origin persona discovery/session/turn capabilities. No browser-direct private myChat credentials. Coach fallback is non-blocking.

### 2F — Embodied Pal Selection
Bind all five canonical finalist visuals to live persona sessions, selection, animation, responsive behavior, accessibility, and production acceptance.

## Activation rule

A Pal cannot be production-active until all of the following are true:

1. canonical finalist identity exists;
2. immutable `persona_id` exists;
3. generated model definition exists;
4. personality contract exists;
5. distinct voice profile exists;
6. memory is isolated by authenticated profile and persona;
7. capability negotiation succeeds;
8. text Coach fallback remains functional;
9. required CI/deployment/production gates are terminal-green.

The cast ships as identities, not costumes.
