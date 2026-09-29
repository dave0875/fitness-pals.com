# Vital Presence Phase 2E: Fitness-Pals Pal Adapter

Phase 2E adds the **same-origin Fitness-Pals bridge** between an authenticated athlete and a separately deployed myChat Pal runtime. It does not move private myChat identity or memory into Fitness-Pals, and it does not pretend the five Pals are live when the upstream runtime is absent.

## Public contract

Fitness-Pals exposes three authenticated endpoints:

- `GET /api/pals/v1/personas` — public persona discovery plus explicit runtime availability.
- `POST /api/pals/v1/sessions` — create one opaque athlete-owned adapter session for a canonical `persona_id`.
- `POST /api/pals/v1/turns` — submit one text turn through that session.
- `POST /api/pals/v1/voice` — explicitly render the exact server-bound answer for a successful Pal turn.

The canonical cast is:

| Candidate | Persona ID | Display name | Voice key |
| --- | --- | --- | --- |
| W16 | `w16-golden-glow` | Golden Glow | `w16-golden-glow-v1` |
| W18 | `w18-radiant-wellness` | Radiant Wellness | `w18-radiant-wellness-v1` |
| W21 | `w21-confident-coaching` | Confident Coaching | `w21-confident-coaching-v1` |
| W24 | `w24-fresh-momentum` | Fresh Momentum | `w24-fresh-momentum-v1` |
| W51 | `w51-tokyo-strength` | Tokyo Strength | `w51-tokyo-strength-v1` |

These values mirror the terminal-green myChat Phase 2D registry. The older Phase 2A contract remains historical evidence of what was known at that time; Phase 2E does not rewrite it retroactively.

## Identity boundary

The browser may choose a public `persona_id`, but it cannot assert a myChat profile, passkey, biometric identity, memory namespace, or voice credential. Request models reject unknown fields rather than silently ignoring them.

The adapter session token is encrypted with the existing Fitness-Pals Fernet key and binds:

- authenticated Fitness-Pals user id;
- requested `persona_id`;
- adapter mode;
- optional opaque upstream session id;
- optional durable Coach thread id.

A token presented by another Fitness-Pals user is rejected. The token is an adapter capability only. It is not a myChat login and never grants private-profile authority.

## Upstream capability negotiation

The optional upstream is configured only by server operators:

- `RUNTRAINER_PAL_ADAPTER_ENABLED`
- `RUNTRAINER_PAL_SERVICE_URL`
- `RUNTRAINER_PAL_SERVICE_TOKEN`
- `RUNTRAINER_PAL_SERVICE_ALLOWED_HOSTS`
- `RUNTRAINER_PAL_SERVICE_TIMEOUT_SECONDS`
- `RUNTRAINER_PAL_SESSION_TTL_SECONDS`

Even when enabled, the URL must use HTTP(S), contain no embedded credentials, and resolve to a hostname explicitly present in `RUNTRAINER_PAL_SERVICE_ALLOWED_HOSTS`.

Fitness-Pals expects upstream contract `mychat-pal-runtime-v1`. The upstream must advertise `session` and `turn` capabilities and may mark each canonical persona `runtime_available`. Unknown personas, malformed manifests, version drift, timeout, or transport failure degrade the bridge instead of activating a guessed runtime.

Phase 2G closes the former dark-launch boundary. The production myChat runtime now exposes `mychat-pal-runtime-v1`, and Fitness-Pals enables the adapter by default against `https://amanda.fitness-pals.com` while retaining the allow-list and optional server bearer. If the upstream contract becomes unavailable or incompatible, the adapter fails closed and Coach remains the truthful fallback.

## Coach fallback

The existing Fitness-Pals Coach remains the safety net.

If a selected Pal is unavailable, session creation returns `coach-fallback` truthfully. If an upstream Pal session fails during a turn, the same question is handed to the existing durable Coach route. The returned adapter token is rotated to retain the Coach thread id so follow-ups stay in that durable conversation.

No second coaching model, evidence pipeline, or persistence path is introduced.

## Voice boundary

The browser receives only the public persona `voice_key` and an availability signal. After a successful Pal turn, Fitness-Pals rotates the encrypted adapter session token with the exact server-produced answer. The browser cannot submit arbitrary speech text to `/voice`; it sends only that opaque token. Fitness-Pals then proxies the bound answer to myChat and validates the returned contract version, persona id, voice key, WAV type, and size before returning audio. Source voice files, provider credentials, biometric templates, upstream session ids, and private memory authority never cross the browser boundary. Voice never starts automatically and no Pal microphone UI is introduced.

## Phase 2F handoff

Phase 2F may bind the approved avatar visuals to these endpoints only after the adapter reports truthful runtime capability. The user-facing embodied selection must preserve the same fallback, accessibility, reduced-sensory, and no-fake-activation rules.
