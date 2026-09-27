import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.dirname(new URL(import.meta.url).pathname);
const coach = fs.readFileSync(path.join(root, "pages", "coach.js"), "utf8");
const amanda = fs.readFileSync(path.join(root, "components", "AmandaPresence.js"), "utf8");
const css = fs.readFileSync(path.join(root, "styles", "AthletePages.module.css"), "utf8");

test("Amanda Presence keeps the durable Coach and Athlete Orbit contracts", () => {
  assert.match(coach, /authenticatedJson\("\/api\/chat"/);
  assert.match(coach, /authenticatedJson\("\/api\/chat\/threads"/);
  assert.match(coach, /authenticatedJson\("\/api\/intelligence"/);
  assert.match(coach, /AthleteOrbitStory/);
  assert.match(coach, /retry_turn_id/);
  assert.match(coach, /authenticatedJson\(action\.href/);
  assert.match(coach, /variant="electric"/);
  assert.match(coach, /contentClassName=\{styles\.electricCoach\}/);
});

test("Amanda voice is progressive enhancement and never autoplays", () => {
  assert.match(amanda, /window\.SpeechRecognition \|\| window\.webkitSpeechRecognition/);
  assert.match(amanda, /window\.speechSynthesis/);
  assert.match(amanda, /onClick=\{startListening\}/);
  assert.match(amanda, /onClick=\{speakLatest\}/);
  assert.match(amanda, /recognition\.start\(\)/);
  assert.match(amanda, /speechSynthesis\.speak\(utterance\)/);
  assert.match(amanda, /Voice never autoplays/);
  assert.doesNotMatch(amanda, /getUserMedia/);
  assert.doesNotMatch(amanda, /MediaRecorder/);
  assert.doesNotMatch(coach, /speechSynthesis\.speak/);
});

test("Amanda exposes visible states, transcript, stop and barge-in controls", () => {
  for (const state of ["ambient", "listening", "thinking", "speaking", "unavailable"]) {
    assert.match(amanda, new RegExp(state));
  }
  assert.match(amanda, /Voice transcript/);
  assert.match(amanda, /Stop voice/);
  assert.match(amanda, /recognitionRef\.current\?\.abort/);
  assert.match(amanda, /speechSynthesis\?\.cancel/);
  assert.match(amanda, /Starting it also barges into local speech/);
});

test("Amanda Presence preserves accessibility and reduced-motion boundaries", () => {
  assert.match(amanda, /aria-live="polite"/);
  assert.match(amanda, /aria-label="Amanda voice controls"/);
  assert.match(css, /\.amandaVoiceControls button[\s\S]*min-height: 44px/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.amandaPortraitGlow/);
  assert.match(css, /animation: none !important/);
});
