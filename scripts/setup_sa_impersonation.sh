#!/usr/bin/env bash
set -euo pipefail

# This script creates a service account for training-agent token impersonation
# and grants the current user permission to mint ID tokens for the Web Client ID.
#
# Prereqs:
#   - gcloud installed and authenticated (`gcloud auth login`)
#   - gcloud config set project <YOUR_PROJECT>
#
# Usage:
#   ./scripts/setup_sa_impersonation.sh
#
# After running, fetch an ID token with:
#   ./scripts/print_id_token.sh

SA_NAME="training-agent-sa"
PROJECT=$(gcloud config get-value project)
USER_EMAIL=$(gcloud config get-value account)

echo "Project: ${PROJECT}"
echo "User: ${USER_EMAIL}"
echo "Service Account: ${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

read -p "Proceed to create/bind roles? [y/N] " ok
if [[ "${ok:-N}" =~ ^[Yy]$ ]]; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="Training Agent SA" \
    --project="${PROJECT}" || true

  gcloud iam service-accounts add-iam-policy-binding \
    "${SA_NAME}@${PROJECT}.iam.gserviceaccount.com" \
    --member="user:${USER_EMAIL}" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --project="${PROJECT}"

  echo "Done. Now run ./scripts/print_id_token.sh to mint an ID token."
else
  echo "Aborted."
fi
