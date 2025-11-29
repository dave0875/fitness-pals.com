# **AGENTS.md**

### *Trunk-Based Development + SUPER PROMPT Governance Model*

> **Purpose:**
> This document defines the required workflow for all contributors—humans and AI agents—to ensure the repository remains **stable, traceable, auditable, incrementally improving, and operationally safe**.

This document is binding.

---

# 🔒 **1. Core Principles**

## **1.1 Trunk-Based Development**

* The repository uses a **single protected trunk branch: `main`**.
* All work occurs in **short-lived feature branches** branched from `main`, named `feature/<issue-number>-<kebab-topic>` (Issue ID required).
* All PRs target `main`.
* There is no `develop` branch or long-lived integration branches.

---

## **1.2 Every Change Begins with a SUPER PROMPT**

Before ANY code is written:

A **SUPER PROMPT** must be created.
A SUPER PROMPT:

* Defines one atomic increment of work
* Is limited to **what can be completed in one working day or less**
* Includes:

  * Scope of change
  * Expected affected files
  * Tests required
  * CI expectations
  * Acceptance criteria
  * Risk considerations
  * Definition of Done

No work is permitted to start until the SUPER PROMPT exists.

---

## **1.3 SUPER PROMPT → GitHub Issue → GitHub Project**

Every SUPER PROMPT is converted into a **GitHub Issue**.

Required:

1. The Issue MUST contain the full SUPER PROMPT text verbatim.
2. The Issue MUST belong to a **GitHub Project** representing the larger initiative.
3. If no relevant Project exists, a **human must create one**, then add the Issue to it.

Work cannot begin until:

* The SUPER PROMPT exists,
* The Issue exists,
* The Issue is in a Project.

---

## **1.4 Mandatory Traceability (Commits, PRs, Tags)**

Every output of this workflow MUST reference the associated Issue:

* **Branch name**
* **Commits**
* **PR title and description**
* **Annotated tags**

### Commit message format example:

```
Issue #42: Implement RR parsing logic
```

### Tag name and message examples:

```
Tag name: v20251201-fit-rr-issue-42
Tag message: Issue #42: Implement RR parsing logic and export readiness data
```

This ensures end-to-end traceability and auditability.

---

## **1.5 Issue Lifecycle**

A SUPER PROMPT Issue remains open until:

1. The PR has merged into `main`
2. CI passes *on main*
3. An annotated tag referencing the Issue is created
4. All CI logs (success + failure) are attached to the Issue

Only then is the Issue moved to **Done**.

---

## **1.6 CI Logs MUST Be Standardized and Recorded in the Issue (Revised)**

Every PR triggers one or more CI workflows.
**Each workflow execution (pass or fail) MUST produce logs stored in a standardized location and format and linked into the Issue via a structured Issue comment.**

### **1.6.1 Required Log Storage Format**

All CI logs MUST be stored using these rules:

1. **Raw logs MUST be uploaded as GitHub Actions Artifacts**

   * Artifact name format:

     ```
     ci-logs-issue-<issue-number>-run-<run-id>
     ```
   * Contents:

     * `backend-test.log`
     * `backend-lint.log`
     * `backend-typecheck.log`
     * `frontend-build.log`
     * `frontend-test.log`
     * `frontend-lint.log`
     * `docker-build.log` (if applicable)
     * `summary.json` (structured metadata: passed/failed/time/checklist)

2. **Artifacts must be retained for at least 30 days**
   (GitHub default is 90 days — do not override to lower).

3. **Logs MUST NOT be pasted directly in-line** into the Issue.
   Only the structured comment (below) is allowed.

4. If a scope does not run (e.g., no frontend changes), omit the corresponding log file and record `"<scope>_*": "not_run"` in `summary.json` (e.g., `frontend_build: "not_run"`).

---

### **1.6.2 Required Issue Comment Format**

For each CI run (pass or fail), a comment MUST be posted to the Issue using this exact template:

