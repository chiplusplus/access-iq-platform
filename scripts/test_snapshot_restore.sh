#!/usr/bin/env bash
# Integration test: verify Redshift snapshot/restore round-trip preserves data.
# This is a standalone test - snapshot restore is NOT part of the make up flow.
# Usage: ./scripts/test_snapshot_restore.sh
# Requires: Redshift Serverless workgroup deployed (make up first).
set -euo pipefail

if [ -z "${PLATFORM_PROFILE:-}" ]; then
  echo "ERROR: PLATFORM_PROFILE is not set. Export it before running: export PLATFORM_PROFILE=<your-platform-profile>"
  exit 1
fi
AWS_PROFILE="$PLATFORM_PROFILE"
if [ -z "${TRUST_PROFILE:-}" ]; then
  echo "ERROR: TRUST_PROFILE is not set. Export it before running: export TRUST_PROFILE=<your-trust-profile>"
  exit 1
fi
CDK_ENV="${CDK_ENV:-dev}"
REGION="${REGION:-eu-west-2}"
RS_WORKGROUP="access-iq-${CDK_ENV}"
RS_DB="dev"
PLATFORM_REPO="$(cd "$(dirname "$0")/.." && pwd)"

RS_SECRET_ARN=$(aws redshift-serverless get-namespace \
  --namespace-name "$RS_WORKGROUP" \
  --query 'namespace.adminPasswordSecretArn' \
  --output text --profile "$AWS_PROFILE" --region "$REGION")

echo "=== Snapshot/Restore Round-Trip Test ==="
echo ""

# ── Helper: wait for statement to finish ─────────────────────────────

wait_for_statement() {
  local stmt_id="$1"
  while true; do
    local status
    status=$(aws redshift-data describe-statement --id "$stmt_id" \
      --query 'Status' --output text \
      --profile "$AWS_PROFILE" --region "$REGION")
    [ "$status" = "FINISHED" ] && break
    if [ "$status" = "FAILED" ]; then
      local err
      err=$(aws redshift-data describe-statement --id "$stmt_id" \
        --query 'Error' --output text \
        --profile "$AWS_PROFILE" --region "$REGION")
      echo "FAILED: $err"
      exit 1
    fi
    sleep 2
  done
}

# ── Step 1: Create marker table ───────────────────────────────────────

echo "1. Creating marker table..."
STMT_ID=$(aws redshift-data execute-statement \
  --workgroup-name "$RS_WORKGROUP" \
  --database "$RS_DB" \
  --secret-arn "$RS_SECRET_ARN" \
  --sql "CREATE TABLE IF NOT EXISTS public._snapshot_test_marker (created_at TIMESTAMP DEFAULT GETDATE(), marker VARCHAR(100));" \
  --query 'Id' --output text \
  --profile "$AWS_PROFILE" --region "$REGION")
wait_for_statement "$STMT_ID"
echo "   Marker table created."

# ── Step 2: Insert marker row ─────────────────────────────────────────

echo "2. Inserting marker row..."
MARKER="test-$(date +%s)"
STMT_ID=$(aws redshift-data execute-statement \
  --workgroup-name "$RS_WORKGROUP" \
  --database "$RS_DB" \
  --secret-arn "$RS_SECRET_ARN" \
  --sql "INSERT INTO public._snapshot_test_marker (marker) VALUES ('$MARKER');" \
  --query 'Id' --output text \
  --profile "$AWS_PROFILE" --region "$REGION")
wait_for_statement "$STMT_ID"
echo "   Marker: $MARKER"

# ── Step 3: Destroy warehouse stack (triggers FinalSnapshotName) ──────

echo "3. Destroying warehouse stack (snapshot will be taken)..."
TRUST_VPC=$(aws cloudformation describe-stacks \
  --stack-name NorthshireTrustStack \
  --query "Stacks[0].Outputs[?OutputKey==\`VpcId\`].OutputValue" \
  --output text --profile "${TRUST_PROFILE}" --region "$REGION" 2>/dev/null || echo "vpc-placeholder")
