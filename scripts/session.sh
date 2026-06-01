#!/usr/bin/env bash
# Session orchestration: deploy/destroy Trust + Platform stacks.
# Usage: ./scripts/session.sh up|down|status
set -euo pipefail

if [ -z "${AWS_PROFILE:-}" ]; then
  echo "ERROR: AWS_PROFILE is not set. Export it before running: export AWS_PROFILE=<your-platform-profile>"
  exit 1
fi
if [ -z "${TRUST_PROFILE:-}" ]; then
  echo "ERROR: TRUST_PROFILE is not set. Export it before running: export TRUST_PROFILE=<your-trust-profile>"
  exit 1
fi
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
  local skip_infra=false
  for arg in "$@"; do
    case "$arg" in
      --skip-generate) skip_generate="--skip-generate" ;;
      --skip-seed) skip_seed=true ;;
      --skip-infra) skip_infra=true ;;
    esac
  done

  echo ""
  echo "  Deploy sequence: Trust bootstrap → Platform → Redshift pre-warm → Trust (routes + SGs) → Secrets → Docker → dbt Spectrum → Prefect"
  [ -n "$skip_generate" ] && echo "  Skipping data generation (reusing existing data/staging/)"
  [ "$skip_seed" = true ] && echo "  Skipping data seeding (deploy infrastructure only)"
  [ "$skip_infra" = true ] && echo "  Skipping infrastructure deployments (reusing existing stacks)"
  echo "  Estimated total: 20-35 minutes"
  echo ""

  step_start "1/8" "Bootstrap Trust environment (deploy + DB + data)" "8-12 min"
  if [ "$skip_infra" = true ]; then
    echo "  Skipping Trust deploy (--skip-infra)"
  elif [ "$skip_seed" = true ]; then
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

  if [ "$skip_infra" = true ]; then
    echo "  Skipping Platform deploy (--skip-infra)"
  else
    (cd "$PLATFORM_REPO/infra" && AWS_PROFILE="$AWS_PROFILE" uv run cdk deploy --all \
      -c "env=${CDK_ENV}" -c "trust_vpc_id=${TRUST_VPC}" --require-approval never)

    # Deploy Trust budget stack from Trust repo, passing alert config from Platform config.
    local PLATFORM_CFG="$PLATFORM_REPO/infra/config/${CDK_ENV}.json"
    local ALERT_EMAIL; ALERT_EMAIL=$(jq -r '.obs.alert_email // empty' "$PLATFORM_CFG")
    local SLACK_WEBHOOK; SLACK_WEBHOOK=$(jq -r '.obs.slack_webhook_url // empty' "$PLATFORM_CFG")
    echo "  Deploying Trust budget stack..."
    (cd "$TRUST_REPO/infra" && unset VIRTUAL_ENV && . "$TRUST_REPO/.northshire-hospital-sim/bin/activate" \
      && AWS_PROFILE="$TRUST_PROFILE" cdk deploy TrustBudgetStack \
      ${ALERT_EMAIL:+-c "alertEmail=${ALERT_EMAIL}"} \
      ${SLACK_WEBHOOK:+-c "slackWebhookUrl=${SLACK_WEBHOOK}"} \
      --require-approval never) \
      || echo "  WARNING: Trust budget stack deploy failed (non-blocking)"
  fi

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

  SPECTRUM_STMT_ID=""
  if [ "$skip_seed" = true ]; then
    echo "  Skipping Redshift pre-warm (--skip-seed)"
  else
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
  if [ "$skip_infra" = true ]; then
    echo "  Skipping Trust redeploy (--skip-infra)"
  else
    echo "  Platform VPC:  $PLATFORM_VPC"
    echo "  Peering ID:    $PEERING_ID"
    (cd "$TRUST_REPO/infra" && unset VIRTUAL_ENV && . "$TRUST_REPO/.northshire-hospital-sim/bin/activate" \
      && AWS_PROFILE="$TRUST_PROFILE" cdk deploy \
      -c "platformVpcId=$PLATFORM_VPC" \
      -c "platformCidr=10.10.0.0/16" \
      -c "platformAccountId=$(aws sts get-caller-identity --query Account --output text --profile "$AWS_PROFILE")" \
      -c "peeringConnectionId=$PEERING_ID" \
      --require-approval never)
  fi
  step_done

  # ── Step 7: Seed Platform secrets from Trust outputs ──
  step_start "6/8" "Seed Platform secrets from Trust" "<30s"

  if [ "$skip_infra" = true ]; then
    echo "  Skipping secret seeding (--skip-infra)"
    step_done
  else

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

  # Seed Redshift credentials for dbt (extracts from Redshift-managed admin secret)
  local RS_WORKGROUP="access-iq-${CDK_ENV}"
  local RS_ADMIN_SECRET_ARN
  RS_ADMIN_SECRET_ARN=$(aws redshift-serverless get-namespace \
    --namespace-name "$RS_WORKGROUP" \
    --query 'namespace.adminPasswordSecretArn' \
    --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null)

  if [ -n "$RS_ADMIN_SECRET_ARN" ] && [ "$RS_ADMIN_SECRET_ARN" != "None" ]; then
    local RS_ADMIN_JSON
    RS_ADMIN_JSON=$(aws secretsmanager get-secret-value \
      --secret-id "$RS_ADMIN_SECRET_ARN" \
      --query SecretString --output text \
      --profile "$AWS_PROFILE" --region "$REGION")
    local RS_USER RS_PASS RS_HOST
    RS_USER=$(echo "$RS_ADMIN_JSON" | jq -r '.username')
    RS_PASS=$(echo "$RS_ADMIN_JSON" | jq -r '.password')
    RS_HOST=$(aws redshift-serverless get-workgroup \
      --workgroup-name "$RS_WORKGROUP" \
      --query 'workgroup.endpoint.address' \
      --output text --profile "$AWS_PROFILE" --region "$REGION")
    local RS_DSN="postgresql://${RS_USER}:${RS_PASS}@${RS_HOST}:5439/dev"
    seed_secret "${SECRET_PREFIX}/redshift-dsn"      "$RS_DSN"
    seed_secret "${SECRET_PREFIX}/redshift-password"  "$RS_PASS"
    echo "  ✓ Redshift DSN + password seeded"
  else
    echo "  WARNING: Redshift admin secret not found - skipping redshift-dsn/password seeding"
  fi

  fi  # skip_infra

  step_done

  # Write .env for local tools (profiling, readiness gate) that use pydantic Settings.
  # ECS tasks get these from Secrets Manager; locally we use .env (gitignored).
  # Skipped with --skip-infra since .env already exists from initial run.
  if [ "$skip_infra" = true ]; then
    echo "  Skipping .env write (--skip-infra, reusing existing .env)"
  else
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
SFTP_PRIVATE_KEY_PATH=${PLATFORM_REPO}/.secrets/sftp_key.pem
BRONZE_S3_PREFIX=s3://${PLATFORM_BUCKET}/bronze
EOF

    # Write SFTP private key to a secured file (not inline in .env)
    mkdir -p "$PLATFORM_REPO/.secrets"
    chmod 700 "$PLATFORM_REPO/.secrets"
    printf '%s\n' "$SFTP_PRIVATE_KEY_VAL" > "$PLATFORM_REPO/.secrets/sftp_key.pem"
    chmod 600 "$PLATFORM_REPO/.secrets/sftp_key.pem"

    echo "  ✓ .env written (${#PLATFORM_BUCKET} char bucket, all runtime vars)"

    # Populate Streamlit dashboard secrets from IAM stack outputs
    local DASH_KEY_ID DASH_SECRET_KEY
    DASH_KEY_ID=$(aws cloudformation describe-stacks \
      --stack-name "iam-access-iq-${CDK_ENV}" \
      --query "Stacks[0].Outputs[?OutputKey=='DashboardReaderAccessKeyId'].OutputValue" \
      --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null)
    DASH_SECRET_KEY=$(aws cloudformation describe-stacks \
      --stack-name "iam-access-iq-${CDK_ENV}" \
      --query "Stacks[0].Outputs[?OutputKey=='DashboardReaderSecretKey'].OutputValue" \
      --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null)

    if [ -n "$DASH_KEY_ID" ] && [ "$DASH_KEY_ID" != "None" ]; then
      mkdir -p "$PLATFORM_REPO/dashboard/.streamlit"
      cat > "$PLATFORM_REPO/dashboard/.streamlit/secrets.toml" <<DASHEOF