```
### CI Run Summary
**Issue:** #<issue-number>  
**PR:** <link-to-pr>  
**Run:** <link-to-ci-run>  
**Status:** PASSED | FAILED  
**Timestamp:** <CI start timestamp>

### Checks
- Backend Tests: PASS | FAIL
- Backend Lint: PASS | FAIL
- Backend Typecheck: PASS | FAIL
- Frontend Build: PASS | FAIL
- Frontend Tests: PASS | FAIL
- Frontend Lint: PASS | FAIL
- Docker Build: PASS | FAIL

### Artifact
Logs and details are available in the CI artifact:
**ci-logs-issue-<issue-number>-run-<run-id>**

(Do not paste logs directly into the Issue; always refer to artifacts)
```

This ensures Issues remain readable, while preserving deep-dive logs when needed.

If a check did not run, mark it as `N/A` in the comment and ensure the matching entry in `summary.json` is `"not_run"`.

---

### **1.6.3 Required Automation Path**

You MUST use one of the following methods to post CI results:

#### **Preferred (Automatic):**

A GitHub Actions workflow posts comments automatically using:

* `actions/upload-artifact`
* `actions/github-script`
* GitHub REST API (`issues.createComment`)

**Agents must not manually paste logs.**
Humans may trigger a re-run but logs must still be posted via automation.

#### **Alternate (Manual Backup):**

If automation is unavailable:

* Contributor must manually upload logs as an Artifact
* Contributor must manually generate the Issue comment using the template above

But **manual logs pasted inline are forbidden.**

---

### **1.6.4 Logging Requirements**

Each CI execution must include:

* Raw output logs for each job
* `summary.json` containing:

  ```json
  {
    "issue": 42,
    "pr": 128,
    "run_id": 123456789,
    "status": "failed",
    "checks": {
      "backend_tests": "failed",
      "backend_lint": "passed",
      "backend_typecheck": "passed",
      "frontend_build": "passed",
      "frontend_tests": "failed",
      "frontend_lint": "passed",
      "docker_build": "passed"
    },
    "timestamp": "2025-12-01T14:32:55Z"
  }
  ```

---

### **1.6.5 Why This Standard Exists**

This ensures that:

* Issues remain readable and organized
* All CI logs are machine-readable for retrospectives
* Agents can analyze past failures automatically
* Patterns of repeated failure can inform future AGENTS.md refinements
* Historical artifacts support audits and debugging
* Multi-agent orchestration remains safe and traceable

---

## **1.7 Required Mechanical Enforcement (Commit, Tag, Branch, PR Validation)**

To ensure the mandatory traceability between SUPER PROMPT Issues, commits, tags, and PRs, the following protections and automated checks are REQUIRED.

These protections must be enabled at the repository level — **this is not optional.**
Agents and humans MUST rely on these protections.

---

## **1.7.1 Required Branch Protection Rules**

### The `main` branch MUST be protected with:

1. **Require status checks to pass before merging**

   * All CI workflows
   * Enforced and blocking

2. **Require pull request reviews before merging**

   * At least 1 human reviewer
   * AI agents cannot self-approve

3. **Require signed commits** (optional but recommended)

4. **Require linear history**

   * Prevent merge commits; allow rebase-and-merge or squash

5. **Dismiss stale reviews when new commits are pushed**

6. **Do not allow direct pushes to `main`**

---

## **1.7.2 Required Branch Naming Convention (Enforced by Regex)**

All feature and hotfix branches MUST follow this exact format:

```
feature/<issue-number>-<kebab-topic>
hotfix/<issue-number>-<kebab-topic>
```

### Required GitHub branch name pattern (RegEx):

```
^(feature|hotfix)\/[0-9]+-[a-z0-9\-]+$
```

This ensures the Issue number is mechanically extractable for CI.

GitHub branch protection MUST enforce this pattern.

---

## **1.7.3 Required Commit Message Format (Enforced by GitHub Action + server-side hooks)**

Every commit MUST reference the Issue, using:

```
Issue #<issue-number>: <description>
```

### Required commit regex:

```
^Issue #[0-9]+: .+
```

This MUST be enforced by:

* A GitHub Action that **fails the PR** if any commit does not match
* (Optional but recommended) a server-side `pre-receive` hook for GitHub Enterprise environments

---

## **1.7.4 Required Tag Format (Final, Unambiguous, Enforced)**

Every merged change MUST be tagged using the following rules:

