const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const nextRoot = path.join(root, ".next");
const manifestPath = path.join(nextRoot, "build-manifest.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const ELECTRIC_FORM = require("../config/electric-form.json");
const VITAL_PRESENCE = require("../config/vital-presence.json");
const HUMAN_HEAT = require("../config/human-heat-media.json");
const PERFORMANCE_BUDGETS = {
  maxRouteJsBytes: ELECTRIC_FORM.budgets.maxRouteJsBytes,
  maxCriticalJsBytes: ELECTRIC_FORM.budgets.maxCriticalJsBytes,
};
const electricFormAssetRoot = path.join(root, "public", "electric-form");
const routes = ["/", "/today", "/coach", "/progress", "/training", "/settings", "/welcome"];

function routeFiles(route) {
  return [...new Set([...(manifest.pages["/_app"] || []), ...(manifest.pages[route] || [])])]
    .filter((file) => file.endsWith(".js"));
}

function bytesFor(files) {
  return files.reduce((total, file) => {
    const filePath = path.join(nextRoot, file);
    if (!fs.existsSync(filePath)) {
      throw new Error(`Missing built asset ${file} referenced by build-manifest.json`);
    }
    return total + fs.statSync(filePath).size;
  }, 0);
}

function filesUnder(directory) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(entryPath) : [entryPath];
  });
}

function electricFormMediaFailures() {
  const failures = [];
  const files = filesUnder(electricFormAssetRoot);
  let totalBytes = 0;

  for (const file of files) {
    const bytes = fs.statSync(file).size;
    totalBytes += bytes;
    const relative = path.relative(electricFormAssetRoot, file);
    const isSound = /\.(mp3|wav|ogg|m4a|aac)$/i.test(file);
    const isImage = /\.(avif|webp|png|jpe?g)$/i.test(file);

    if (isSound && bytes > ELECTRIC_FORM.budgets.maxSoundCueBytes) {
      failures.push(
        `Electric Form sound ${relative}: ${bytes} > ${ELECTRIC_FORM.budgets.maxSoundCueBytes} bytes`
      );
    }

    if (isImage) {
      const limit = /hero/i.test(path.basename(file))
        ? ELECTRIC_FORM.budgets.maxHeroImageBytes
        : ELECTRIC_FORM.budgets.maxSupportingImageBytes;
      if (bytes > limit) {
        failures.push(`Electric Form image ${relative}: ${bytes} > ${limit} bytes`);
      }
    }
  }

  if (totalBytes > ELECTRIC_FORM.budgets.maxElectricFormMediaTotalBytes) {
    failures.push(
      `Electric Form media total: ${totalBytes} > ${ELECTRIC_FORM.budgets.maxElectricFormMediaTotalBytes} bytes`
    );
  }

  console.log(`PERF Electric Form media: ${totalBytes} bytes across ${files.length} files`);
  return failures;
}


function humanHeatMediaFailures() {
  const failures = [];
  const roles = new Set(HUMAN_HEAT.assets.map((asset) => asset.role));
  const requiredRoles = HUMAN_HEAT.representation.required || [];
  let transferEnvelope = 0;

  for (const role of requiredRoles) {
    if (!roles.has(role)) failures.push(`Human Heat is missing required representation: ${role}`);
  }

  for (const asset of HUMAN_HEAT.assets) {
    const limit = asset.budgetClass === "hero"
      ? VITAL_PRESENCE.budgets.maxHeroImageBytes
      : VITAL_PRESENCE.budgets.maxSupportingImageBytes;
    transferEnvelope += asset.maxBytes;

    if (asset.maxBytes > limit) {
      failures.push(`Human Heat ${asset.id} transfer envelope: ${asset.maxBytes} > ${limit} bytes`);
    }
    if (asset.license !== HUMAN_HEAT.license) {
      failures.push(`Human Heat ${asset.id} license is not declared consistently`);
    }

    for (const [name, variant] of Object.entries(asset.variants)) {
      let parsed;
      try {
        parsed = new URL(variant.src);
      } catch (_error) {
        failures.push(`Human Heat ${asset.id}/${name} has an invalid URL`);
        continue;
      }
      const width = Number(parsed.searchParams.get("w"));
      const height = Number(parsed.searchParams.get("h"));
      const quality = Number(parsed.searchParams.get("q"));
      if (parsed.origin !== HUMAN_HEAT.remoteOrigin) {
        failures.push(`Human Heat ${asset.id}/${name} uses unexpected origin ${parsed.origin}`);
      }
      if (variant.format !== "webp" || parsed.searchParams.get("fm") !== "webp") {
        failures.push(`Human Heat ${asset.id}/${name} must request WebP`);
      }
      if (width !== variant.width || height !== variant.height) {
        failures.push(`Human Heat ${asset.id}/${name} dimensions drifted from its manifest`);
      }
      if (!Number.isFinite(quality) || quality > asset.maxQuality) {
        failures.push(`Human Heat ${asset.id}/${name} quality exceeds its declared ceiling`);
      }
    }
  }

  if (transferEnvelope > VITAL_PRESENCE.budgets.maxVitalPresenceMediaTotalBytes) {
    failures.push(
      `Human Heat transfer envelope: ${transferEnvelope} > ${VITAL_PRESENCE.budgets.maxVitalPresenceMediaTotalBytes} bytes`
    );
  }
  if (HUMAN_HEAT.playback.autoplayAudio || HUMAN_HEAT.playback.autoplayVideo) {
    failures.push("Human Heat must not autoplay audio or video");
  }

  console.log(
    `PERF Human Heat media envelope: ${transferEnvelope} bytes across ${HUMAN_HEAT.assets.length} assets`
  );
  return failures;
}

let failed = false;
const criticalFiles = new Set();

for (const failure of electricFormMediaFailures()) {
  console.error(`PERF FAIL ${failure}`);
  failed = true;
}

for (const failure of humanHeatMediaFailures()) {
  console.error(`PERF FAIL ${failure}`);
  failed = true;
}

for (const route of routes) {
  const files = routeFiles(route);
  if (!files.length) {
    console.error(`PERF FAIL ${route}: no JavaScript assets in build manifest`);
    failed = true;
    continue;
  }
  files.forEach((file) => criticalFiles.add(file));
  const bytes = bytesFor(files);
  console.log(`PERF ${route}: ${bytes} bytes`);
  if (bytes > PERFORMANCE_BUDGETS.maxRouteJsBytes) {
    console.error(
      `PERF FAIL ${route}: ${bytes} > ${PERFORMANCE_BUDGETS.maxRouteJsBytes} byte route budget`
    );
    failed = true;
  }
}

const totalBytes = bytesFor([...criticalFiles]);
console.log(`PERF critical unique JS: ${totalBytes} bytes`);
if (totalBytes > PERFORMANCE_BUDGETS.maxCriticalJsBytes) {
  console.error(
    `PERF FAIL critical JS: ${totalBytes} > ${PERFORMANCE_BUDGETS.maxCriticalJsBytes} byte budget`
  );
  failed = true;
}

if (failed) process.exit(1);
