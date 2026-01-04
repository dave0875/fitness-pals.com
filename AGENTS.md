# AGENTS.md

## Trunk-Based Development + CI/CD Guardrails

`main` is the trunk. Keep it deployable at all times.

This file defines the expected workflow for humans and AI agents working in this repository.

---

## 1) Trunk-Based Workflow

- Integrate to `main` frequently (hours → a couple days, not weeks).
- Prefer short-lived branches and PRs; avoid long-lived branches.
- Use feature flags / dark launches when work can’t be completed in one merge.
- Keep history linear (squash or rebase merges; avoid merge commits).

### Branch naming (recommended)

- `feat/<topic>`
- `fix/<topic>`
- `chore/<topic>`
- `docs/<topic>`
- `dependabot/...` (allowed)

---

## 2) Keep Changes Short and Feature-Specific

- One PR = one feature/fix. Avoid “drive-by refactors”.
- Split large work into a series of safe, shippable PRs.
- Prefer “thin slices”: wire one vertical path end-to-end, then iterate.
- Include a rollback plan for changes that affect deploy/infra or user-facing flows.

---

## 3) PR Expectations

- CI must pass before merging.
- PR description should include:
  - **What/Why** (1–3 sentences)
  - **Test plan** (what you ran or why not)
  - **Risk / rollback** (what could break + how to revert)
- If CI fails: fix-forward on the same PR until green.

---

## 4) CI/CD Requirements

- PRs run CI and upload logs as a GitHub Actions artifact.
- CI posts a standardized summary comment to the PR (pass or fail) linking to the artifact.
- Deployments happen only from `main` after CI passes.

Artifact naming:

- PR runs: `ci-logs-pr-<pr-number>-run-<run-id>`
- Non-PR runs: `ci-logs-run-<run-id>`

Do not paste raw logs into PR comments; always link to the artifact.

---

## 5) Issues, Projects, Tags

- Issues/projects are optional and can be used when helpful, but they are not required for every change.
- Tags are optional. If you create a release tag, use either SemVer (recommended) like `v1.2.3` or a date tag like `vYYYYMMDD-<topic>`, and use an annotated tag message that explains what shipped.
