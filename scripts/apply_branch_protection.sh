#!/usr/bin/env bash
# Apply branch protection settings for main as required by AGENTS.md.
# Prereqs: gh CLI authenticated with admin rights (GH_TOKEN or gh auth login).

set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"

# Optionally load OWNER/REPO/BRANCH from .env
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a
  source "$ENV_FILE"
  set +a
fi

OWNER="${OWNER:-your-org-or-user}"
REPO="${REPO:-fitness-pals}"
BRANCH="${BRANCH:-main}"

if [[ "$OWNER" == "your-org-or-user" || "$REPO" == "fitness-pals" ]]; then
  echo "ERROR: OWNER/REPO not set. Export OWNER/REPO/BRANCH or set them in $ENV_FILE." >&2
  exit 1
fi

# Update this list if job names change; they must match the GitHub check names exactly.
CONTEXTS=(
  "branch-name"
  "commit-messages"
  "Lint & Test"
)

echo "Setting branch protection on $OWNER/$REPO:$BRANCH"

contexts_json=$(printf '"%s",' "${CONTEXTS[@]}")
contexts_json="[${contexts_json%,}]"

payload="$(mktemp)"
cat >"$payload" <<EOF
{
  "required_status_checks": {
    "strict": true,
    "contexts": $contexts_json
  },
  "enforce_admins": true,
  "required_linear_history": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "required_approving_review_count": 1
  },
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true,
  "restrictions": null
}
EOF

gh api -X PUT \
  -H "Accept: application/vnd.github+json" \
  "repos/$OWNER/$REPO/branches/$BRANCH/protection" \
  --input "$payload"

# Require signed commits (recommended in AGENTS.md).
if gh api -X PUT "repos/$OWNER/$REPO/branches/$BRANCH/protection/required_signatures" >/dev/null 2>&1; then
  echo "Required signatures enabled."
else
  echo "Required signatures not supported on this plan/repo; continuing without it."
fi

# Align merge methods with linear history (squash/rebase only, disable merge commits).
if gh api -X PATCH -H "Accept: application/vnd.github+json" \
  "repos/$OWNER/$REPO" \
  -f allow_merge_commit=false \
  -f allow_squash_merge=true \
  -f allow_rebase_merge=true >/dev/null; then
  echo "Merge methods updated: merge-commits disabled; squash/rebase enabled."
else
  echo "Warning: could not update merge method settings via API."
fi

echo "Done. Verify protection rules in GitHub settings."
