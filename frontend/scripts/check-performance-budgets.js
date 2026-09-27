const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const nextRoot = path.join(root, ".next");
const manifestPath = path.join(nextRoot, "build-manifest.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const ELECTRIC_FORM = require("../config/electric-form.json");
const PERFORMANCE_BUDGETS = {
  maxRouteJsBytes: ELECTRIC_FORM.budgets.maxRouteJsBytes,
  maxCriticalJsBytes: ELECTRIC_FORM.budgets.maxCriticalJsBytes,
};
const electricFormAssetRoot = path.join(root, "public", "electric-form");
const routes = ["/today", "/coach", "/progress", "/training", "/settings", "/welcome"];

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

let failed = false;
const criticalFiles = new Set();

for (const failure of electricFormMediaFailures()) {
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
