# Vital Presence Phase 0: Vital Blueprint

Vital Presence begins where Electric Form ended. Electric Form successfully made Fitness Pals visually coherent, dark, tactile, accessible, and truthful. The remaining gap is not another token pass. It is **presence**: human bodies in motion, a coach that feels genuinely alive, sound with physical character, and motion/media choreography strong enough to make the product feel inhabited rather than decorated.

Phase 0 defines those outcomes as contracts. It deliberately does not ship the new media or service integration yet.

## Baseline: what is still missing

### 1. Human heat is still an illustration, not a person
The current proof point relies on `frontend/public/electric-form/electric-entry-athletes.svg`, including reuse on Journey/Progress. It is lightweight and safe, but it cannot deliver the requested feeling of exceptional adult male and female athletic form, sweat, breath, muscle under effort, or cinematic light.

**Target:** real-feeling cinematic adult athletes in credible athletic action. Generated or commissioned media is acceptable when it follows the art direction and representation contract. The work must stay athlete-first rather than pin-up-like.

### 2. Amanda is present, but not yet alive
Fitness Pals currently renders Amanda locally and uses browser-native speech recognition/synthesis as progressive enhancement. That keeps the page functional, but it is not the richer Amanda system now being built in `dave0875/myChat`.

**Target architecture:** reuse myChat as a separately deployed capability. Do not fork or copy its source, databases, user profiles, memories, voice credentials, biometric material, or authentication model into Fitness Pals.

The intended path is:

`Fitness-Pals authenticated UI → same-origin Fitness-Pals Amanda adapter → separately deployed myChat service`

The adapter owns product-specific authorization, capability negotiation, timeout/circuit-breaker behavior, and translation into Fitness-Pals UI states. myChat remains the authority for its own private profile, voice-authentication, conversation-memory, and live-voice contracts.

A Fitness-Pals login must never silently become a myChat biometric credential. Association must be explicit, server-mediated, least-privilege, revocable, and auditable.

Most importantly, **Amanda enhancement may fail without Coach failing**. If myChat is unavailable, voice authentication cannot run, or private profile access is locked, the existing Fitness-Pals text Coach stays usable. Amanda visibly degrades instead of holding the page hostage.

### 3. Sonic Body is safe, but too synthetic
The current oscillator cues proved the opt-in/silent-by-default safety model. They do not yet create a physical, premium sound world.

**Target:** short designed cues with material character: breath, impact, tension, release, acceleration, contact, or stadium-scale space, used sparingly and only after explicit user actions. Silence remains the default. No page-load, data-arrival, navigation-completion, or surprise Coach-response audio.

### 4. Motion is polished UI motion, not kinetic storytelling
Electric Form correctly constrained motion to meaningful transform/opacity behavior. Vital Presence should keep that discipline while moving from isolated fades to scene choreography: entry, continuity, progress, effort, and earned celebration.

Motion can intensify emotion, but it cannot carry unique meaning. Reduced-motion mode must preserve the full information architecture and interaction sequence.

### 5. Composition still repeats the same visual sentence
Dark cards, borders, labels, and evidence panels are coherent, but repetition lowers contrast between ordinary state and emotionally important state.

Vital Presence should deliberately alternate:
- full-bleed or edge-to-edge human media;
- evidence-dense athlete UI;
- open negative space;
- oversized editorial typography;
- focused primary action;
- quiet utility regions.

The goal is rhythm, not more decoration.

## Media art direction

The visual world is adult athletic performance: women and men in believable motion, sculptural light, sweat, breath, speed, strength, recovery tension, confidence, and real effort.

Required:
- intentional desktop and mobile crops;
- planned negative space for copy;
- meaningful alt text;
- believable movement and anatomy;
- representation of both adult women and adult men;
- data and training purpose remain primary.

Do not use minors, body-shaming, manipulated before/after stories, medical promises, pin-up framing, gratuitous nudity, or sexualized camera framing disconnected from sport.

## Amanda integration contract

Phase 2, **Amanda Alive**, owns implementation. Phase 0 fixes the rules now:

1. Reuse the separate `dave0875/myChat` deployment. Do not vendor or clone it into Fitness Pals.
2. Browser code does not receive direct access to myChat private-service credentials.
3. Fitness Pals speaks to a same-origin adapter with a minimal, versioned capability contract.
4. myChat continues to own profile/voice/memory isolation and biometric authentication.
5. Fitness Pals owns its authenticated athlete context and chooses what minimum context may be sent for a coaching turn.
6. Private profile or voice-auth failure is a degraded Amanda state, not a lockout of Fitness-Pals Coach.
7. Microphone and voice playback are always explicit athlete gestures; transcript/state remains visible; stop/barge-in remains immediate.

Phase 2 must begin with protocol discovery against the then-current myChat main branch. This blueprint defines the boundary, not a frozen endpoint guessed in advance.

## Performance budget

Vital Presence inherits Electric Form's route and asset discipline. The machine-readable contract keeps the existing route JS, hero/supporting image, and sound-cue limits and raises the initiative-level total media ceiling only to **1.5 MiB**, which is still a ceiling rather than a target.

Production experience targets:
- LCP p75 ≤ 2.5 s;
- INP p75 ≤ 200 ms;
- CLS p75 ≤ 0.10;
- WCAG 2.2 AA;
- 44 px minimum interactive targets;
- visible keyboard focus;
- equivalent experience for reduced-motion and reduced-sensory preferences.

No autoplay background video is required by this initiative. A later phase may only introduce video if it beats a still-image alternative in measured experience without breaking these budgets.

## Truth, privacy, and resilience

Vital Presence changes how the product feels, not what athlete evidence means. Athlete Orbit provenance, uncertainty, unknown/stale/partial states, Today semantics, activity facts, and coaching recommendation boundaries remain authoritative.

Media must never imply a measured state the system does not have. Amanda must never impersonate a readiness measurement. Sound must never become the only indication of success/failure. A myChat outage must not remove the existing text coaching path.

## Phase sequence

1. **Vital Blueprint**: contracts, boundaries, budgets, acceptance criteria.
2. **Human Heat**: replace abstract runner art with cinematic adult-athlete media.
3. **Amanda Alive**: service-backed Amanda reuse through the adapter boundary.
4. **Sonic Impact**: designed physical sound language.
5. **Kinetic Cinema**: scene choreography and motion continuity.
6. **Embodied Athlete**: carry human presence into authenticated athlete/history surfaces.
7. **Living World**: product-wide convergence, resilience, performance, accessibility, and production proof.

## Phase 1 handoff: Human Heat

Human Heat is a deliberately narrow visual proof point. It must replace the landing page's abstract primary athlete SVG with cinematic adult-athlete imagery that includes both an adult woman and an adult man across the primary composition, with art-directed desktop/mobile crops and copy-safe negative space.

It must preserve:
- the current authentication path;
- trust/proof hierarchy;
- Amanda cue without implementing myChat yet;
- Electric Form truth/accessibility/sound rules;
- current backend, Garmin/import, athlete-data, Coach, and recommendation semantics.

It must not ship autoplay audio or autoplay background video.

## Phase 0 PASS rule

Phase 0 is PASS only after:
1. Issue #291 is governed in the canonical Project.
2. The branch is based on the verified Electric Form closing main SHA.
3. Contract tests and repository CI are terminal green on the PR head.
4. The PR is squash-merged.
5. Merge-triggered Dev, Prod, and production acceptance are terminal green.
6. The next standalone super prompt for **Phase 1: Human Heat** is generated with exact durable handoff identifiers and lessons learned.

Only terminal success counts.
