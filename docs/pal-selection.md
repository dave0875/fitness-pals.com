# Vital Presence Phase 2F: Embodied Pal Selection

Phase 2F binds the five approved Vital Presence portraits to the authenticated Phase 2E Pal adapter without making visual selection an identity claim.

## Truth model

The selector discovers runtime state from `GET /api/pals/v1/personas`. The five canonical visual records must exactly match the server manifest before the UI treats discovery as valid. A portrait click changes only the preview. The user must explicitly choose an available Pal, and `POST /api/pals/v1/sessions` must return `mode: "pal"` for that exact persona before Fitness-Pals presents that Pal as active.

If activation or a turn returns Coach fallback, Fitness-Pals immediately removes active-Pal presentation and uses the durable Coach thread returned by the Phase 2E adapter. A malformed, incomplete, or unavailable Pal manifest fails closed to Coach.

## Approved cast

| Candidate | Persona | Portrait |
| --- | --- | --- |
| W16 | Golden Glow | `/pals/w16-golden-glow.webp` |
| W18 | Radiant Wellness | `/pals/w18-radiant-wellness.webp` |
| W21 | Confident Coaching | `/pals/w21-confident-coaching.webp` |
| W24 | Fresh Momentum | `/pals/w24-fresh-momentum.webp` |
| W51 | Tokyo Strength | `/pals/w51-tokyo-strength.webp` |

The W51 crop deliberately preserves the approved final upper-torso emphasis.

## Interaction boundary

The selector never starts speech, microphone capture, or autoplay media. Native buttons provide keyboard operation and visible focus. Continuous decorative portrait motion is disabled under `prefers-reduced-motion: reduce`. The layout collapses for narrow screens without removing Pal identity or availability status.

The browser submits only the public `persona_id` for activation and the opaque adapter `session_token` plus message for a live Pal turn. It does not claim a myChat profile, model, memory namespace, biometric identity, passkey, provider credential, or upstream session identity.

## Current production state

Until a compatible `mychat-pal-runtime-v1` service is configured, production discovery is expected to report the five Pals as preview-only. That is a successful dark launch: the approved cast is visible, their runtime status is truthful, and Coach remains fully usable.