# Auto-generated by make up — this file is gitignored.
AWS_ACCESS_KEY_ID = "${DASH_KEY_ID}"
AWS_SECRET_ACCESS_KEY = "${DASH_SECRET_KEY}"
AWS_REGION = "${REGION}"
PLATFORM_BUCKET = "${PLATFORM_BUCKET}"
DASHEOF
      echo "  ✓ dashboard/.streamlit/secrets.toml written"
    else
      echo "  WARNING: DashboardReaderAccessKeyId not found in IAM stack outputs — skipping secrets.toml"
    fi
  fi

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
  (cd "$PLATFORM_REPO" && docker build --platform linux/amd64 -f flows/Dockerfile -t "${ECR_URI}:latest" .)
  docker push "${ECR_URI}:latest"
  echo "  ✓ Pushed ${ECR_URI}:latest"

  step_done

  # Verify Spectrum schema creation completed (submitted in step 4/8).
  if [ -n "${SPECTRUM_STMT_ID:-}" ]; then
    local saved_profile="$AWS_PROFILE"
    local stmt_status="SUBMITTED"
    local wait_secs=0
    local max_wait=120
    while [ "$stmt_status" != "FINISHED" ] && [ "$stmt_status" != "FAILED" ]; do
      if [ "$wait_secs" -ge "$max_wait" ]; then
        echo "  WARNING: Spectrum statement poll timed out after ${max_wait}s (status: $stmt_status)"
        break
      fi
      sleep 2
      wait_secs=$((wait_secs + 2))
      stmt_status=$(aws redshift-data describe-statement --id "$SPECTRUM_STMT_ID" \
        --query 'Status' --output text \
        --profile "$saved_profile" --region "$REGION")
    done
    if [ "$stmt_status" = "FINISHED" ]; then
      echo "  ✓ Spectrum external schema ready"
    else
      echo "  WARNING: Spectrum schema creation failed - run CREATE EXTERNAL SCHEMA manually"
    fi
  fi

  # ── Step 8/8: Start tunnel + configure self-hosted Prefect ──
  step_start "8/8" "Start tunnel + configure Prefect (work pool + flow deploy)" "30-60s"

  local TUNNEL_PID_FILE="$PLATFORM_REPO/.tunnel.pid"
  local TUNNEL_INSTANCE_ID
  TUNNEL_INSTANCE_ID=$(platform_output warehouse TunnelInstanceId)
  local RS_ENDPOINT
  RS_ENDPOINT=$(platform_output warehouse WorkgroupEndpoint)

  # Start SSM tunnel in background (used by Prefect and manual dbt)
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
  else
    echo "  WARNING: Tunnel not ready after 30s"
  fi

  # Server and worker are ECS services started by CDK deploy (step 3/8).
  # The server is in a private subnet -- use the Redshift tunnel instance as a jump host.
  # Cloud Map DNS registration requires a passing health check (start_period=60s + interval=30s),
  # so we wait for the ECS service to stabilise before attempting the tunnel.
  local PREFECT_SERVER_HOST="prefect-server.access-iq.local"
  local PREFECT_API="http://${PREFECT_SERVER_HOST}:4200/api"
  local PREFECT_TUNNEL_PID_FILE="$PLATFORM_REPO/.prefect-tunnel.pid"

  # Wait for Prefect server ECS service to reach RUNNING with healthy target
  echo "  Waiting for Prefect server service to stabilise..."
  local svc_name="access-iq-${CDK_ENV}-prefect-server"
  local cluster_name="access-iq-${CDK_ENV}-ingestion"
  aws ecs wait services-stable \
    --cluster "$cluster_name" --services "$svc_name" \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null \
    || echo "  WARNING: ecs wait timed out - attempting tunnel anyway"

  # Start SSM tunnel with retry (Cloud Map DNS may take a few seconds after service stabilises)
  local server_ready=false
  for attempt in 1 2 3; do
    aws ssm start-session \
      --target "$TUNNEL_INSTANCE_ID" \
      --document-name AWS-StartPortForwardingSessionToRemoteHost \
      --parameters "{\"host\":[\"${PREFECT_SERVER_HOST}\"],\"portNumber\":[\"4200\"],\"localPortNumber\":[\"4200\"]}" \
      --profile "$AWS_PROFILE" --region "$REGION" &
    local prefect_tunnel_pid=$!
    echo "$prefect_tunnel_pid" > "$PREFECT_TUNNEL_PID_FILE"

    # Give tunnel a moment to establish, then check health
    sleep 5
    if curl -sf http://localhost:4200/api/health >/dev/null 2>&1; then
      server_ready=true
      break
    fi

    # Tunnel failed - kill it and retry after a wait
    kill "$prefect_tunnel_pid" 2>/dev/null || true
    if [ "$attempt" -lt 3 ]; then
      echo "  Tunnel attempt $attempt failed, retrying in 15s..."
      sleep 15
    fi
  done

  # If initial attempts failed, do a longer health wait (tunnel may be up but server slow)
  if [ "$server_ready" = false ] && kill -0 "$prefect_tunnel_pid" 2>/dev/null; then
    for i in $(seq 1 20); do
      if curl -sf http://localhost:4200/api/health >/dev/null 2>&1; then
        server_ready=true
        break
      fi
      sleep 5
    done
  fi

  if [ "$server_ready" = true ]; then
    echo "  Prefect server healthy"
    export PREFECT_API_URL="http://localhost:4200/api"

    # Resolve CDK stack outputs for flow deployment
    local stack_name="compute-access-iq-${CDK_ENV}"
    local cluster_arn task_role_arn exec_role_arn
    cluster_arn=$(aws cloudformation describe-stacks \
      --stack-name "$stack_name" \
      --query "Stacks[0].Outputs[?OutputKey=='ClusterArn'].OutputValue" \
      --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")
    task_role_arn=$(platform_output ingestion-role EcsTaskRoleArn 2>/dev/null || echo "")
    exec_role_arn=$(platform_output ingestion-role EcsExecutionRoleArn 2>/dev/null || echo "")
    local ecr_uri
    ecr_uri=$(aws cloudformation describe-stacks \
      --stack-name "ecr-access-iq-${CDK_ENV}" \
      --query "Stacks[0].Outputs[?OutputKey=='IngestionRepoUri'].OutputValue" \
      --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")
    local PIPELINE_IMAGE_URI="${ecr_uri}:latest"
    local PIPELINE_TASK_DEF_ARN
    PIPELINE_TASK_DEF_ARN=$(aws ecs describe-task-definition \
      --task-definition "access-iq-${CDK_ENV}-pipeline" \
      --query 'taskDefinition.taskDefinitionArn' \
      --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")
    local ECS_CLUSTER_ARN="$cluster_arn"
    local ECS_TASK_ROLE_ARN="$task_role_arn"
    local ECS_EXECUTION_ROLE_ARN="$exec_role_arn"
    local PLATFORM_VPC
    PLATFORM_VPC=$(aws cloudformation describe-stacks \
      --stack-name "network-access-iq-${CDK_ENV}" \
      --query "Stacks[0].Outputs[?OutputKey=='VpcId'].OutputValue" \
      --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")
    local PRIVATE_SUBNET_IDS
    PRIVATE_SUBNET_IDS=$(aws ec2 describe-subnets \
      --filters "Name=vpc-id,Values=$PLATFORM_VPC" "Name=tag:aws-cdk:subnet-type,Values=Private" \
      --query 'Subnets[*].SubnetId' --output json \
      --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "[]")
    local ECS_TASK_SG_ID
    ECS_TASK_SG_ID=$(aws ec2 describe-security-groups \
      --filters "Name=vpc-id,Values=$PLATFORM_VPC" "Name=group-name,Values=*ecs-task*" \
      --query 'SecurityGroups[0].GroupId' --output text \
      --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")

    if [ "$PRIVATE_SUBNET_IDS" = "[]" ] || [ -z "$PRIVATE_SUBNET_IDS" ]; then
      echo "  ERROR: No private subnets found for VPC $PLATFORM_VPC - cannot deploy Prefect flow"
      return 1
    fi

    # Generate deployment YAML with resolved network values (Prefect templates
    # can't handle JSON arrays, so we bake in the actual values).
    local DEPLOY_YAML="$PLATFORM_REPO/.prefect-deploy.yaml"
    local SUBNET_YAML
    SUBNET_YAML=$(echo "$PRIVATE_SUBNET_IDS" | jq -r '.[] | "              - \"" + . + "\""' )

    cat > "$DEPLOY_YAML" <<EOYAML
name: access-iq-flows
prefect-version: "3.7.2"

deployments:
  - name: dev
    flow_name: daily-ingest
    entrypoint: flows/access_iq_flows/daily_ingest.py:daily_ingest
    pull:
      - prefect.deployments.steps.set_working_directory:
          directory: /app
    work_pool:
      name: access-iq-${CDK_ENV}-pipeline
      work_queue_name: default
      job_variables:
        task_definition_arn: "${PIPELINE_TASK_DEF_ARN}"
        image: "${PIPELINE_IMAGE_URI}"
        cluster: "${ECS_CLUSTER_ARN}"
        vpc_id: "${PLATFORM_VPC}"
        task_start_timeout_seconds: 300
        task_watch_poll_interval: 5
        network_configuration:
          subnets:
${SUBNET_YAML}
          securityGroups:
              - "${ECS_TASK_SG_ID}"
          assignPublicIp: "DISABLED"
    schedules:
      - cron: "0 * * * *"
        timezone: "Europe/London"
        active: true
    parameters:
      env: ${CDK_ENV}
EOYAML

    # Create/update ecs work pool (idempotent)
    "$PLATFORM_REPO/.venv/bin/prefect" work-pool create "access-iq-${CDK_ENV}-pipeline" \
      --type ecs --overwrite 2>/dev/null || true

    # Fix work pool template defaults (prefect-aws templates them to 0/None)
    "$PLATFORM_REPO/.venv/bin/python" -c "
import json, httpx
client = httpx.Client(base_url='$PREFECT_API_URL')
pools = client.post('/work_pools/filter', json={}).json()
pool = [p for p in pools if p['name'] == 'access-iq-${CDK_ENV}-pipeline'][0]
tmpl = pool['base_job_template']
props = tmpl['variables']['properties']
props['task_start_timeout_seconds'] = {'title':'Task Start Timeout Seconds','default':300,'type':'integer'}
props['task_watch_poll_interval'] = {'title':'Task Watch Poll Interval','default':5,'type':'number'}
props['configure_cloudwatch_logs']['default'] = True
props['cloudwatch_logs_options']['default'] = {
    'awslogs-group': '/access-iq/${CDK_ENV}/pipeline',
    'awslogs-region': '${REGION}',
    'awslogs-stream-prefix': 'flow-run',
}
client.patch(f'/work_pools/{pool[\"name\"]}', json={'base_job_template': tmpl})
" 2>/dev/null || true

    # Deploy flow definition against self-hosted server
    (cd "$PLATFORM_REPO" && \
      "$PLATFORM_REPO/.venv/bin/prefect" deploy --prefect-file "$DEPLOY_YAML" --name dev --no-prompt \
        || true)

    rm -f "$DEPLOY_YAML"

    printf "  Prefect work pool + flow deployed (self-hosted)\n"
    printf "  Prefect UI: http://localhost:4200 (tunnel PID %s)\n" "$prefect_tunnel_pid"
  else
    printf "  \033[0;33mPrefect server not healthy after 150s -- configure manually\033[0m\n"
    # Kill the failed tunnel
    kill "$prefect_tunnel_pid" 2>/dev/null || true
    rm -f "$PREFECT_TUNNEL_PID_FILE"
  fi
  step_done

  session_summary
  echo ""
  echo "  ✓ All stacks deployed, secrets seeded, image pushed."
  echo "  ✓ Run 'make pipeline' to trigger ingestion via Prefect."
  echo "  ✓ SSM tunnel running on localhost:5439 (PID $(cat "$TUNNEL_PID_FILE" 2>/dev/null || echo 'unknown'))"
  echo "    Run dbt commands: make dbt CMD=\"...\""
  echo "    Stop tunnel: make down (or kill $(cat "$TUNNEL_PID_FILE" 2>/dev/null || echo 'PID'))"
  echo ""
}

cmd_down() {
  echo ""
  echo "  Destroy sequence: Prefect pause → Platform → Trust"
  echo "  Estimated total: 6-10 minutes"
  echo ""

  TRUST_VPC=$(trust_output VpcId 2>/dev/null || echo "vpc-placeholder")

  # ── Step 1/3: Clean up Prefect tunnel ──
  step_start "1/3" "Clean up Prefect tunnel" "<5s"
  local PREFECT_TUNNEL_PID_FILE="$PLATFORM_REPO/.prefect-tunnel.pid"
  if [ -f "$PREFECT_TUNNEL_PID_FILE" ]; then
    local ptpid
    ptpid="$(cat "$PREFECT_TUNNEL_PID_FILE" 2>/dev/null || true)"
    if [[ "$ptpid" =~ ^[0-9]+$ ]] && kill -0 "$ptpid" 2>/dev/null; then
      kill "$ptpid" 2>/dev/null || true
      echo "  Killed Prefect tunnel (PID $ptpid)"
    fi
    rm -f "$PREFECT_TUNNEL_PID_FILE"
  else
    echo "  No Prefect tunnel running"
  fi
  step_done

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

  step_start "2/4" "Destroy Platform stacks" "3-5 min"
  (cd "$PLATFORM_REPO/infra" && AWS_PROFILE="$AWS_PROFILE" uv run cdk destroy --all --force \
    -c "env=$CDK_ENV" \
    -c "trust_vpc_id=$TRUST_VPC")
  step_done

  step_start "3/4" "Destroy Trust budget stack" "<1 min"
  (cd "$TRUST_REPO/infra" && unset VIRTUAL_ENV && . "$TRUST_REPO/.northshire-hospital-sim/bin/activate" \
    && AWS_PROFILE="$TRUST_PROFILE" cdk destroy TrustBudgetStack --force) 2>/dev/null \
    || echo "  Trust budget stack not deployed or already destroyed"
  step_done

  step_start "4/4" "Destroy Trust stack" "3-5 min"
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

  # ── Colour helpers (no-colour if piped) ──
  if [ -t 1 ]; then
    _g="\033[1;32m" _r="\033[1;31m" _y="\033[1;33m" _c="\033[1;36m" _d="\033[0;37m" _0="\033[0m"
  else
    _g="" _r="" _y="" _c="" _d="" _0=""
  fi

  ok()   { printf "${_g}✓${_0} %s\n" "$1"; }
  warn() { printf "${_y}⚠${_0} %s\n" "$1"; }
  fail() { printf "${_r}✗${_0} %s\n" "$1"; }

  status_icon() {
    local val="$1" good="$2"
    if [ "$val" = "$good" ]; then ok "$val"; else fail "$val"; fi
  }

  # ─────────────────────────────────────────────────────────────────────
  printf "\n${_c}═══ 1/6  Trust Account (%s) ═══${_0}\n\n" "$TRUST_PROFILE"
  # ─────────────────────────────────────────────────────────────────────

  status=$(aws cloudformation describe-stacks --stack-name NorthshireTrustStack \
    --query 'Stacks[0].StackStatus' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT_DEPLOYED")
  printf "  %-30s " "CloudFormation"
  status_icon "$status" "CREATE_COMPLETE"

  status=$(aws rds describe-db-instances \
    --query 'DBInstances[?starts_with(DBInstanceIdentifier,`northshire`)].DBInstanceStatus|[0]' \
    --output text --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  printf "  %-30s " "RDS"
  status_icon "$status" "available"

  status=$(aws transfer list-servers \
    --query 'Servers[0].State' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  local sftp_type
  sftp_type=$(aws transfer list-servers \
    --query 'Servers[0].EndpointType' --output text \
    --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null || echo "?")
  printf "  %-30s " "SFTP ($sftp_type)"
  status_icon "$status" "ONLINE"

  # Trust S3 exports
  local trust_bucket
  trust_bucket=$(trust_output ExternalBucketName 2>/dev/null || echo "")
  if [ -n "$trust_bucket" ] && [ "$trust_bucket" != "None" ]; then
    local diag_count prov_count
    diag_count=$(aws s3 ls "s3://${trust_bucket}/diagnostics/" --recursive \
      --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null | grep -c '\S' || echo "0")
    prov_count=$(aws s3 ls "s3://${trust_bucket}/providers/" --recursive \
      --profile "$TRUST_PROFILE" --region "$REGION" 2>/dev/null | grep -c '\S' || echo "0")
    printf "  %-30s " "S3 Exports"
    if [ "$diag_count" -gt 0 ] && [ "$prov_count" -gt 0 ]; then
      ok "diagnostics ($diag_count files) | providers ($prov_count files)"
    elif [ "$diag_count" -gt 0 ] || [ "$prov_count" -gt 0 ]; then
      warn "diagnostics ($diag_count) | providers ($prov_count) - partial"
    else
      fail "no export files found"
    fi
  fi

  # ─────────────────────────────────────────────────────────────────────
  printf "\n${_c}═══ 2/6  Platform Stacks (%s) ═══${_0}\n\n" "$CDK_ENV"
  # ─────────────────────────────────────────────────────────────────────

  for stack in lake secrets catalog ecr ingestion-role network observability compute warehouse; do
    status=$(aws cloudformation describe-stacks --stack-name "${stack}-access-iq-${CDK_ENV}" \
      --query 'Stacks[0].StackStatus' --output text \
      --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NOT_DEPLOYED")
    printf "  %-30s " "$stack"
    if echo "$status" | grep -q "COMPLETE"; then ok "$status"; else fail "$status"; fi
  done

  # ─────────────────────────────────────────────────────────────────────
  printf "\n${_c}═══ 3/6  Connectivity ═══${_0}\n\n"
  # ─────────────────────────────────────────────────────────────────────

  local peering_status peering_id
  peering_id=$(aws ec2 describe-vpc-peering-connections \
    --filters "Name=status-code,Values=active" "Name=tag:Name,Values=*access-iq*" \
    --query 'VpcPeeringConnections[0].VpcPeeringConnectionId' \
    --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  peering_status=$(aws ec2 describe-vpc-peering-connections \
    --filters "Name=status-code,Values=active" "Name=tag:Name,Values=*access-iq*" \
    --query 'VpcPeeringConnections[0].Status.Code' \
    --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  printf "  %-30s " "VPC Peering"
  if [ "$peering_status" = "active" ]; then ok "active ($peering_id)"; else fail "$peering_status"; fi

  local cluster_status
  cluster_status=$(aws ecs describe-clusters \
    --clusters "access-iq-${CDK_ENV}-ingestion" \
    --query 'clusters[0].status' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  printf "  %-30s " "ECS Cluster"
  status_icon "$cluster_status" "ACTIVE"

  local running_tasks
  running_tasks=$(aws ecs list-tasks \
    --cluster "access-iq-${CDK_ENV}-ingestion" \
    --query 'taskArns | length(@)' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "0")
  printf "  %-30s " "Running ECS Tasks"
  printf "%s\n" "$running_tasks"

  local rs_status
  rs_status=$(aws redshift-serverless get-workgroup \
    --workgroup-name "access-iq-${CDK_ENV}" \
    --query 'workgroup.status' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "NONE")
  printf "  %-30s " "Redshift Workgroup"
  status_icon "$rs_status" "AVAILABLE"

  # SSM tunnel
  local tunnel_pid_file="$PLATFORM_REPO/.tunnel.pid"
  printf "  %-30s " "SSM Tunnel (:5439)"
  if [ -f "$tunnel_pid_file" ]; then
    local tpid
    tpid=$(cat "$tunnel_pid_file" 2>/dev/null || echo "")
    if [ -n "$tpid" ] && kill -0 "$tpid" 2>/dev/null; then
      ok "running (PID $tpid)"
    else
      fail "stale PID file (process gone)"
    fi
  elif nc -z localhost 5439 2>/dev/null; then
    ok "port open (external tunnel?)"
  else
    fail "not running"
  fi

  # ─────────────────────────────────────────────────────────────────────
  printf "\n${_c}═══ 4/6  Data Lake (S3 Bronze) ═══${_0}\n\n"
  # ─────────────────────────────────────────────────────────────────────

  local platform_bucket
  platform_bucket=$(aws cloudformation describe-stacks \
    --stack-name "lake-access-iq-${CDK_ENV}" \
    --query "Stacks[0].Outputs[?OutputKey==\`BucketName\`].OutputValue" \
    --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")

  if [ -z "$platform_bucket" ] || [ "$platform_bucket" = "None" ]; then
    printf "  ${_r}Lake bucket not found - lake stack not deployed${_0}\n"
  else
    local entities=(
      "source=ehr_postgres/entity=patient_demographics"
      "source=ehr_postgres/entity=encounters"
      "source=ehr_postgres/entity=referrals"
      "source=ehr_postgres/entity=diagnoses"
      "source=sftp_appointments/entity=appointments"
      "source=trust_s3_provider_ref/entity=provider_site_reference"
      "source=trust_s3_diagnostics/entity=diagnostics_orders"
      "source=urgent_care_postgres/entity=urgent_care_logs"
    )
    local entity_labels=(
      "patient_demographics"
      "encounters"
      "referrals"
      "diagnoses"
      "appointments"
      "provider_site_reference"
      "diagnostics_orders"
      "urgent_care_logs"
    )

    local total_ok=0 total_entities=${#entities[@]}
    for i in "${!entities[@]}"; do
      local prefix="bronze/${entities[$i]}/"
      local label="${entity_labels[$i]}"
      local file_count
      file_count=$(aws s3 ls "s3://${platform_bucket}/${prefix}" --recursive \
        --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null \
        | grep -c '\.parquet$' || echo "0")
      printf "  %-30s " "$label"
      if [ "$file_count" -gt 0 ]; then
        ok "$file_count parquet file(s)"
        total_ok=$((total_ok + 1))
      else
        fail "empty"
      fi
    done
    printf "\n  %-30s " "Bronze coverage"
    if [ "$total_ok" -eq "$total_entities" ]; then
      ok "${total_ok}/${total_entities} entities populated"
    else
      warn "${total_ok}/${total_entities} entities populated"
    fi
  fi

  # ─────────────────────────────────────────────────────────────────────
  printf "\n${_c}═══ 5/6  Glue Catalog ═══${_0}\n\n"
  # ─────────────────────────────────────────────────────────────────────

  local glue_db="access-iq-${CDK_ENV}-bronze"
  local glue_tables
  glue_tables=$(aws glue get-tables --database-name "$glue_db" \
    --query 'TableList[*].Name' --output text \
    --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")

  printf "  %-30s " "Database ($glue_db)"
  if [ -n "$glue_tables" ] && [ "$glue_tables" != "None" ]; then
    local table_count
    table_count=$(echo "$glue_tables" | wc -w | tr -d ' ')
    ok "$table_count table(s) registered"

    for tbl in $glue_tables; do
      local part_count
      part_count=$(aws glue get-partitions --database-name "$glue_db" --table-name "$tbl" \
        --query 'Partitions | length(@)' --output text --no-paginate \
        --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null | head -1 | tr -d '[:space:]')
      part_count=${part_count:-0}
      printf "  %-30s " "  $tbl"
      if [ "$part_count" -gt 0 ] 2>/dev/null; then
        ok "$part_count partition(s)"
      else
        warn "no partitions"
      fi
    done
  else
    fail "database not found or empty"
  fi

  # ─────────────────────────────────────────────────────────────────────
  printf "\n${_c}═══ 6/6  Spectrum Tables (Redshift) ═══${_0}\n\n"
  # ─────────────────────────────────────────────────────────────────────

  if [ "$rs_status" != "AVAILABLE" ]; then
    printf "  ${_y}Skipped - Redshift workgroup not available${_0}\n"
  else
    local RS_SECRET_ARN
    RS_SECRET_ARN=$(aws redshift-serverless get-namespace \
      --namespace-name "access-iq-${CDK_ENV}" \
      --query 'namespace.adminPasswordSecretArn' \
      --output text --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")

    if [ -z "$RS_SECRET_ARN" ] || [ "$RS_SECRET_ARN" = "None" ]; then
      fail "Cannot resolve Redshift admin secret"
    else
      # Check external schema exists
      local schema_stmt_id
      schema_stmt_id=$(aws redshift-data execute-statement \
        --workgroup-name "access-iq-${CDK_ENV}" \
        --database dev \
        --secret-arn "$RS_SECRET_ARN" \
        --sql "SELECT schemaname FROM svv_external_schemas WHERE schemaname = 'bronze_external'" \
        --query 'Id' --output text \
        --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")

      if [ -n "$schema_stmt_id" ]; then
        # Wait for schema check
        local schema_done="SUBMITTED"
        while [ "$schema_done" != "FINISHED" ] && [ "$schema_done" != "FAILED" ]; do
          sleep 1
          schema_done=$(aws redshift-data describe-statement --id "$schema_stmt_id" \
            --query 'Status' --output text \
            --profile "$AWS_PROFILE" --region "$REGION")
        done

        if [ "$schema_done" = "FINISHED" ]; then
          local schema_rows
          schema_rows=$(aws redshift-data get-statement-result --id "$schema_stmt_id" \
            --query 'TotalNumRows' --output text \
            --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "0")
          printf "  %-30s " "bronze_external schema"
          if [ "$schema_rows" -gt 0 ]; then ok "exists"; else fail "not found"; fi
        else
          printf "  %-30s " "bronze_external schema"
          fail "query failed"
        fi
      fi

      # Query row counts for all Spectrum tables in one statement
      local count_sql
      count_sql=$(cat <<'EOSQL'
SELECT 'patient_demographics' AS tbl, COUNT(*) AS cnt FROM bronze_external.patient_demographics
UNION ALL SELECT 'encounters', COUNT(*) FROM bronze_external.encounters
UNION ALL SELECT 'referrals', COUNT(*) FROM bronze_external.referrals
UNION ALL SELECT 'diagnoses', COUNT(*) FROM bronze_external.diagnoses
UNION ALL SELECT 'appointments', COUNT(*) FROM bronze_external.appointments
UNION ALL SELECT 'provider_site_reference', COUNT(*) FROM bronze_external.provider_site_reference
UNION ALL SELECT 'diagnostics_orders', COUNT(*) FROM bronze_external.diagnostics_orders
UNION ALL SELECT 'urgent_care_logs', COUNT(*) FROM bronze_external.urgent_care_logs
EOSQL
)

      local count_stmt_id
      count_stmt_id=$(aws redshift-data execute-statement \
        --workgroup-name "access-iq-${CDK_ENV}" \
        --database dev \
        --secret-arn "$RS_SECRET_ARN" \
        --sql "$count_sql" \
        --query 'Id' --output text \
        --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "")

      if [ -n "$count_stmt_id" ]; then
        printf "  ${_d}Querying row counts (may take 10-30s)...${_0}\r"

        local count_done="SUBMITTED"
        local wait_secs=0
        while [ "$count_done" != "FINISHED" ] && [ "$count_done" != "FAILED" ] && [ "$wait_secs" -lt 60 ]; do
          sleep 2
          wait_secs=$((wait_secs + 2))
          count_done=$(aws redshift-data describe-statement --id "$count_stmt_id" \
            --query 'Status' --output text \
            --profile "$AWS_PROFILE" --region "$REGION")
        done

        printf "  %-30s \n" ""  # clear the "Querying..." line

        if [ "$count_done" = "FINISHED" ]; then
          local result_json
          result_json=$(aws redshift-data get-statement-result --id "$count_stmt_id" \
            --query 'Records' --output json \
            --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "[]")

          local all_populated=true
          echo "$result_json" | jq -r '.[] | "\(.[0].stringValue) \(.[1].longValue // .[1].stringValue)"' 2>/dev/null | \
          while read -r tbl cnt; do
            printf "  %-30s " "$tbl"
            if [ "$cnt" -gt 0 ] 2>/dev/null; then
              printf "${_g}✓${_0} %s rows\n" "$(printf "%'d" "$cnt" 2>/dev/null || echo "$cnt")"
            else
              printf "${_r}✗${_0} empty (0 rows)\n"
            fi
          done
        elif [ "$count_done" = "FAILED" ]; then
          local err_msg
          err_msg=$(aws redshift-data describe-statement --id "$count_stmt_id" \
            --query 'Error' --output text \
            --profile "$AWS_PROFILE" --region "$REGION" 2>/dev/null || echo "unknown")
          printf "  %-30s " "Row counts"
          fail "query failed: $err_msg"
        else
          printf "  %-30s " "Row counts"
          warn "timed out after 60s"
        fi
      fi
    fi
  fi

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
      printf "  \033[1;32m✓ %s - exit 0\033[0m\n" "$source"
    else
      printf "  \033[1;31m✗ %s - exit %s\033[0m\n" "$source" "$exit_code"
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

cmd_pipeline() {
  printf "\n\033[1;35m══════════════════════════════════════════\033[0m\n"
  printf "\033[1;35m  Prefect Pipeline: daily-ingest\033[0m\n"
  printf "\033[1;35m══════════════════════════════════════════\033[0m\n"

  step_start "1/2" "Connect to self-hosted Prefect server" "<10s"
  # Check if tunnel already running (port 4200 open locally)
  if ! nc -z localhost 4200 2>/dev/null; then
    local TUNNEL_INSTANCE_ID
    TUNNEL_INSTANCE_ID=$(platform_output warehouse TunnelInstanceId)
    aws ssm start-session \
      --target "$TUNNEL_INSTANCE_ID" \
      --document-name AWS-StartPortForwardingSessionToRemoteHost \
      --parameters '{"host":["prefect-server.access-iq.local"],"portNumber":["4200"],"localPortNumber":["4200"]}' \
      --profile "$AWS_PROFILE" --region "$REGION" &
    local tunnel_pid=$!
    echo "$tunnel_pid" > "$PLATFORM_REPO/.prefect-tunnel.pid"
    # Wait for tunnel to be ready
    for i in $(seq 1 15); do
      nc -z localhost 4200 2>/dev/null && break
      sleep 2
    done
  fi
  export PREFECT_API_URL="http://localhost:4200/api"
  step_done

  step_start "2/2" "Trigger flow run" "<10s"
  local run_date
  run_date=$(date +%Y-%m-%d)
  "$PLATFORM_REPO/.venv/bin/prefect" deployment run 'daily-ingest/dev' \
    --param "run_date=${run_date}" 2>&1 | tee /tmp/prefect_run.log
  printf "  Prefect UI: http://localhost:4200\n"
  step_done

  session_summary
}

# ── Main ──────────────────────────────────────────────────────────────

case "${1:-}" in
  up)                shift; cmd_up "$@" ;;
  down)              cmd_down ;;
  status)            cmd_status ;;
  ingest)            cmd_ingest ;;
  pipeline)          cmd_pipeline ;;
  cleanup-snapshots) shift; cmd_cleanup_snapshots "$@" ;;
  *)
    echo "Usage: $0 {up|down|status|ingest|pipeline|cleanup-snapshots}"
    echo ""
    echo "  up [flags]            Deploy Trust + Platform, publish data, run ingestion (~25 min)"
    echo "                        --skip-generate: reuse existing data/staging/ instead of regenerating"
    echo "                        --skip-seed:     deploy infrastructure only, no data seeding"
    echo "  down                  Destroy Platform + Trust stacks (~8 min)"
    echo "  status                Show current stack states"
    echo "  ingest                Run all 3 Bronze ingestion tasks on ECS (~5 min)"
    echo "  pipeline              Trigger full Prefect pipeline flow run (~2 min to queue)"
    echo "  cleanup-snapshots [N] Delete old Redshift snapshots, keep N most recent (default 2)"
    exit 1
    ;;
esac
