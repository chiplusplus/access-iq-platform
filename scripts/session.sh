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
  echo "  Deploy sequence: Trust bootstrap → Platform → Redshift pre-warm → Trust (routes + SGs) → Secrets → Docker → Ingest → dbt Spectrum"
  [ -n "$skip_generate" ] && echo "  Skipping data generation (reusing existing data/staging/)"
  [ "$skip_seed" = true ] && echo "  Skipping data seeding (deploy infrastructure only)"
  echo "  Estimated total: 20-35 minutes"
  echo ""

  step_start "1/8" "Bootstrap Trust environment (deploy + DB + data)" "8-12 min"
  if [ "$skip_seed" = true ]; then
    (cd "$TRUST_REPO/infra" && unset VIRTUAL_ENV && . "$TRUST_REPO/.northshire-hospital-sim/bin/activate" \
      && AWS_PROFILE="$TRUST_PROFILE" cdk deploy --outputs-file cdk-outputs.json \
      --profile "$TRUST_PROFILE" --require-approval never)
  else
    (cd "$TRUST_REPO" && unset VIRTUAL_ENV && AWS_PROFILE="$TRUST_PROFILE" make trust-bootstrap \
      ARGS="--profile $TRUST_PROFILE $skip_generate")
  fi
  step_done

  step_start "2/8" "Read Trust outputs" "<5s"
  TRUST_VPC=$(trust_output VpcId)
  echo "  Trust VPC: $TRUST_VPC"
  step_done

  step_start "3/8" "Deploy Platform stacks" "5-10min"

  local CDK_CONTEXT_ARGS="-c env=$CDK_ENV -c trust_vpc_id=$TRUST_VPC"

  (cd "$PLATFORM_REPO/infra" && AWS_PROFILE="$AWS_PROFILE" uv run cdk deploy --all \
    $CDK_CONTEXT_ARGS --require-approval never)

  # Export BRONZE_S3_PREFIX for dbt
  local PLATFORM_BUCKET
  PLATFORM_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "lake-access-iq-${CDK_ENV}" \
    --query "Stacks[0].Outputs[?OutputKey==\`BucketName\`].OutputValue" \
    --output text --profile "$AWS_PROFILE" --region "$REGION")
  export BRONZE_S3_PREFIX="s3://${PLATFORM_BUCKET}/bronze"
  echo "  BRONZE_S3_PREFIX=${BRONZE_S3_PREFIX}"

  step_done

  step_start "4/8" "Create Spectrum external schema + pre-warm Redshift" "30-60s"

  local RS_WORKGROUP="access-iq-${CDK_ENV}"
  local RS_DB="dev"

  # Wait for workgroup to be AVAILABLE (may take 30-60s after CDK deploy)
  local rs_status="CREATING"
  local wait_count=0
  while [ "$rs_status" != "AVAILABLE" ] && [ "$wait_count" -lt 30 ]; do
    rs_status=$(aws redshift-serverless get-workgroup \
      --workgroup-name "$RS_WORKGROUP" \
      --query 'workgroup.status' --output text \
      --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT_FOUND")
    if [ "$rs_status" != "AVAILABLE" ]; then
      sleep 10
      wait_count=$((wait_count + 1))
      echo "    Waiting for workgroup... ($rs_status)"
    fi
  done

  if [ "$rs_status" = "AVAILABLE" ]; then
    local SPECTRUM_ROLE_ARN
    SPECTRUM_ROLE_ARN=$(aws cloudformation describe-stacks \
      --stack-name "warehouse-access-iq-${CDK_ENV}" \
      --query "Stacks[0].Outputs[?OutputKey=='SpectrumRoleArn'].OutputValue" \
      --output text --profile "$AWS_PROFILE" --region "$REGION")
    local GLUE_DB="access-iq-${CDK_ENV}-bronze"

    local RS_SECRET_ARN
    RS_SECRET_ARN=$(aws redshift-serverless get-namespace \
      --namespace-name "$RS_WORKGROUP" \
      --query 'namespace.adminPasswordSecretArn' \
      --output text --profile "$AWS_PROFILE" --region "$REGION")

    SPECTRUM_STMT_ID=""
    SPECTRUM_STMT_ID=$(aws redshift-data execute-statement \
      --workgroup-name "$RS_WORKGROUP" \
      --database "$RS_DB" \
      --secret-arn "$RS_SECRET_ARN" \
      --sql "CREATE EXTERNAL SCHEMA IF NOT EXISTS bronze_external FROM DATA CATALOG DATABASE '${GLUE_DB}' IAM_ROLE '${SPECTRUM_ROLE_ARN}' REGION '${REGION}'; GRANT USAGE ON SCHEMA bronze_external TO PUBLIC; GRANT SELECT ON ALL TABLES IN SCHEMA bronze_external TO PUBLIC;" \
      --query 'Id' --output text \
      --profile "$AWS_PROFILE" --region "$REGION")
    echo "  Spectrum schema statement submitted (will verify at end)"
  else
    echo "  WARNING: Redshift workgroup not available after 5 min -- skipping pre-warm"
  fi

  step_done

  PLATFORM_VPC=$(aws ec2 describe-vpcs \
    --filters "Name=tag:Name,Values=access-iq-${CDK_ENV}-platform" \
    --query 'Vpcs[0].VpcId' --output text \
    --profile "$AWS_PROFILE" --region "$REGION")

  PEERING_ID=$(aws cloudformation describe-stacks \
    --stack-name "network-access-iq-${CDK_ENV}" \
    --query "Stacks[0].Outputs[?OutputKey==\`PeeringConnectionId\`].OutputValue" \
    --output text --profile "$AWS_PROFILE" --region "$REGION")

  step_start "5/8" "Redeploy Trust with routes and peering SG rules" "~2 min"
  echo "  Platform VPC:  $PLATFORM_VPC"
  echo "  Peering ID:    $PEERING_ID"
  (cd "$TRUST_REPO/infra" && AWS_PROFILE="$TRUST_PROFILE" uv run cdk deploy \
    -c "platformVpcId=$PLATFORM_VPC" \
    -c "platformCidr=10.10.0.0/16" \
    -c "platformAccountId=$(aws sts get-caller-identity --query Account --output text --profile "$AWS_PROFILE")" \
    -c "peeringConnectionId=$PEERING_ID" \
    --require-approval never)
  step_done

  # ── Step 7: Seed Platform secrets from Trust outputs ──
  step_start "6/8" "Seed Platform secrets from Trust" "<30s"

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

  # Write .env for local tools (profiling, readiness gate) that use pydantic Settings.
  # ECS tasks get these from Secrets Manager; locally we use .env (gitignored).
  local TRUST_BUCKET
  TRUST_BUCKET=$(trust_output ExternalBucketName 2>/dev/null || echo "northshire-trust-external-exports")

  cat > "$PLATFORM_REPO/.env" <<EOF
ACCESS_IQ_ENV=${CDK_ENV}
ACCESS_IQ_AWS_REGION=${REGION}
ACCESS_IQ_PLATFORM_BUCKET=${PLATFORM_BUCKET}
ACCESS_IQ_AWS_PROFILE=${AWS_PROFILE}
ACCESS_IQ_POSTGRES_SOURCES={"ehr_postgres": {"dsn_env": "EHR_DSN", "tables": ["patient_demographics","encounters","referrals","diagnoses"]}, "urgent_care_postgres": {"dsn_env": "URGENT_CARE_DSN", "tables": ["urgent_care_logs"]}}
ACCESS_IQ_SFTP_SOURCES={"appointments": {"host_env":"SFTP_HOST","port_env":"SFTP_PORT","user_env":"SFTP_USER","private_key_env":"SFTP_PRIVATE_KEY","remote_dir":"/outbound/appointments/","source_name":"sftp_appointments"}}
ACCESS_IQ_TRUST_S3={"base":{"bucket":"${TRUST_BUCKET}","profile":"${AWS_PROFILE}"},"diagnostics":{"prefix_root":"diagnostics","source_name":"trust_s3_diagnostics"},"provider_ref":{"key":"providers/sites_and_services_master.xlsx","source_name":"trust_s3_provider_ref"}}
EHR_DSN=${EHR_DSN}
URGENT_CARE_DSN=${URGENT_DSN}
SFTP_HOST=${SFTP_ENDPOINT}
SFTP_PORT=22
SFTP_USER=${SFTP_USER_VAL}
SFTP_PRIVATE_KEY=${SFTP_PRIVATE_KEY_VAL}
EOF
  echo "  ✓ .env written (${#PLATFORM_BUCKET} char bucket, all runtime vars)"

  # ── Step 8: Build and push Docker image to ECR ──
  step_start "7/8" "Build and push ingestion image to ECR" "1-3 min"

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

  # ── Step 7: Run Bronze ingestion (all 3 sources) ──
  cmd_ingest

  # cmd_ingest assumes an STS role and unsets AWS_PROFILE; restore it.
  AWS_PROFILE="${AWS_PROFILE:-CHI-Engineer-222308823356}"

  # Verify Spectrum schema creation completed (submitted in step 4/7).
  if [ -n "${SPECTRUM_STMT_ID:-}" ]; then
    local saved_profile="${AWS_PROFILE:-CHI-Engineer-222308823356}"
    local stmt_status="SUBMITTED"
    while [ "$stmt_status" != "FINISHED" ] && [ "$stmt_status" != "FAILED" ]; do
      sleep 2
      stmt_status=$(aws redshift-data describe-statement --id "$SPECTRUM_STMT_ID" \
        --query 'Status' --output text \
        --profile "$saved_profile" --region "$REGION")
    done
    if [ "$stmt_status" = "FINISHED" ]; then
      echo "  ✓ Spectrum external schema ready"
    else
      echo "  WARNING: Spectrum schema creation failed — run CREATE EXTERNAL SCHEMA manually"
    fi
  fi

  # ── Step 8: Start tunnel, create Spectrum tables + partitions ──
  step_start "8/8" "Create Spectrum external tables and register partitions" "30-60s"

  local TUNNEL_PID_FILE="$PLATFORM_REPO/.tunnel.pid"
  local TUNNEL_INSTANCE_ID
  TUNNEL_INSTANCE_ID=$(platform_output warehouse TunnelInstanceId)
  local RS_ENDPOINT
  RS_ENDPOINT=$(platform_output warehouse WorkgroupEndpoint)

  # Start SSM tunnel in background
  aws ssm start-session \
    --target "$TUNNEL_INSTANCE_ID" \
    --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters "{\"host\":[\"${RS_ENDPOINT}\"],\"portNumber\":[\"5439\"],\"localPortNumber\":[\"5439\"]}" \
    --profile "$AWS_PROFILE" --region "$REGION" &
  local tunnel_pid=$!
  echo "$tunnel_pid" > "$TUNNEL_PID_FILE"
  echo "  Tunnel PID: $tunnel_pid (saved to .tunnel.pid)"

  # Wait for tunnel to be ready
  local tunnel_ready=false
  for i in $(seq 1 15); do
    if nc -z localhost 5439 2>/dev/null; then
      tunnel_ready=true
      break
    fi
    sleep 2
  done

  if [ "$tunnel_ready" = true ]; then
    echo "  ✓ Tunnel connected"

    # Load Redshift credentials
    eval "$("$PLATFORM_REPO/scripts/tunnel.sh" env)"

    # Create external tables via dbt-external-tables
    (cd "$PLATFORM_REPO/dbt" && uv run dbt run-operation stage_external_sources --profiles-dir .) \
      && echo "  ✓ Spectrum external tables created" \
      || echo "  WARNING: stage_external_sources failed — run manually via make dbt"

    # Register partitions
    (cd "$PLATFORM_REPO/dbt" && uv run dbt run-operation add_spectrum_partitions --profiles-dir .) \
      && echo "  ✓ Partitions registered" \
      || echo "  WARNING: add_spectrum_partitions failed — run manually via make dbt"
  else
    echo "  WARNING: Tunnel not ready after 30s — skipping dbt operations"
    echo "  Run manually: make tunnel (terminal 1), make dbt CMD=\"run-operation stage_external_sources\" (terminal 2)"
  fi

  step_done

  session_summary
  echo ""
  echo "  ✓ All stacks deployed, secrets seeded, image pushed, ingestion complete."
  echo "  ✓ SSM tunnel running on localhost:5439 (PID $(cat "$TUNNEL_PID_FILE" 2>/dev/null || echo 'unknown'))"
  echo "    Run dbt commands: make dbt CMD=\"...\""
  echo "    Stop tunnel: make down (or kill $(cat "$TUNNEL_PID_FILE" 2>/dev/null || echo 'PID'))"
  echo ""
}

