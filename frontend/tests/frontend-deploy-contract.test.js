const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const repositoryRoot = path.join(__dirname, "..", "..");
const read = (relativePath) =>
  fs.readFileSync(path.join(repositoryRoot, relativePath), "utf8");

test("frontend image carries the deployment commit", () => {
  const dockerfile = read("frontend/Dockerfile");
  const compose = read("compose.yml");
  const releasePage = read("frontend/pages/deploy-version.js");

  assert.ok(dockerfile.includes("ARG RUNTRAINER_RELEASE_SHA"));
  assert.ok(dockerfile.includes("NEXT_PUBLIC_RUNTRAINER_RELEASE_SHA"));
  assert.ok(compose.includes("RUNTRAINER_RELEASE_SHA"));
  assert.ok(releasePage.includes("NEXT_PUBLIC_RUNTRAINER_RELEASE_SHA"));
});

test("production deploy recreates and verifies the exact frontend release", () => {
  const workflow = read(".github/workflows/ci-cd.yml");

  assert.ok(workflow.includes("--force-recreate"));
  assert.ok(workflow.includes("/deploy-version"));
  assert.ok(workflow.includes("RUNTRAINER_RELEASE_SHA"));
  assert.ok(workflow.includes("github.sha"));
  assert.ok(workflow.includes("expected release"));
});


test("deployment waits for frontend health and routes public traffic to it", () => {
  const workflow = read(".github/workflows/ci-cd.yml");
  const tunnel = read("cloudflare/config.yml");

  assert.ok(workflow.includes("frontend_health_deadline"));
  assert.ok(workflow.includes("Frontend did not become healthy"));
  assert.ok(tunnel.includes("path: ^/(api|auth)(/.*)?$"));
  assert.ok(tunnel.includes("service: http://backend:8000"));
  assert.ok(tunnel.includes("service: http://frontend:3000"));
});

test("infrastructure restarts do not recreate dependency containers", () => {
  const workflow = read(".github/workflows/ci-cd.yml");

  assert.ok(
    workflow.includes(
      'docker compose --env-file "$ENV_FILE" up -d --no-deps "${infra_services[@]}"'
    )
  );
});

test("frontend replacement removes only stale project frontend containers", () => {
  const workflow = read(".github/workflows/ci-cd.yml");

  assert.ok(
    workflow.includes(
      'label=com.docker.compose.project=$COMPOSE_PROJECT_NAME'
    )
  );
  assert.ok(
    workflow.includes('label=com.docker.compose.service=frontend')
  );
  assert.ok(workflow.includes('docker rm -f "${frontend_cids[@]}"'));
});

test("manual deploys target the frontend without restarting infrastructure", () => {
  const workflow = read(".github/workflows/ci-cd.yml");
  const manualDispatchGuard =
    'if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then';

  assert.equal(workflow.split(manualDispatchGuard).length - 1, 2);
  assert.equal(
    workflow.split('echo "frontend_changed=true"').length - 1,
    2
  );
  for (const service of ["postgres", "influxdb", "grafana", "cloudflared"]) {
    assert.equal(
      workflow.split(`echo "${service}_changed=false"`).length - 1,
      2
    );
  }
});

test("CI validation selects self-hosted runners without exposing prod to PRs", () => {
  const workflow = read(".github/workflows/ci-cd.yml");

  assert.ok(!workflow.includes("runs-on: ubuntu-latest"));
  assert.ok(workflow.includes("      - self-hosted"));
  assert.ok(
    workflow.includes(
      "github.event_name == 'pull_request' && 'dev' || 'prod'"
    )
  );
});
