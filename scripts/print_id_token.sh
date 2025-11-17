#!/usr/bin/env bash
set -euo pipefail

# Prints a Google ID token for the training-agent API using service account impersonation.
# Requires:
#   - RUNTRAINER_GOOGLE_CLIENT_ID set in .env
#   - Service account training-agent-sa created and tokenCreator bound to your user
#     (run ./scripts/setup_sa_impersonation.sh first)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

if [[ -z "${RUNTRAINER_GOOGLE_CLIENT_ID:-}" ]]; then
  echo "RUNTRAINER_GOOGLE_CLIENT_ID is not set. Please set it in .env." >&2
  exit 1
fi

PROJECT=$(gcloud config get-value project)
SA_EMAIL="training-agent-sa@${PROJECT}.iam.gserviceaccount.com"

gcloud auth print-identity-token \
  --impersonate-service-account="${SA_EMAIL}" \
  --audiences="${RUNTRAINER_GOOGLE_CLIENT_ID}"
