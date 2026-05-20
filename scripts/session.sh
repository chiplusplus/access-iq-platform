#!/usr/bin/env bash
# Session orchestration: deploy/destroy Trust + Platform stacks.
# Usage: ./scripts/session.sh up|down|status
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-CHI-Engineer-222308823356}"
TRUST_PROFILE="${TRUST_PROFILE:-northshire-trust}"
CDK_ENV="${CDK_ENV:-dev}"
REGION="${REGION:-eu-west-2}"
TRUST_REPO="${TRUST_REPO:-$(cd "$(dirname "$0")/../.." && pwd)/northshire-hospital-sim}"
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

platform_output() {
  local stack="$1" key="$2"
  aws cloudformation describe-stacks \
    --stack-name "${stack}-access-iq-${CDK_ENV}" \
    --query "Stacks[0].Outputs[?OutputKey==\`$key\`].OutputValue" \
    --output text --profile "$AWS_PROFILE" --region "$REGION"
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
    -c "platformAccountId=$(aws sts get-caller-identity --query Account --output text --profile "$AWS_PROFILE")" \
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
  for stack in lake secrets catalog ecr ingestion-role network observability compute; do
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

cmd_ingest() {
  echo ""
  echo "  Launching 3 ingestion tasks in parallel (D-07)"
  echo "  Cluster: access-iq-${CDK_ENV}-ingestion"
  echo ""

  # ── Step 1: Resolve runtime values from CloudFormation outputs ──
  step_start "1/3" "Resolve cluster and network config" "<5s"

  local CLUSTER_NAME
  CLUSTER_NAME=$(platform_output "compute" "ClusterName")

  # Resolve private subnet IDs from VPC
  local VPC_ID
  VPC_ID=$(aws ec2 describe-vpcs \
    --filters "Name=tag:Name,Values=access-iq-${CDK_ENV}-platform" \
    --query 'Vpcs[0].VpcId' --output text \
    --profile "$AWS_PROFILE" --region "$REGION")

  local SUBNET_IDS
  SUBNET_IDS=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:aws-cdk:subnet-type,Values=Private" \
    --query 'Subnets[*].SubnetId' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" | tr '\t' ',')

  local SG_ID
  SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=*ecs-task*" \
    --query 'SecurityGroups[0].GroupId' --output text \
    --profile "$AWS_PROFILE" --region "$REGION")

  echo "  Cluster:  $CLUSTER_NAME"
  echo "  Subnets:  $SUBNET_IDS"
  echo "  SG:       $SG_ID"
  step_done

  # ── Step 2: Launch all 3 tasks in parallel ──
  step_start "2/3" "Launch ECS tasks" "<10s"

  local SOURCES=("ingest-postgres" "ingest-sftp" "ingest-trust-s3")
  local TASK_ARNS=()
  local PIDS=()

  for source in "${SOURCES[@]}"; do
    local task_def="access-iq-${CDK_ENV}-${source}"
    (
      aws ecs run-task \
        --cluster "$CLUSTER_NAME" \
        --task-definition "$task_def" \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_IDS],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
        --query 'tasks[0].taskArn' --output text \
        --profile "$AWS_PROFILE" --region "$REGION"
    ) > "/tmp/ecs_task_${source}.arn" &
    PIDS+=($!)
  done

  # Wait for all launches to complete
  for pid in "${PIDS[@]}"; do
    wait "$pid"
  done

  # Collect and validate task ARNs
  local LAUNCH_FAILED=0
  for source in "${SOURCES[@]}"; do
    local arn
    arn="$(cat "/tmp/ecs_task_${source}.arn" 2>/dev/null || true)"
    if [ -z "$arn" ] || [ "$arn" = "None" ] || [ "$arn" = "null" ]; then
      echo "  ERROR: Failed to launch $source (got ARN: '${arn:-<empty>}')"
      LAUNCH_FAILED=$((LAUNCH_FAILED + 1))
    else
      TASK_ARNS+=("$arn")
      echo "  Launched: $source -> $arn"
    fi
  done

  if [ "$LAUNCH_FAILED" -gt 0 ]; then
    echo ""
    echo "  ERROR: $LAUNCH_FAILED task(s) failed to launch. Aborting."
    rm -f /tmp/ecs_task_*.arn
    exit 1
  fi
  step_done

  # ── Step 3: Poll until all tasks stopped, then report ──
  step_start "3/3" "Wait for completion" "2-10 min"

  local ALL_STOPPED=false
  while [ "$ALL_STOPPED" = false ]; do
    sleep 15
    ALL_STOPPED=true
    for arn in "${TASK_ARNS[@]}"; do
      local status
      status=$(aws ecs describe-tasks \
        --cluster "$CLUSTER_NAME" \
        --tasks "$arn" \
        --query 'tasks[0].lastStatus' --output text \
        --profile "$AWS_PROFILE" --region "$REGION")
      if [ "$status" != "STOPPED" ]; then
        ALL_STOPPED=false
        printf "    %s: %s\n" "$(basename "$arn")" "$status"
      fi
    done
  done

  # Report per-task results
  echo ""
  local FAILED=0
  for i in "${!SOURCES[@]}"; do
    local source="${SOURCES[$i]}"
    local arn="${TASK_ARNS[$i]}"
    local exit_code
    exit_code=$(aws ecs describe-tasks \
      --cluster "$CLUSTER_NAME" \
      --tasks "$arn" \
      --query 'tasks[0].containers[0].exitCode' --output text \
      --profile "$AWS_PROFILE" --region "$REGION")

    if [ "$exit_code" = "0" ]; then
      printf "  \033[1;32m✓ %s — exit 0\033[0m\n" "$source"
    else
      printf "  \033[1;31m✗ %s — exit %s\033[0m\n" "$source" "$exit_code"
      FAILED=$((FAILED + 1))
    fi
  done
  step_done

  # Clean up temp files
  rm -f /tmp/ecs_task_*.arn

  session_summary

  if [ "$FAILED" -gt 0 ]; then
    echo ""
    echo "  ✗ $FAILED task(s) failed. Check CloudWatch logs."
    echo ""
    exit 1
  fi

  echo ""
  echo "  ✓ All 3 ingestion tasks completed successfully."
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────

case "${1:-}" in
  up)     cmd_up ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  ingest) cmd_ingest ;;
  *)
    echo "Usage: $0 {up|down|status|ingest}"
    echo ""
    echo "  up      Deploy Trust + Platform stacks with peering (~10 min)"
    echo "  down    Destroy Platform + Trust stacks (~8 min)"
    echo "  status  Show current stack states"
    echo "  ingest  Run all 3 Bronze ingestion tasks on ECS (~5 min)"
    exit 1
    ;;
esac
