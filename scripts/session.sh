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
  printf "\n\033[1;36m═══ Step %s: %s (est. %s) ═══\033[0m\n" "$step" "$total" "$estimate"
  printf "\033[0;37m    Started at: %s\033[0m\n\n" "$(date +%H:%M:%S)"
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
  local skip_generate=""
  local skip_seed=false
  for arg in "$@"; do
    case "$arg" in
      --skip-generate) skip_generate="--skip-generate" ;;
      --skip-seed) skip_seed=true ;;
    esac
  done

  echo ""
  echo "  Deploy sequence: Trust bootstrap → Platform → Trust (routes + SGs) → Secrets → Docker"
  [ -n "$skip_generate" ] && echo "  Skipping data generation (reusing existing data/staging/)"
  [ "$skip_seed" = true ] && echo "  Skipping data seeding (deploy infrastructure only)"
  echo "  Estimated total: 18-30 minutes"
  echo ""

  step_start "1/6" "Bootstrap Trust environment (deploy + DB + data)" "8-12 min"
  if [ "$skip_seed" = true ]; then
    (cd "$TRUST_REPO/infra" && unset VIRTUAL_ENV && . "$TRUST_REPO/.northshire-hospital-sim/bin/activate" \
      && AWS_PROFILE="$TRUST_PROFILE" cdk deploy --outputs-file cdk-outputs.json \
      --profile "$TRUST_PROFILE" --require-approval never)
  else
    (cd "$TRUST_REPO" && unset VIRTUAL_ENV && AWS_PROFILE="$TRUST_PROFILE" make trust-bootstrap \
      ARGS="--profile $TRUST_PROFILE $skip_generate")
  fi
  step_done

  step_start "2/6" "Read Trust outputs" "<5s"
  TRUST_VPC=$(trust_output VpcId)
  echo "  Trust VPC: $TRUST_VPC"
  step_done

  step_start "3/6" "Deploy Platform stacks" "5-8 min"
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

  step_start "4/6" "Redeploy Trust with routes and peering SG rules" "~2 min"
  echo "  Platform VPC:  $PLATFORM_VPC"
  echo "  Peering ID:    $PEERING_ID"
  (cd "$TRUST_REPO/infra" && AWS_PROFILE="$TRUST_PROFILE" uv run cdk deploy \
    -c "platformVpcId=$PLATFORM_VPC" \
    -c "platformCidr=10.10.0.0/16" \
    -c "platformAccountId=$(aws sts get-caller-identity --query Account --output text --profile "$AWS_PROFILE")" \
    -c "peeringConnectionId=$PEERING_ID" \
    --require-approval never)
  step_done

  # ── Step 5: Seed Platform secrets from Trust outputs ──
  step_start "5/6" "Seed Platform secrets from Trust" "<30s"

  local SECRET_PREFIX="access-iq/${CDK_ENV}"

  # Fetch Trust RDS credentials from Trust-account Secrets Manager
  local EHR_SECRET_JSON
  EHR_SECRET_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "$(trust_output EhrRoSecretArn)" \
    --query SecretString --output text \
    --profile "$TRUST_PROFILE" --region "$REGION")

  local URGENT_SECRET_JSON
  URGENT_SECRET_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "$(trust_output UrgentRoSecretArn)" \
    --query SecretString --output text \
    --profile "$TRUST_PROFILE" --region "$REGION")

  local RDS_ENDPOINT
  RDS_ENDPOINT=$(trust_output RdsEndpoint)
  local RDS_PORT
  RDS_PORT=$(trust_output RdsPort)

  # Construct DSNs: postgresql://user:pass@host:port/dbname
  local EHR_USER EHR_PASS EHR_DB
  EHR_USER=$(echo "$EHR_SECRET_JSON" | jq -r '.username')
  EHR_PASS=$(echo "$EHR_SECRET_JSON" | jq -r '.password')
  EHR_DB=$(echo "$EHR_SECRET_JSON" | jq -r '.dbname // "ehr_mirror"')

  local URGENT_USER URGENT_PASS URGENT_DB
  URGENT_USER=$(echo "$URGENT_SECRET_JSON" | jq -r '.username')
  URGENT_PASS=$(echo "$URGENT_SECRET_JSON" | jq -r '.password')
  URGENT_DB=$(echo "$URGENT_SECRET_JSON" | jq -r '.dbname // "urgent_care_mirror"')

  local EHR_DSN="postgresql://${EHR_USER}:${EHR_PASS}@${RDS_ENDPOINT}:${RDS_PORT}/${EHR_DB}"
  local URGENT_DSN="postgresql://${URGENT_USER}:${URGENT_PASS}@${RDS_ENDPOINT}:${RDS_PORT}/${URGENT_DB}"

  # Fetch SFTP credentials from Trust-account Secrets Manager
  local SFTP_SECRET_JSON
  SFTP_SECRET_JSON=$(aws secretsmanager get-secret-value \
    --secret-id "$(trust_output SftpUserSecretArn)" \
    --query SecretString --output text \
    --profile "$TRUST_PROFILE" --region "$REGION")

  local SFTP_USER_VAL SFTP_PRIVATE_KEY_VAL
  SFTP_USER_VAL=$(echo "$SFTP_SECRET_JSON" | jq -r '.username // .user')
  SFTP_PRIVATE_KEY_VAL=$(echo "$SFTP_SECRET_JSON" | jq -r '.privateKey // .private_key // empty')

  if [ -z "$SFTP_PRIVATE_KEY_VAL" ]; then
    # Generate SSH key pair and register with Transfer Family
    echo "  Generating SSH key pair for Transfer Family publickey auth..."
    local SFTP_KEY_DIR="/tmp/access-iq-sftp-key-$$"
    mkdir -p "$SFTP_KEY_DIR"
    ssh-keygen -t rsa -b 4096 -f "$SFTP_KEY_DIR/id_rsa" -N "" -q

    SFTP_PRIVATE_KEY_VAL=$(cat "$SFTP_KEY_DIR/id_rsa")
    local SFTP_PUBLIC_KEY
    SFTP_PUBLIC_KEY=$(cat "$SFTP_KEY_DIR/id_rsa.pub")

    # Import public key to Transfer Family user
    local SFTP_SERVER_ID_FOR_KEY
    SFTP_SERVER_ID_FOR_KEY=$(trust_output SftpServerId)
    aws transfer import-ssh-public-key \
      --server-id "$SFTP_SERVER_ID_FOR_KEY" \
      --user-name "trust_sftp" \
      --ssh-public-key-body "$SFTP_PUBLIC_KEY" \
      --profile "$TRUST_PROFILE" --region "$REGION" >/dev/null 2>&1 || true

    rm -rf "$SFTP_KEY_DIR"
    echo "  ✓ SSH key registered with Transfer Family"
  fi

  # Resolve SFTP private IP for cross-VPC peering access.
  # Transfer Family public endpoints resolve to public IPs that aren't
  # reachable from private subnets over VPC peering. We need the VPC
  # endpoint's ENI private IP (within Trust CIDR 10.0.0.0/16).
  local SFTP_SERVER_ID
  SFTP_SERVER_ID=$(aws transfer list-servers \
    --query 'Servers[0].ServerId' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION")

  local SFTP_ENDPOINT_TYPE
  SFTP_ENDPOINT_TYPE=$(aws transfer describe-server \
    --server-id "$SFTP_SERVER_ID" \
    --query 'Server.EndpointType' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION")

  local SFTP_ENDPOINT
  if [ "$SFTP_ENDPOINT_TYPE" = "VPC" ]; then
    local SFTP_VPC_EP_ID
    SFTP_VPC_EP_ID=$(aws transfer describe-server \
      --server-id "$SFTP_SERVER_ID" \
      --query 'Server.EndpointDetails.VpcEndpointId' --output text \
      --profile "$TRUST_PROFILE" --region "$REGION")

    local SFTP_ENI_ID
    SFTP_ENI_ID=$(aws ec2 describe-vpc-endpoints \
      --vpc-endpoint-ids "$SFTP_VPC_EP_ID" \
      --query 'VpcEndpoints[0].NetworkInterfaceIds[0]' --output text \
      --profile "$TRUST_PROFILE" --region "$REGION")

    SFTP_ENDPOINT=$(aws ec2 describe-network-interfaces \
      --network-interface-ids "$SFTP_ENI_ID" \
      --query 'NetworkInterfaces[0].PrivateIpAddress' --output text \
      --profile "$TRUST_PROFILE" --region "$REGION")

    echo "  SFTP: VPC endpoint → private IP $SFTP_ENDPOINT"
  else
    SFTP_ENDPOINT=$(trust_output SftpEndpoint)
    echo "  WARNING: SFTP server is ${SFTP_ENDPOINT_TYPE} type (${SFTP_ENDPOINT})"
    echo "           Public endpoints are not reachable over VPC peering from private subnets."
    echo "           Switch Trust Transfer Family to VPC endpoint type for peering access."
  fi

  # Upsert each secret in Platform account
  seed_secret() {
    local name="$1" value="$2"
    if aws secretsmanager describe-secret --secret-id "$name" \
        --profile "$AWS_PROFILE" --region "$REGION" >/dev/null 2>&1; then
      aws secretsmanager put-secret-value --secret-id "$name" \
        --secret-string "$value" \
        --profile "$AWS_PROFILE" --region "$REGION" >/dev/null
      echo "  ↻ Updated $name"
    else
      aws secretsmanager create-secret --name "$name" \
        --secret-string "$value" \
        --profile "$AWS_PROFILE" --region "$REGION" >/dev/null
      echo "  + Created $name"
    fi
  }

  seed_secret "${SECRET_PREFIX}/ehr-dsn"          "$EHR_DSN"
  seed_secret "${SECRET_PREFIX}/urgent-care-dsn"   "$URGENT_DSN"
  seed_secret "${SECRET_PREFIX}/sftp-host"         "$SFTP_ENDPOINT"
  seed_secret "${SECRET_PREFIX}/sftp-port"         "22"
  seed_secret "${SECRET_PREFIX}/sftp-user"         "$SFTP_USER_VAL"
  if [ -n "$SFTP_PRIVATE_KEY_VAL" ]; then
    seed_secret "${SECRET_PREFIX}/sftp-private-key"  "$SFTP_PRIVATE_KEY_VAL"
  fi

  step_done

  # ── Step 6: Build and push Docker image to ECR ──
  step_start "6/6" "Build and push ingestion image to ECR" "1-3 min"

  local ECR_URI
  ECR_URI=$(platform_output ecr IngestionRepoUri)
  echo "  ECR repo: $ECR_URI"

  # Authenticate Docker to ECR
  aws ecr get-login-password --profile "$AWS_PROFILE" --region "$REGION" \
    | docker login --username AWS --password-stdin \
      "$(echo "$ECR_URI" | cut -d/ -f1)" 2>/dev/null

  # Build and push
  (cd "$PLATFORM_REPO" && docker build --platform linux/amd64 -t "${ECR_URI}:latest" .)
  docker push "${ECR_URI}:latest"
  echo "  ✓ Pushed ${ECR_URI}:latest"

  step_done

  session_summary
  echo ""
  echo "  ✓ All stacks deployed, secrets seeded, image pushed."
  echo "  Run './scripts/session.sh status' to verify, then 'make ingest' to run."
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
  if [ -f "$TRUST_REPO/.tunnel.pid" ]; then
    local tunnel_pid
    tunnel_pid="$(cat "$TRUST_REPO/.tunnel.pid" 2>/dev/null || true)"
    if [[ "$tunnel_pid" =~ ^[0-9]+$ ]] && kill -0 "$tunnel_pid" 2>/dev/null; then
      kill "$tunnel_pid" 2>/dev/null || true
    fi
    rm -f "$TRUST_REPO/.tunnel.pid"
  fi
  (cd "$TRUST_REPO/infra" && AWS_PROFILE="$TRUST_PROFILE" uv run cdk destroy --force)
  step_done

  session_summary
  echo ""
  echo "  ✓ Both stacks destroyed."
  echo ""
}

cmd_status() {
  local status

  echo ""
  echo "═══ Trust Account (${TRUST_PROFILE}) ═══"
  echo ""

  status=$(aws cloudformation describe-stacks --stack-name NorthshireTrustStack \
    --query 'Stacks[0].StackStatus' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT DEPLOYED")
  printf "  %-28s %s\n" "NorthshireTrustStack" "$status"

  status=$(aws rds describe-db-instances \
    --query 'DBInstances[?starts_with(DBInstanceIdentifier,`northshire`)].DBInstanceStatus|[0]' \
    --output text --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  printf "  %-28s %s\n" "RDS (northshire)" "$status"

  status=$(aws transfer list-servers \
    --query 'Servers[0].State' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  local sftp_type
  sftp_type=$(aws transfer list-servers \
    --query 'Servers[0].EndpointType' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "?")
  printf "  %-28s %s (%s)\n" "SFTP Server" "$status" "$sftp_type"

  echo ""
  echo "═══ Platform Account (${CDK_ENV}) ═══"
  echo ""

  for stack in lake secrets catalog ecr ingestion-role network observability compute; do
    status=$(aws cloudformation describe-stacks --stack-name "${stack}-access-iq-${CDK_ENV}" \
      --query 'Stacks[0].StackStatus' --output text \
      --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT DEPLOYED")
    printf "  %-28s %s\n" "$stack" "$status"
  done

  echo ""
  echo "═══ Connectivity ═══"
  echo ""

  status=$(aws ec2 describe-vpc-peering-connections \
    --filters "Name=status-code,Values=active" \
    --query 'VpcPeeringConnections[0].{Id:VpcPeeringConnectionId,Status:Status.Code}' \
    --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  printf "  %-28s %s\n" "VPC Peering" "$status"

  local cluster_status
  cluster_status=$(aws ecs describe-clusters \
    --clusters "access-iq-${CDK_ENV}-ingestion" \
    --query 'clusters[0].status' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  printf "  %-28s %s\n" "ECS Cluster" "$cluster_status"

  local running_tasks
  running_tasks=$(aws ecs list-tasks \
    --cluster "access-iq-${CDK_ENV}-ingestion" \
    --query 'taskArns | length(@)' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "0")
  printf "  %-28s %s\n" "Running ECS Tasks" "$running_tasks"

  echo ""
}

cmd_ingest() {
  echo ""
  echo "  Launching 3 ingestion tasks in parallel (D-07)"
  echo "  Cluster: access-iq-${CDK_ENV}-ingestion"
  echo ""

  # ── Step 0: Assume the ECS operator role (control-plane only) ──
  step_start "0/4" "Assume ECS operator role" "<5s"

  local OPERATOR_ROLE_ARN
  OPERATOR_ROLE_ARN=$(platform_output "ingestion-role" "EcsOperatorRoleArn")

  local STS_OUTPUT
  STS_OUTPUT=$(aws sts assume-role \
    --role-arn "$OPERATOR_ROLE_ARN" \
    --role-session-name "ecs-operator-$(date +%s)" \
    --duration-seconds 3600 \
    --profile "$AWS_PROFILE" --region "$REGION" \
    --output json)

  export AWS_ACCESS_KEY_ID=$(echo "$STS_OUTPUT" | jq -r '.Credentials.AccessKeyId')
  export AWS_SECRET_ACCESS_KEY=$(echo "$STS_OUTPUT" | jq -r '.Credentials.SecretAccessKey')
  export AWS_SESSION_TOKEN=$(echo "$STS_OUTPUT" | jq -r '.Credentials.SessionToken')
  unset AWS_PROFILE

  echo "  Assumed: $(echo "$STS_OUTPUT" | jq -r '.AssumedRoleUser.Arn')"
  step_done

  # ── Step 1: Resolve runtime values from CloudFormation outputs ──
  step_start "1/4" "Resolve cluster and network config" "<5s"

  local CLUSTER_NAME
  CLUSTER_NAME=$(aws cloudformation describe-stacks \
    --stack-name "compute-access-iq-${CDK_ENV}" \
    --query "Stacks[0].Outputs[?OutputKey==\`ClusterName\`].OutputValue" \
    --output text --region "$REGION")

  # Resolve private subnet IDs from VPC
  local VPC_ID
  VPC_ID=$(aws ec2 describe-vpcs \
    --filters "Name=tag:Name,Values=access-iq-${CDK_ENV}-platform" \
    --query 'Vpcs[0].VpcId' --output text \
    --region "$REGION")

  local SUBNET_IDS
  SUBNET_IDS=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:aws-cdk:subnet-type,Values=Private" \
    --query 'Subnets[*].SubnetId' --output text \
    --region "$REGION" | tr '\t' ',')

  local SG_ID
  SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=*ecs-task*" \
    --query 'SecurityGroups[0].GroupId' --output text \
    --region "$REGION")

  echo "  Cluster:  $CLUSTER_NAME"
  echo "  Subnets:  $SUBNET_IDS"
  echo "  SG:       $SG_ID"
  step_done

  # ── Step 2: Launch all 3 tasks in parallel ──
  step_start "2/4" "Launch ECS tasks" "<10s"

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
        --region "$REGION"
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
  step_start "3/4" "Wait for completion" "2-10 min"

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
        --region "$REGION")
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
      --region "$REGION")

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
  up)     shift; cmd_up "$@" ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  ingest) cmd_ingest ;;
  *)
    echo "Usage: $0 {up|down|status|ingest}"
    echo ""
    echo "  up [flags]            Deploy Trust + Platform stacks with peering (~10 min)"
    echo "                        --skip-generate: reuse existing data/staging/ instead of regenerating"
    echo "                        --skip-seed:     deploy infrastructure only, no data seeding"
    echo "  down                  Destroy Platform + Trust stacks (~8 min)"
    echo "  status                Show current stack states"
    echo "  ingest                Run all 3 Bronze ingestion tasks on ECS (~5 min)"
    exit 1
    ;;
esac
