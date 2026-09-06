const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const configPath = path.join(__dirname, "..", "next.config.js");

function loadConfig(backendOrigin) {
  const previousOrigin = process.env.RUNTRAINER_BACKEND_ORIGIN;
  if (backendOrigin === undefined) {
    delete process.env.RUNTRAINER_BACKEND_ORIGIN;
  } else {
    process.env.RUNTRAINER_BACKEND_ORIGIN = backendOrigin;
  }
  delete require.cache[require.resolve(configPath)];
  const config = require(configPath);
  if (previousOrigin === undefined) {
    delete process.env.RUNTRAINER_BACKEND_ORIGIN;
  } else {
    process.env.RUNTRAINER_BACKEND_ORIGIN = previousOrigin;
  }
  return config;
}

test("frontend proxies API and auth routes to the Compose backend by default", async () => {
  const config = loadConfig();

  assert.deepEqual(await config.rewrites(), [
    {
      source: "/api/:path*",
      destination: "http://backend:8000/api/:path*",
    },
    {
      source: "/auth/:path*",
      destination: "http://backend:8000/auth/:path*",
    },
  ]);
});

test("frontend proxy accepts an explicit backend origin", async () => {
  const config = loadConfig("http://backend.internal:8080/");

  assert.deepEqual(await config.rewrites(), [
    {
      source: "/api/:path*",
      destination: "http://backend.internal:8080/api/:path*",
    },
    {
      source: "/auth/:path*",
      destination: "http://backend.internal:8080/auth/:path*",
    },
  ]);
});
