const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const privacySource = fs.readFileSync(
  path.join(__dirname, "..", "pages", "privacy.js"),
  "utf8"
);
const homepageSource = fs.readFileSync(
  path.join(__dirname, "..", "pages", "index.js"),
  "utf8"
);

test("privacy policy is a public standalone pages-router route", () => {
  assert.match(privacySource, /export default function PrivacyPolicy/);
  assert.doesNotMatch(privacySource, /AuthenticatedShell/);
  assert.doesNotMatch(privacySource, /authenticatedFetch|authenticatedJson|useRouter/);
  assert.doesNotMatch(privacySource, /\/auth\/login|\/welcome/);
});

test("privacy policy exposes required Garmin developer application identity", () => {
  assert.match(privacySource, /david\.barker@fitness-pals\.com/);
  assert.match(privacySource, /https:\/\/fitness-pals\.com\/privacy/);
  assert.match(privacySource, /rel="canonical"/);
  assert.match(privacySource, /Privacy Policy/);
});

test("privacy policy covers core data-handling topics without claiming current official Garmin approval", () => {
  assert.match(privacySource, /does\s+<strong>not sell your personal fitness or wellness data<\/strong>/i);
  assert.match(privacySource, /Disconnecting a provider/i);
  assert.match(privacySource, /Garmin archive import is separate from Garmin's official developer APIs/i);
  assert.match(
    privacySource,
    /used\s+only\s+when\s+Fitness Pals\s+has\s+the required Garmin developer\s+approval/i
  );
  assert.match(privacySource, /read-only Drive access/i);
});

test("homepage exposes a discoverable public privacy-policy link", () => {
  assert.match(homepageSource, /href="\/privacy"/);
  assert.match(homepageSource, />\s*Privacy Policy\s*</);
});
