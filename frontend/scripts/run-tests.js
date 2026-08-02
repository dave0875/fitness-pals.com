const { spawnSync } = require("node:child_process");

const result = spawnSync(process.execPath, ["--test"], {
  stdio: "inherit",
});

process.exit(result.status ?? 1);
