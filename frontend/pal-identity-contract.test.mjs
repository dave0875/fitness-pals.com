import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const contract = JSON.parse(read("config/pal-personas.json"));
const doc = read("../docs/pal-identity-contract.md");

test("Pal Identity Contract preserves the approved five-finalist decision without fabricating missing identities", () => {
  assert.equal(contract.version, "pal-identity-contract-v1");
  assert.equal(contract.approvedFinalistCount, 5);
  assert.equal(contract.knownFinalists.length, 3);
  assert.deepEqual(contract.knownFinalists.map((pal) => pal.candidateId), ["W16", "W21", "W51"]);
  assert.equal(contract.knownFinalists.find((pal) => pal.candidateId === "W51").displayName, "Tokyo Strength");
  assert.equal(contract.unresolvedFinalistSlots, 2);
  assert.match(contract.unresolvedIdentityRule, /Do not invent/);
  assert.ok(contract.knownFinalists.every((pal) => pal.activationStatus !== "active"));
});

test("one persona id owns model, personality, voice, avatar, memory, and capabilities", () => {
  assert.equal(contract.personaIdentity.canonicalKey, "persona_id");
  assert.equal(contract.personaIdentity.immutableAfterActivation, true);
  assert.deepEqual(
    new Set(contract.personaIdentity.onePersonaIdBinds),
    new Set([
      "visual-avatar",
      "model-definition",
      "system-personality-contract",
      "voice-profile",
      "memory-namespace",
      "capability-manifest",
    ])
  );
  assert.match(contract.personaIdentity.modelDefinitionRequirement, /Amanda\.Modelfile/);
  assert.deepEqual(
    contract.personaIdentity.personalityRequirement,
    ["voice", "attitude", "disposition", "personality", "interaction-boundaries"]
  );
});

test("long-term memory is isolated by authenticated profile plus persona", () => {
  assert.deepEqual(contract.memory.scopeKey, ["authenticated_profile_id", "persona_id"]);
  assert.equal(contract.memory.crossPersonaRecallAllowed, false);
  assert.equal(contract.memory.anonymousPrivateMemoryAllowed, false);
  assert.equal(contract.memory.fitnessPalsCopiesPrivateMemory, false);
  assert.equal(contract.memory.migrationRequiredBeforeActivation, true);
  assert.match(contract.memory.migrationRule, /migration-ledger/);
});

test("myChat remains the private identity authority and Fitness-Pals keeps a safe fallback", () => {
  assert.equal(contract.integration.myChatRepository, "dave0875/myChat");
  assert.equal(contract.integration.browserDirectPrivateServiceAccess, false);
  assert.equal(contract.integration.copyMyChatSourceIntoFitnessPals, false);
  assert.equal(contract.integration.copyProfiles, false);
  assert.equal(contract.integration.copyMemories, false);
  assert.equal(contract.integration.copyVoiceCredentials, false);
  assert.equal(contract.integration.copyBiometricMaterial, false);
  assert.equal(contract.integration.copyPasskeys, false);
  assert.match(contract.integration.fallback, /text Coach remains usable/);
  assert.equal(contract.voice.speakerRecognitionIsAuthentication, false);
  assert.equal(contract.voice.microphoneAlwaysUserInitiated, true);
  assert.equal(contract.voice.autoplayVoice, false);
});

test("rollout separates registry, memory migration, voice, adapter, and embodied activation", () => {
  assert.deepEqual(
    contract.rollout.map((slice) => slice.slice),
    ["2A", "2B", "2C", "2D", "2E", "2F"]
  );
  assert.equal(contract.rollout.find((slice) => slice.slice === "2A").schemaChange, false);
  assert.equal(contract.rollout.find((slice) => slice.slice === "2C").schemaChange, true);
  assert.ok(contract.rollout.find((slice) => slice.slice === "2B").dependsOn.includes("myChat migration-ledger PASS"));
  assert.ok(contract.rollout.find((slice) => slice.slice === "2F").dependsOn.includes("all-five-canonical-finalist-identities"));
  assert.match(doc, /The cast ships as identities, not costumes\./);
});
