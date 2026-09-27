# Electric Form foundation

Electric Form is the Fitness Pals presentation system for athletic aspiration. The target feeling is magnetic and physically alive: elite training, sculptural light, speed, strength, sweat, control, and confidence. It should feel sensual through athletic form and movement without becoming explicit, objectifying, or disconnected from the athlete's actual work.

Phase 0 establishes the grammar. It does **not** perform the full redesign.

## Visual grammar

The canonical values live in `frontend/styles/electric-form.css` and the machine-readable contract in `frontend/config/electric-form.json`.

Use the Electric Form tokens instead of inventing page-local versions of core ink, canvas, surface, line, primary, focus, radius, shadow, or motion values. Phase 1 may extend the palette when a real proof point demonstrates the need, but should not fork it casually.

The new electric and heat accents are reserved for high-energy moments and imagery treatment. They are not replacements for semantic success, warning, or danger colors.

## Imagery contract

Future photography or generated imagery should evoke exceptional male and female athletic form through movement, posture, lighting, texture, and real exertion. Favor editorial crops, negative space for readable copy, believable musculature, sweat, breath, stride, and strength. Mixed-athlete scenes should feel like one performance world rather than a catalog.

Do not use body-shaming, deceptive before/after framing, implied medical guarantees, pin-up composition, gratuitous nudity, or imagery that makes the athlete data feel secondary.

Phase 1 owns the first cinematic proof point. Do not propagate a photography treatment across the product until that proof point is reviewed in real responsive layouts.

## Amanda contract

Amanda is a coach presence, not decoration.

- **Ambient:** a low-intensity visual signature that can orient or reassure without competing with athlete data.
- **Coach:** a clearly attributable presence when coaching interpretation or conversation is active.
- **Celebration:** a brief, earned escalation after a meaningful athlete action or milestone.

Amanda must never block navigation, obscure evidence, or impersonate measured athlete state. Her presentation should be warm, assured, athletic, and editorial. Voice is never autoplayed.

## Motion contract

Motion should explain hierarchy, continuity, progress, or earned celebration. Prefer transform and opacity so animation stays compositor-friendly. Decorative motion cannot be the only carrier of meaning.

`prefers-reduced-motion: reduce` collapses Electric Form durations to effectively immediate transitions. Every future animation must remain understandable in that mode.

## Sonic contract

Sound is silent by default. There is no page-load sound and no surprise voice.

A cue may play only after:
1. the athlete explicitly enables Electric Form sound; and
2. the playback call is tied to a user-initiated interaction.

Every sonic cue requires a visible equivalent. The primitive in `frontend/lib/electricFormAudio.mjs` intentionally refuses playback unless both conditions are true.

## Performance and accessibility budgets

The machine-readable limits live in `frontend/config/electric-form.json` and are enforced by the existing performance-budget script for Electric Form media under `frontend/public/electric-form/`.

Budgets include route JavaScript, hero/supporting images, individual sound cues, and the total Electric Form media payload. Prefer AVIF/WebP and responsive delivery. Do not make autoplay video part of the default proof point.

Interactive targets remain at least 44px. Normal text targets WCAG AA contrast. Focus indicators must stay conspicuous against both quiet and cinematic surfaces.

## Phase boundary

Phase 0 is complete only when the foundation is tested, merged, deployed, and production acceptance is green. Phase 1 should then build one end-to-end cinematic proof point using this grammar, including the first real athletic imagery treatment and Amanda integration, before the look is propagated elsewhere.
