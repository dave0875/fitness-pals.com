import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const selector = fs.readFileSync(path.join(root, "components", "PalSelector.js"), "utf8");
const coach = fs.readFileSync(path.join(root, "pages", "coach.js"), "utf8");
const css = fs.readFileSync(path.join(root, "styles", "AthletePages.module.css"), "utf8");

const canonical = [
  ["W16", "w16-golden-glow", "Golden Glow", "w16-golden-glow-v1"],
  ["W18", "w18-radiant-wellness", "Radiant Wellness", "w18-radiant-wellness-v1"],
  ["W21", "w21-confident-coaching", "Confident Coaching", "w21-confident-coaching-v1"],
  ["W24", "w24-fresh-momentum", "Fresh Momentum", "w24-fresh-momentum-v1"],
  ["W51", "w51-tokyo-strength", "Tokyo Strength", "w51-tokyo-strength-v1"],
];

test("Embodied selector pins the exact canonical five and approved local portraits", () => {
  for (const [candidate, persona, name, voice] of canonical) {
    assert.ok(selector.includes(`candidate_id: "${candidate}"`));
    assert.ok(selector.includes(`persona_id: "${persona}"`));
    assert.ok(selector.includes(`display_name: "${name}"`));
    assert.ok(selector.includes(`voice_key: "${voice}"`));
    const image = path.join(root, "public", "pals", `${persona}.webp`);
    assert.ok(fs.existsSync(image), `missing ${persona} portrait`);
    assert.ok(fs.statSync(image).size < 25_000, `${persona} portrait exceeds budget`);
  }
  const total = canonical.reduce(
    (sum, [, persona]) => sum + fs.statSync(path.join(root, "public", "pals", `${persona}.webp`)).size,
    0
  );
  assert.ok(total < 50_000, "five-Pal portrait payload exceeds 50 KB");
  assert.match(selector, /persona_id: "w51-tokyo-strength"[\s\S]*framing: "upper-torso"/);
});

test("Discovery is server authoritative and malformed persona manifests fail closed", () => {
  assert.ok(selector.includes('authenticatedJson("/api/pals/v1/personas")'));
  assert.ok(selector.includes("discovered.size !== PAL_VISUALS.length"));
  assert.ok(selector.includes("item.candidate_id !== expected.candidate_id"));
  assert.ok(selector.includes("item.display_name !== expected.display_name"));
  assert.ok(selector.includes('typeof item.runtime_available !== "boolean"'));
  assert.ok(selector.includes('typeof item.voice_available !== "boolean"'));
  assert.ok(selector.includes("item.voice_key !== expected.voice_key"));
  assert.ok(selector.includes("onSessionChange?.(null)"));
});

test("Preview selection cannot create a Pal session and activation is explicit", () => {
  assert.ok(selector.includes("onClick={() => setSelectedId(pal.persona_id)}"));
  assert.ok(selector.includes('authenticatedJson("/api/pals/v1/sessions"'));
  assert.ok(selector.includes("json: { persona_id: selected.persona_id }"));
  assert.ok(selector.includes('data?.mode === "pal"'));
  assert.ok(selector.includes("data.active_persona_id === selected.persona_id"));
  assert.ok(selector.includes("data.speaker === selected.display_name"));
  assert.ok(selector.includes("data.voice?.voice_key === selected.voice_key"));
  assert.ok(selector.includes('typeof data.voice?.available === "boolean"'));
  assert.ok(selector.includes("disabled={!selected.runtime_available || busy}"));
  assert.ok(!selector.includes("profile_id"));
  assert.ok(!selector.includes("memory_namespace"));
  assert.ok(!selector.includes("passkey"));
});

test("Pal turn path preserves exact speaker identity and truthful Coach fallback", () => {
  assert.ok(coach.includes('authenticatedJson("/api/pals/v1/turns"'));
  assert.ok(coach.includes("session_token: palSession.session_token"));
  assert.ok(coach.includes('data?.mode === "pal"'));
  assert.ok(coach.includes("data.active_persona_id === palSession.active_persona_id"));
  assert.ok(coach.includes('data?.mode === "coach-fallback"'));
  assert.ok(coach.includes("data.coach?.thread?.id"));
  assert.ok(coach.includes('authenticatedJson("/api/chat"'));
  assert.ok(coach.includes("setPalSession(null)"));
});

test("Selector has no audio, microphone, or autoplay path", () => {
  for (const forbidden of [
    "speechSynthesis",
    "SpeechRecognition",
    "webkitSpeechRecognition",
    "getUserMedia",
    "mediaDevices",
    "autoPlay",
    "autoplay",
  ]) {
    assert.ok(!selector.includes(forbidden), `unexpected ${forbidden} in Pal selector`);
  }
});

test("Living Pal voice is explicit, exact-attributed, and never browser-authored", () => {
  assert.ok(coach.includes('authenticatedFetch("/api/pals/v1/voice"'));
  assert.ok(coach.includes("JSON.stringify({ session_token: turn.voiceSessionToken })"));
  assert.ok(coach.includes('response.headers.get("x-pal-persona-id")'));
  assert.ok(coach.includes('response.headers.get("x-pal-voice-key")'));
  assert.ok(coach.includes("new Audio(objectUrl)"));
  assert.ok(coach.includes("await audio.play()"));
  assert.ok(coach.includes("Play ${turn.speaker} voice"));
  assert.ok(coach.includes("stopPalVoice()"));
  assert.ok(!coach.includes("getUserMedia"));
  assert.ok(!coach.includes("speechSynthesis"));
  assert.ok(!coach.includes("text: turn.answer"));
  assert.ok(css.includes(".palVoiceButton:focus-visible"));
});

test("Embodied selection is keyboard-visible, responsive, and reduced-motion safe", () => {
  assert.ok(selector.includes('type="button"'));
  assert.ok(selector.includes("aria-pressed"));
  assert.ok(selector.includes('data-contract="embodied-pal-selection-v1"'));
  assert.ok(css.includes(".palCard:focus-visible"));
  assert.match(css, /@media\s*\(max-width:\s*620px\)[\s\S]*\.palStage/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.palPreviewImage/);
});
