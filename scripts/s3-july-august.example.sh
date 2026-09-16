#!/usr/bin/env bash
# Example: validate then ingest July + August test CSVs from S3.
# 1. Copy to s3-july-august.sh and set BUCKET, PREFIX, API key.
# 2. aws configure / IAM role must allow s3:GetObject on the prefix.
# 3. Run validate-only first, then set VALIDATE_ONLY=false.

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

export HARNESS_API_KEY="${HARNESS_API_KEY:?set HARNESS_API_KEY}"
ACCOUNT_ID="SxuV0ChbRqWGSYClFlMQMQ"
PROVIDER_ID="6aaa161da729b114c9ffc862"
BUCKET="${BUCKET:?set BUCKET}"
PREFIX="${PREFIX:-cacm-external-test/}"   # e.g. cacm-external-test/july.csv

# Adjust keys to match your actual object paths after upload
JULY_URI="s3://${BUCKET}/${PREFIX}july-forecast.csv"
AUG_URI="s3://${BUCKET}/${PREFIX}august-forecast.csv"

PERIODS_JSON=$(python3 -c "import json; print(json.dumps({
  '${JULY_URI}': '20260701-20260731',
  '${AUG_URI}': '20260801-20260831',
}))")

VALIDATE_ONLY="${VALIDATE_ONLY:-true}"
EXTRA=()
if [ "$VALIDATE_ONLY" = "true" ]; then
  EXTRA+=(--validate-only)
fi

python3 -m pip install -q -r requirements.txt
export PYTHONPATH="$REPO"

python3 -m cacm_external_ingest.cli \
  --account-id "$ACCOUNT_ID" \
  --api-key "$HARNESS_API_KEY" \
  --provider-id "$PROVIDER_ID" \
  --provider-type custom \
  --s3-prefix "s3://${BUCKET}/${PREFIX}" \
  --invoice-periods-json "$PERIODS_JSON" \
  "${EXTRA[@]}"