(cd "$PLATFORM_REPO/infra" && AWS_PROFILE="$AWS_PROFILE" uv run cdk destroy \
  "warehouse-access-iq-${CDK_ENV}" --force \
  -c "env=$CDK_ENV" -c "trust_vpc_id=$TRUST_VPC")
echo "   Warehouse stack destroyed."

# ── Step 4: Find latest snapshot ─────────────────────────────────────

echo "4. Finding latest snapshot..."
LATEST_SNAPSHOT=$(aws redshift-serverless list-snapshots \
  --namespace-name "access-iq-${CDK_ENV}" \
  --query 'snapshots | sort_by(@, &snapshotCreateTime) | [-1].snapshotName' \
  --output text --profile "$AWS_PROFILE" --region "$REGION")
echo "   Latest snapshot: $LATEST_SNAPSHOT"

# ── Step 5: Restore namespace from snapshot via CLI ──────────────────

echo "5. Restoring namespace from snapshot..."
aws redshift-serverless restore-from-snapshot \
  --namespace-name "access-iq-${CDK_ENV}" \
  --workgroup-name "$RS_WORKGROUP" \
  --snapshot-name "$LATEST_SNAPSHOT" \
  --profile "$AWS_PROFILE" --region "$REGION"

echo "   Waiting for namespace restore..."
ns_status="RESTORING"
while [ "$ns_status" != "AVAILABLE" ]; do
  sleep 15
  ns_status=$(aws redshift-serverless get-namespace \
    --namespace-name "access-iq-${CDK_ENV}" \
    --query 'namespace.status' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "RESTORING")
  echo "   Namespace status: $ns_status"
done
echo "   Namespace restored."

# ── Step 6: Redeploy warehouse stack to recreate workgroup ───────────

echo "6. Redeploying warehouse stack (recreate workgroup)..."
(cd "$PLATFORM_REPO/infra" && AWS_PROFILE="$AWS_PROFILE" uv run cdk deploy \
  "warehouse-access-iq-${CDK_ENV}" \
  -c "env=$CDK_ENV" -c "trust_vpc_id=$TRUST_VPC" \
  --require-approval never)
echo "   Warehouse stack redeployed."

echo "7. Waiting for workgroup..."
wg_status="CREATING"
while [ "$wg_status" != "AVAILABLE" ]; do
  wg_status=$(aws redshift-serverless get-workgroup \
    --workgroup-name "$RS_WORKGROUP" \
    --query 'workgroup.status' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT_FOUND")
  sleep 10
done
echo "   Workgroup AVAILABLE."

# ── Step 8: Verify marker row survived ───────────────────────────────

echo "8. Verifying marker row survived restore..."
STMT_ID=$(aws redshift-data execute-statement \
  --workgroup-name "$RS_WORKGROUP" \
  --database "$RS_DB" \
  --secret-arn "$RS_SECRET_ARN" \
  --sql "SELECT marker FROM public._snapshot_test_marker WHERE marker = '$MARKER';" \
  --query 'Id' --output text \
  --profile "$AWS_PROFILE" --region "$REGION")
wait_for_statement "$STMT_ID"

ROW_COUNT=$(aws redshift-data get-statement-result --id "$STMT_ID" \
  --query 'TotalNumRows' --output text \
  --profile "$AWS_PROFILE" --region "$REGION")

if [ "$ROW_COUNT" -ge 1 ]; then
  echo ""
  echo "=== PASS: Marker '$MARKER' survived snapshot/restore round-trip ==="
else
  echo ""
  echo "=== FAIL: Marker '$MARKER' not found after restore ==="
  exit 1
fi

# ── Cleanup ───────────────────────────────────────────────────────────

aws redshift-data execute-statement \
  --workgroup-name "$RS_WORKGROUP" \
  --database "$RS_DB" \
  --secret-arn "$RS_SECRET_ARN" \
  --sql "DROP TABLE IF EXISTS public._snapshot_test_marker;" \
  --profile "$AWS_PROFILE" --region "$REGION" >/dev/null 2>&1
echo "   Cleanup: marker table dropped."