### **Tag Name Format (Required, Enforced by Regex)**

```
vYYYYMMDD-<kebab-topic>-issue-<issue-number>
```

Examples:

```
v20251201-fit-rr-issue-42
v20260115-frontend-cors-update-issue-87
v20250203-fix-docker-build-issue-5
```

### **Required Tag Message Format**

The annotated tag message MUST begin with:

```
Issue #<issue-number>: <short description>
```

The description must briefly state how the tagged release satisfies the referenced Issue.

Example:

```
Issue #42: Implement RR FIT parsing and update tests
Merged to main with CI passing. See Issue #42 for full context.
```

### **Both Tag Name AND Tag Message MUST Reference the Issue**

This is **not optional**.
This ensures:

* Perfect automatable traceability
* 1:1 mapping of tags to Issues
* Reliable release audit
* Clean retrospective analytics
* Zero ambiguity for humans or AI agents

---

## **1.7.5 Required Regex Enforcement**

### Tag Name Regex:

```
^v[0-9]{8}-[a-z0-9\-]+-issue-[0-9]+$
```

### Tag Message Regex:

```
^Issue #[0-9]+: .+
```

If a tag does **not** match both patterns:

* It MUST NOT be allowed to remain in the repo
* The CI tag validation workflow MUST fail
* The release owner or repo admin MUST delete the bad tag (`git tag -d <tag> && git push origin :refs/tags/<tag>`) and recreate it with the correct format before release continues

---

## **1.7.6 Required Pull Request Requirements**

A PR **must not be allowed to merge** unless:

1. **PR title includes Issue number**
   Example:

   ```
   Issue #42 — Add RR interval FIT parsing
   ```

2. **PR body includes:**

   * Link to Issue
   * Link to Project
   * SUPER PROMPT summary

3. **CI passes**

4. **Commit messages are valid**

5. **Branch name is valid**

6. **Tagging step (post-merge) references the Issue**

---

## **1.7.7 Required CI Validation Workflow (Must Fail PR on Violation)**

The CI system MUST enforce all traceability rules via automated checks:

* **Check branch name regex**
* **Check PR title contains Issue number**
* **Check PR body references the Issue**
* **Check all commits match commit regex**
* **Check Issue exists and is open**
* **Check Issue is assigned to a Project**
* **Extract Issue number from branch name**
* **Ensure branch Issue == commit Issue == PR Issue**

If any mismatch occurs:

* **The PR MUST fail**
* The contributor must fix and push a corrected commit

This ensures **zero drift** between Issue → Branch → Commit → PR → Tag.

---

## **1.7.8 Optional (Recommended) Local Pre-Commit Hooks**

Contributors may install optional local hooks for convenience:

### `commit-msg` hook:

Validates:

* Issue syntax
* Regex patterns

### `pre-push` hook:

Validates:

* Branch name
* Pending commits

These hooks are optional locally but MUST NOT replace server-side enforcement.

---

## **1.7.9 Required Integration Into Agents**

All agents MUST obey:

* Branch name pattern
* Commit message pattern
* PR pattern
* Tag pattern

If an AI agent cannot comply, the work MUST NOT proceed.

---

## **1.7.10 Rationale**

This strict enforcement:

* Prevents human or agent drift
* Eliminates accidental “hot commits” without Issue linkage
* Ensures perfect traceability for audits
* Supports reproducible evolution of the codebase
* Enables downstream tools to automate retrospectives
* Ensures AGENTS.md evolves based on real data
* Prevents ambiguous or invalid tags that break release tracking

This is the minimal structure required for safe, scalable multi-agent collaboration.

---

## **1.8 Clean Working State Before Starting Work**

Before beginning new work:

* `git status` must be clean
* You must be on updated `main`
* No untracked/uncommitted changes
* No partially completed prior work

---

# 🧪 **2. CI Gatekeeping**

## **2.1 CI Is Mandatory**

Every PR targeting `main` runs CI:

Backend:

* Tests
* Lint
* Type checks
* Build

Frontends (wellness, legacy if applicable):

* Lint
* Unit tests
* Build

Infra:

* Docker builds
* Optional security scans

A PR may not merge unless all checks pass.