cmd_down() {
  echo ""
  echo "  Destroy sequence: Platform → Trust (no cross-account dependencies)"
  echo "  Estimated total: 6-10 minutes"
  echo ""

  TRUST_VPC=$(trust_output VpcId 2>/dev/null || echo "vpc-placeholder")

  # Kill Redshift SSM tunnel if running
  local RS_TUNNEL_PID_FILE="$PLATFORM_REPO/.tunnel.pid"
  if [ -f "$RS_TUNNEL_PID_FILE" ]; then
    local rs_tunnel_pid
    rs_tunnel_pid="$(cat "$RS_TUNNEL_PID_FILE" 2>/dev/null || true)"
    if [[ "$rs_tunnel_pid" =~ ^[0-9]+$ ]] && kill -0 "$rs_tunnel_pid" 2>/dev/null; then
      kill "$rs_tunnel_pid" 2>/dev/null || true
      echo "  ✓ Killed Redshift tunnel (PID $rs_tunnel_pid)"
    fi
    rm -f "$RS_TUNNEL_PID_FILE"
  fi

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

  for stack in lake secrets catalog ecr ingestion-role network observability compute warehouse; do
    status=$(aws cloudformation describe-stacks --stack-name "${stack}-access-iq-${CDK_ENV}" \
      --query 'Stacks[0].StackStatus' --output text \
      --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT DEPLOYED")
    printf "  %-28s %s\n" "$stack" "$status"
  done

  local rs_status
  rs_status=$(aws redshift-serverless get-workgroup \
    --workgroup-name "access-iq-${CDK_ENV}" \
    --query 'workgroup.status' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  printf "  %-28s %s\n" "Redshift Workgroup" "$rs_status"

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

cmd_cleanup_snapshots() {
  local RS_NAMESPACE="access-iq-${CDK_ENV}"
  local KEEP_COUNT="${1:-2}"  # Keep the N most recent snapshots, default 2

  echo "Cleaning up old Redshift snapshots for namespace: $RS_NAMESPACE"
  echo "  Keeping $KEEP_COUNT most recent snapshots"

  local ALL_SNAPSHOTS
  ALL_SNAPSHOTS=$(aws redshift-serverless list-snapshots \
    --namespace-name "$RS_NAMESPACE" \
    --query 'snapshots | sort_by(@, &snapshotCreateTime) | [*].snapshotName' \
    --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null)

  if [ -z "$ALL_SNAPSHOTS" ] || [ "$ALL_SNAPSHOTS" = "None" ]; then
    echo "  No snapshots found."
    return 0
  fi

  local SNAPSHOT_COUNT
  SNAPSHOT_COUNT=$(echo "$ALL_SNAPSHOTS" | wc -w | tr -d ' ')

  if [ "$SNAPSHOT_COUNT" -le "$KEEP_COUNT" ]; then
    echo "  Only $SNAPSHOT_COUNT snapshot(s) found, nothing to clean up."
    return 0
  fi

  local DELETE_COUNT=$((SNAPSHOT_COUNT - KEEP_COUNT))
  echo "  Found $SNAPSHOT_COUNT snapshots, deleting $DELETE_COUNT oldest..."

  local i=0
  for snap in $ALL_SNAPSHOTS; do
    if [ "$i" -ge "$DELETE_COUNT" ]; then
      break
    fi
    echo "    Deleting: $snap"
    aws redshift-serverless delete-snapshot \
      --snapshot-name "$snap" \
      --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || true
    i=$((i + 1))
  done

  echo "  Cleanup complete. Kept $KEEP_COUNT most recent snapshots."
}

# ── Main ──────────────────────────────────────────────────────────────

case "${1:-}" in
  up)                shift; cmd_up "$@" ;;
  down)              cmd_down ;;
  status)            cmd_status ;;
  ingest)            cmd_ingest ;;
  cleanup-snapshots) shift; cmd_cleanup_snapshots "$@" ;;
  *)
    echo "Usage: $0 {up|down|status|ingest|cleanup-snapshots}"
    echo ""
    echo "  up [flags]            Deploy Trust + Platform, publish data, run ingestion (~25 min)"
    echo "                        --skip-generate: reuse existing data/staging/ instead of regenerating"
    echo "                        --skip-seed:     deploy infrastructure only, no data seeding"
    echo "  down                  Destroy Platform + Trust stacks (~8 min)"
    echo "  status                Show current stack states"
    echo "  ingest                Run all 3 Bronze ingestion tasks on ECS (~5 min)"
    echo "  cleanup-snapshots [N] Delete old Redshift snapshots, keep N most recent (default 2)"
    exit 1
    ;;
esac
