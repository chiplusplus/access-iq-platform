#!/usr/bin/env bash
# Session orchestration: deploy/destroy Trust + Platform stacks.
# Usage: ./scripts/session.sh up|down|status
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-CHI-Engineer-222308823356}"
TRUST_PROFILE="${TRUST_PROFILE:-northshire-trust}"
CDK_ENV="${CDK_ENV:-dev}"
REGION="${REGION:-eu-west-2}"
TRUST_REPO="${TRUST_REPO:-/Users/chiamakaanamekwe/Documents/tech-projects/data-engineering/northshire-hospital-sim}"
PLATFORM_REPO="$(cd "$(dirname "$0")/.." && pwd)"

# ── Timing helpers ────────────────────────────────────────────────────

SESSION_START=$(date +%s)

step_start() {
  STEP_START=$(date +%s)
  local step="$1" total="$2" estimate="$3"
  local elapsed=$(( $(date +%s) - SESSION_START ))
  printf "\n\033[1;36m═══ Step %s: %s (est. %s) ═══\033[0m\n" "$step" "$2" "$estimate"
  printf "\033[0;37m    Session elapsed: %s\033[0m\n\n" "$(fmt_duration $elapsed)"
}

step_done() {
  local duration=$(( $(date +%s) - STEP_START ))
  local total_elapsed=$(( $(date +%s) - SESSION_START ))
  printf "\n\033[1;32m    ✓ Done in %s (total: %s)\033[0m\n" \
    "$(fmt_duration $duration)" "$(fmt_duration $total_elapsed)"
}

fmt_duration() {
  local secs=$1
  if (( secs < 60 )); then
    echo "${secs}s"
  else
    echo "$((secs / 60))m $((secs % 60))s"
  fi
}

session_summary() {
  local total=$(( $(date +%s) - SESSION_START ))
  printf "\n\033[1;33m═══════════════════════════════════════════════\033[0m\n"
  printf "\033[1;33m  Total session time: %s\033[0m\n" "$(fmt_duration $total)"
  printf "\033[1;33m═══════════════════════════════════════════════\033[0m\n"
}

# ── Trust helpers ─────────────────────────────────────────────────────

trust_output() {
  aws cloudformation describe-stacks \
    --stack-name NorthshireTrustStack \
    --query "Stacks[0].Outputs[?OutputKey==\`$1\`].OutputValue" \
    --output text --profile "$TRUST_PROFILE" --region "$REGION"
}

# ── Commands ──────────────────────────────────────────────────────────

cmd_up() {
  echo ""
  echo "  Deploy sequence: Trust bootstrap → Platform → Trust (routes + SGs)"
  echo "  Estimated total: 15-25 minutes"
  echo ""

  step_start "1/4" "Bootstrap Trust environment (deploy + DB + data)" "8-12 min"
  (cd "$TRUST_REPO" && unset VIRTUAL_ENV && AWS_PROFILE="$TRUST_PROFILE" make trust-bootstrap \
    ARGS="--profile $TRUST_PROFILE")
  step_done

  step_start "2/4" "Read Trust outputs" "<5s"
  TRUST_VPC=$(trust_output VpcId)
  echo "  Trust VPC: $TRUST_VPC"
  step_done

  step_start "3/4" "Deploy Platform stacks" "5-8 min"
  (cd "$PLATFORM_REPO/infra" && AWS_PROFILE="$AWS_PROFILE" uv run cdk deploy --all \
    -c "env=$CDK_ENV" \
    -c "trust_vpc_id=$TRUST_VPC" \
    --require-approval never)
  step_done

  PLATFORM_VPC=$(aws ec2 describe-vpcs \
    --filters "Name=tag:Name,Values=access-iq-${CDK_ENV}-platform" \
    --query 'Vpcs[0].VpcId' --output text \
    --profile "$AWS_PROFILE" --region "$REGION")

  PEERING_ID=$(aws cloudformation describe-stacks \
    --stack-name "network-access-iq-${CDK_ENV}" \
    --query "Stacks[0].Outputs[?OutputKey==\`PeeringConnectionId\`].OutputValue" \
    --output text --profile "$AWS_PROFILE" --region "$REGION")

  step_start "4/4" "Redeploy Trust with routes and peering SG rules" "~2 min"
  echo "  Platform VPC:  $PLATFORM_VPC"
  echo "  Peering ID:    $PEERING_ID"
  (cd "$TRUST_REPO/infra" && AWS_PROFILE="$TRUST_PROFILE" uv run cdk deploy \
    -c "platformVpcId=$PLATFORM_VPC" \
    -c "platformCidr=10.10.0.0/16" \
    -c "platformAccountId=222308823356" \
    -c "peeringConnectionId=$PEERING_ID" \
    --require-approval never)
  step_done

  session_summary
  echo ""
  echo "  ✓ Both stacks deployed. Run './scripts/session.sh status' to verify."
  echo ""
}

cmd_down() {
  echo ""
  echo "  Destroy sequence: Platform → Trust (no cross-account dependencies)"
  echo "  Estimated total: 6-10 minutes"
  echo ""

  TRUST_VPC=$(trust_output VpcId 2>/dev/null || echo "vpc-placeholder")

  step_start "1/2" "Destroy Platform stacks" "3-5 min"
  (cd "$PLATFORM_REPO/infra" && AWS_PROFILE="$AWS_PROFILE" uv run cdk destroy --all --force \
    -c "env=$CDK_ENV" \
    -c "trust_vpc_id=$TRUST_VPC")
  step_done

  step_start "2/2" "Destroy Trust stack" "3-5 min"
  (cd "$TRUST_REPO" && kill $(cat .tunnel.pid 2>/dev/null) 2>/dev/null; rm -f "$TRUST_REPO/.tunnel.pid")
  (cd "$TRUST_REPO/infra" && AWS_PROFILE="$TRUST_PROFILE" uv run cdk destroy --force)
  step_done

  session_summary
  echo ""
  echo "  ✓ Both stacks destroyed."
  echo ""
}

cmd_status() {
  echo ""
  echo "═══ Trust Stack ═══"
  printf "  %-24s" "NorthshireTrustStack:"
  aws cloudformation describe-stacks --stack-name NorthshireTrustStack \
    --query 'Stacks[0].StackStatus' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT DEPLOYED"

  echo ""
  echo "═══ Platform Stacks ═══"
  for stack in lake secrets catalog ecr ingestion-role network; do
    printf "  %-24s" "$stack:"
    aws cloudformation describe-stacks --stack-name "${stack}-access-iq-${CDK_ENV}" \
      --query 'Stacks[0].StackStatus' --output text \
      --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT DEPLOYED"
  done

  echo ""
  echo "═══ Key Resources ═══"
  printf "  %-24s" "VPC Peering:"
  aws ec2 describe-vpc-peering-connections \
    --filters "Name=status-code,Values=active" \
    --query 'VpcPeeringConnections[0].VpcPeeringConnectionId' \
    --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE"
  printf "  %-24s" "Trust RDS:"
  aws rds describe-db-instances \
    --query 'DBInstances[?starts_with(DBInstanceIdentifier,`northshire`)].DBInstanceStatus|[0]' \
    --output text --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE"
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────

case "${1:-}" in
  up)     cmd_up ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  *)
    echo "Usage: $0 {up|down|status}"
    echo ""
    echo "  up      Deploy Trust + Platform stacks with peering (~10 min)"
    echo "  down    Destroy Platform + Trust stacks (~8 min)"
    echo "  status  Show current stack states"
    exit 1
    ;;
esac
