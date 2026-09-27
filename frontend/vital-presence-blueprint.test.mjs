import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const contract = JSON.parse(
  fs.readFileSync(path.join(root, "config", "vital-presence.json"), "utf8")
);

test("Vital Presence declares the complete phased initiative", () => {
  assert.equal(contract.initiative, "Vital Presence");
  assert.deepEqual(
    contract.phases.map((phase) => phase.name),
    ["Vital Blueprint", "Human Heat", "Amanda Alive", "Sonic Impact", "Kinetic Cinema", "Embodied Athlete", "Living World"]
  );
  assert.equal(contract.release.onlyTerminalSuccessCounts, true);
  assert.equal(contract.release.generateNextPhasePromptOnlyAfterPass, true);
});

test("Vital Blueprint makes Human Heat concrete without weakening representation safety", () => {
  assert.match(contract.baselineGaps.humanHeat.current, /SVG/);
  assert.ok(contract.mediaDirection.subjects.includes("adult women athletes"));
  assert.ok(contract.mediaDirection.subjects.includes("adult men athletes"));
  assert.ok(contract.mediaDirection.avoid.includes("minors"));
  assert.ok(contract.mediaDirection.avoid.includes("pin-up framing"));
  assert.match(contract.phase1Acceptance.must.join(" "), /adult woman athlete/);
  assert.match(contract.phase1Acceptance.must.join(" "), /adult man athlete/);
});

test("Amanda Alive reuses myChat rather than copying private capability into Fitness Pals", () => {
  assert.equal(contract.amandaArchitecture.sourceRepository, "dave0875/myChat");
  assert.equal(contract.amandaArchitecture.integrationMode, "reuse-separate-deployment-through-adapter");
  assert.equal(contract.amandaArchitecture.copySourceIntoFitnessPals, false);
  assert.equal(contract.amandaArchitecture.replicateMyChatDatabase, false);
  assert.equal(contract.amandaArchitecture.replicateVoiceCredentials, false);
  assert.equal(contract.amandaArchitecture.replicateBiometricMaterial, false);
  assert.equal(contract.amandaArchitecture.replicatePrivateMemories, false);
  assert.equal(contract.amandaArchitecture.browserDirectPrivateServiceAccess, false);
  assert.match(contract.amandaArchitecture.fallback, /text Coach remains usable/);
});

test("Vital Presence keeps sound, motion, accessibility, and performance bounded", () => {
  assert.equal(contract.sound.defaultEnabled, false);
  assert.equal(contract.sound.autoplay, false);
  assert.equal(contract.sound.userInitiatedPlaybackRequired, true);
  assert.equal(contract.motion.reducedMotionEquivalentRequired, true);
  assert.equal(contract.accessibility.wcagTarget, "2.2 AA");
  assert.equal(contract.accessibility.minimumInteractiveTargetPx, 44);
  assert.ok(contract.budgets.maxVitalPresenceMediaTotalBytes <= 1572864);
  assert.ok(contract.budgets.productionTargets.lcpP75Ms <= 2500);
  assert.ok(contract.budgets.productionTargets.inpP75Ms <= 200);
  assert.ok(contract.budgets.productionTargets.clsP75 <= 0.1);
});

test("Phase 0 preserves athlete truth and defers product behavior changes", () => {
  assert.equal(contract.truthAndSafety.preserveAthleteEvidenceProvenance, true);
  assert.equal(contract.truthAndSafety.preserveUncertainty, true);
  assert.equal(contract.truthAndSafety.noFabricatedMetrics, true);
  assert.equal(contract.truthAndSafety.noRecommendationSemanticsChangeInPhase0, true);
  assert.ok(contract.phase1Acceptance.mustNot.includes("implement myChat integration"));
});