---

## **2.2 Updated CI Recovery Policy (Allows Iterative Fixes)**

If CI fails:

### ✔ The PR **remains open**

### ✔ The contributor may push new commits to the same branch

### ✔ CI re-runs automatically

This iterative loop continues until CI is green.

This is the standard GitHub Flow pattern and reduces unnecessary branch churn.

---

## **2.3 When a PR MUST Be Closed**

A PR should be manually closed only when:

1. **It is abandoned**
2. **It violates AGENTS.md rules**, e.g.:

   * Wrong Issue
   * Not in Project
   * Scope creep beyond SUPER PROMPT
   * Excessive unrelated changes
3. **Branch is corrupted structurally**, e.g.:

   * Wrong base
   * Bad merge
   * Large binary additions
4. **Reviewer requests starting fresh**, e.g.:

   * Too many fix commits
   * Confused or drifting intent
5. **Fundamental refactoring is required outside SUPER PROMPT scope**

After closing:

* A new branch from `main` is created
* Useful commits may be cherry-picked

---

## **2.4 CI Logs Must Be Attached to the Issue**

Each CI run (pass or fail) requires logs to be saved into the Issue for:

* Retrospective analysis
* Improving AGENTS.md
* Understanding failure modes
* AI optimization in future cycles

---

# 🔁 **3. The Full Workflow**

## **Step 0 — Write SUPER PROMPT**

Define everything required for a one-day increment.

## **Step 1 — Create GitHub Issue**

Paste SUPER PROMPT text.
Assign to a GitHub Project.

## **Step 2 — Create Feature Branch**

```
git checkout main
git pull origin main
git checkout -b feature/<issue-number>-<kebab-topic>
```

## **Step 3 — Implement Change**

Follow the SUPER PROMPT strictly.

## **Step 4 — Local Validation**

Backend:

```
make test
make lint
make typecheck
```

Frontend:

```
npm run lint
npm run test
npm run build
```

## **Step 5 — Commit (reference Issue!)**

```
git commit -m "Issue #42: Add RR parsing"
```

## **Step 6 — Push**

```
git push origin feature/<issue-number>-<kebab-topic>
```

## **Step 7 — Open PR → main (must reference Issue)**

Include:

* Issue link
* Project link
* Scope summary

## **Step 8 — CI runs**

* Logs attached to Issue
* Fixes pushed until CI is green

## **Step 9 — Merge into main**

## **Step 10 — Create Annotated Tag (must reference Issue)**

```
git tag -a vYYYYMMDD-<kebab-topic>-issue-<issue-number> -m "Issue #<issue-number>: <how this tag satisfies the Issue>"
git push origin --tags
```

## **Step 11 — Close Issue**

Only once:

* PR merged → `main`
* CI passed on main
* Tag created
* All CI logs recorded in the Issue

---

# 🔧 **4. Branching Model**

* `main` — protected trunk, always deployable
* `feature/<issue-number>-<kebab-topic>` — short-lived, one per SUPER PROMPT
* `hotfix/<issue-number>-<kebab-topic>` — urgent fixes from main (production incident exception flow will be defined when live; until then follow the standard workflow)

No long-lived branches.

---

# 🤖 **5. AI Agent Rules (Strict)**

AI agents MUST:

* Start with a SUPER PROMPT
* Create or reference the Issue
* Ensure Issue is in a Project
* Use proper branch naming
* Keep increments ≤ 1 day
* Commit small, clean diffs
* Always reference the Issue in commits and tags
* Never merge their own PRs
* Never bypass CI
* Attach CI logs to Issues
* Maintain the integrity of AGENTS.md
* Suggest AGENTS.md improvements when patterns of failure emerge

AGENTS.md is a **non-negotiable contract**.

---

# 🧭 **6. Summary**

* Trunk-based development
* SUPER PROMPT → Issue → Project is mandatory
* All commits and tags must reference the Issue
* CI failure does *not* close PRs; iteration is allowed
* PR closes only under defined conditions
* CI logs must be posted to the Issue
* Merge → tag → CI pass → then close Issue

This model creates a **high-stability, high-auditability, low-friction, AI-compatible development environment**.

---
