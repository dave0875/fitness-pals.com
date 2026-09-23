const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const nextRoot = path.join(root, ".next");
const manifestPath = path.join(nextRoot, "build-manifest.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const PERFORMANCE_BUDGETS = {
  maxRouteJsBytes: 900 * 1024,
  maxCriticalJsBytes: 2500 * 1024,
};
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

let failed = false;
const criticalFiles = new Set();

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
