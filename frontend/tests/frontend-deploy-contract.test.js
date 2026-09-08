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

test("frontend dependency metadata is mandatory and reproducible", () => {
  const workflow = read(".github/workflows/ci-cd.yml");
  const dockerfile = read("frontend/Dockerfile");

  assert.ok(workflow.includes('frontend_root="frontend"'));
  assert.ok(workflow.includes("for manifest in package.json package-lock.json"));
  assert.ok(workflow.includes("the frontend is not buildable"));
  assert.ok(workflow.includes("overall_status=\"failed\""));
  assert.ok(workflow.includes("(cd \"$frontend_root\" && npm ci)"));
  assert.ok(!workflow.includes('for path in frontend web app ui'));
  assert.ok(!workflow.includes('install_cmd="npm install"'));
  assert.ok(dockerfile.includes("COPY package.json package-lock.json ./"));
  assert.ok(dockerfile.includes("RUN npm ci --omit=dev"));
});

test("required CI builds every deployable application image", () => {
  const workflow = read(".github/workflows/ci-cd.yml");

  assert.ok(
    workflow.includes(
      '"ci-logs/docker-build-frontend.log" -f frontend/Dockerfile frontend'
    )
  );
  assert.ok(
    workflow.includes(
      '"ci-logs/docker-build-backend.log" -f backend/Dockerfile backend'
    )
  );
  assert.ok(
    workflow.includes(
      '"ci-logs/docker-build-training-agent.log" -f services/training_agent/Dockerfile .'
    )
  );
});

test("production deploy recreates and verifies the exact frontend release", () => {
  const workflow = read(".github/workflows/ci-cd.yml");
  const productionJob = workflow.split("  deploy-prod:\n", 2)[1];

  assert.ok(workflow.includes("--force-recreate"));
  assert.ok(productionJob.includes("scripts/smoke_production.py"));
  assert.ok(productionJob.includes('--expected-release "$RUNTRAINER_RELEASE_SHA"'));
  assert.ok(!productionJob.includes("skipping release verification"));
  assert.ok(workflow.includes("RUNTRAINER_RELEASE_SHA"));
  assert.ok(workflow.includes("github.sha"));
  assert.ok(workflow.includes("expected release"));
});

test("production always reconciles and verifies the complete public journey", () => {
  const workflow = read(".github/workflows/ci-cd.yml");
  const productionJob = workflow.split("  deploy-prod:\n", 2)[1];

  for (const service of [
    "runtrainer-postgres",
    "influxdb",
    "grafana",
    "authentik-redis",
    "authentik-server",
    "authentik-worker",
    "backend",
    "worker",
    "training-agent",
    "frontend",
    "cloudflared",
    "cloudflared-loopback",
  ]) {
    assert.ok(productionJob.includes(service));
  }
  assert.ok(productionJob.includes("Reconcile complete production runtime"));
  assert.ok(productionJob.includes("Verify public production journey"));
  assert.ok(productionJob.includes("RUNTRAINER_SMOKE_AUTH_TOKEN"));
  assert.ok(!productionJob.includes("Smoke check external Cloudflare ingress"));
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

test("production reconciliation does not force-recreate stateful services", () => {
  const workflow = read(".github/workflows/ci-cd.yml");
  const productionJob = workflow.split("  deploy-prod:\n", 2)[1];

  assert.ok(productionJob.includes("up -d --remove-orphans"));
  assert.ok(!productionJob.includes("up -d --remove-orphans --force-recreate"));
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
  const devJob = workflow.split("  deploy-dev:\n", 2)[1].split("  deploy-prod:\n", 1)[0];
  const productionJob = workflow.split("  deploy-prod:\n", 2)[1];
  const manualDispatchGuard =
    'if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then';

  assert.equal(workflow.split(manualDispatchGuard).length - 1, 2);
  assert.ok(devJob.includes('echo "frontend_changed=true"'));
  for (const service of ["postgres", "influxdb", "grafana", "cloudflared"]) {
    assert.ok(devJob.includes(`echo "${service}_changed=false"`));
    assert.ok(productionJob.includes(`echo "${service}_changed=true"`));
  }
  for (const service of ["frontend", "backend", "worker", "training_agent"]) {
    assert.ok(productionJob.includes(`echo "${service}_changed=true"`));
  }
});

test("production deploy reads its overlay from the protected production secret store", () => {
  const workflow = read(".github/workflows/ci-cd.yml");
  const productionJob = workflow.split("  deploy-prod:\n", 2)[1];

  assert.ok(
    productionJob.includes(
      "OVERLAY_ENV_PATH: /home/fitness-pals/fitness-pals.com-secrets/.env.authentik-oidc"
    )
  );
  assert.ok(!productionJob.includes("/home/dbarker/fitness-pals-deploy"));
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

test("lightweight governance workflows use the self-hosted dev runner", () => {
  for (const path of [
    ".github/workflows/pr-governance.yml",
    ".github/workflows/dependabot-history.yml",
  ]) {
    const workflow = read(path);
    assert.ok(workflow.includes("runs-on: [self-hosted, dev]"));
    assert.ok(!workflow.includes("runs-on: ubuntu-latest"));
  }
});
