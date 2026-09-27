# Electric Form Phase 5: Sonic Body

Sonic Body extends the Phase 0 sound primitive into a restrained interaction layer. It is intentionally smaller than a soundtrack: short synthesized cues can reinforce an athlete's explicit action, while the interface remains fully understandable in silence.

## Control contract

`frontend/lib/electricFormAudio.mjs` is the single cue-policy controller. It owns the cue palette, semantic mapping, persisted preferences, and the gate that must approve playback.

The defaults are deliberately quiet:

- sound cues are disabled by default;
- mute is available without discarding the athlete's opt-in;
- reduced-sensory mode suppresses Electric Form interface cues;
- preferences persist only in browser-local storage and do not change athlete data or backend state.

The authenticated shell exposes all three controls in a visible Sound menu. Preference hydration never creates an `AudioContext` and never plays a cue.

## Absolute no-autoplay rule

A cue is allowed only when every condition below is true:

1. the cue is known;
2. the caller marks the playback as user initiated;
3. the athlete has explicitly enabled sound;
4. mute is off;
5. reduced-sensory mode is off; and
6. the browser exposes Web Audio.

Page load, hydration, navigation completion, data arrival, refresh completion, Amanda state effects, and Coach response arrival are not playback triggers. Amanda speech remains separately explicit: the athlete must press **Read latest reply**.

## Semantic restraint

The sonic vocabulary stays tiny. Focus, confirmation, progress, and celebration tones are synthesized locally with short envelopes. Semantic names such as `amanda-listen` map into those cues so components do not invent their own sounds.

Phase 5 wires cues only into Amanda's explicit Listen, Read latest reply, and Stop voice gestures plus the Sound control's own opt-in/unmute confirmation. This keeps sound physical and attributable rather than turning ordinary navigation into a stream of chirps.

## Accessibility and truth

Sound is never the only carrier of meaning. Amanda retains visible state labels, controls, and transcript. The Sound menu always shows the current cue state in text. Reduced-sensory mode suppresses interface tones without changing training recommendations, athlete evidence, or Amanda's explicit text/voice interaction contract.

No backend, Garmin/import, authentication, athlete-data, recommendation, memory, biometric, billing, or notification behavior changes in this phase.
