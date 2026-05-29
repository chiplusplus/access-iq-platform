#!/usr/bin/env bash
# SSM port-forwarding tunnel to Redshift Serverless.
# Usage:
#   ./scripts/tunnel.sh          — start the tunnel (foreground, Ctrl+C to stop)
#   ./scripts/tunnel.sh env      — print export commands for dbt credentials
#   eval $(./scripts/tunnel.sh env) && dbt debug --profiles-dir .
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-CHI-Engineer-222308823356}"
CDK_ENV="${CDK_ENV:-dev}"
REGION="${REGION:-eu-west-2}"
LOCAL_PORT="${LOCAL_PORT:-5439}"
STACK_NAME="warehouse-access-iq-${CDK_ENV}"

stack_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey==\`$1\`].OutputValue" \
    --output text --profile "$AWS_PROFILE" --region "$REGION"
}

cmd_env() {
  local ns_name
  ns_name=$(stack_output NamespaceName)

  local secret_arn
  secret_arn=$(aws redshift-serverless get-namespace \
    --namespace-name "$ns_name" \
    --query 'namespace.adminPasswordSecretArn' \
    --output text --profile "$AWS_PROFILE" --region "$REGION")

  local secret_json
  secret_json=$(aws secretsmanager get-secret-value \
    --secret-id "$secret_arn" \
    --query SecretString --output text \
    --profile "$AWS_PROFILE" --region "$REGION")

  local user password
  user=$(echo "$secret_json" | jq -r '.username')
  password=$(echo "$secret_json" | jq -r '.password')

  local bucket
  bucket=$(aws cloudformation describe-stacks \
    --stack-name "lake-access-iq-${CDK_ENV}" \
    --query "Stacks[0].Outputs[?OutputKey==\`BucketName\`].OutputValue" \
    --output text --profile "$AWS_PROFILE" --region "$REGION")

  local hmac_lambda_name
  hmac_lambda_name=$(stack_output HmacLambdaName)

  local lambda_udf_role_arn
  lambda_udf_role_arn=$(stack_output LambdaUdfRoleArn)

  local kms_key_arn
  kms_key_arn=$(aws cloudformation describe-stacks \
    --stack-name "lake-access-iq-${CDK_ENV}" \
    --query "Stacks[0].Outputs[?OutputKey==\`KmsKeyArn\`].OutputValue" \
    --output text --profile "$AWS_PROFILE" --region "$REGION")

  printf 'export REDSHIFT_HOST=localhost\n'
  printf 'export REDSHIFT_USER=%s\n' "$user"
  printf 'export REDSHIFT_PASSWORD=%s\n' "$(printf '%q' "$password")"
  printf 'export BRONZE_S3_PREFIX=s3://%s/bronze\n' "$bucket"
  printf 'export PLATFORM_BUCKET=%s\n' "$bucket"
  printf 'export HMAC_LAMBDA_NAME=%s\n' "$hmac_lambda_name"
  printf 'export REDSHIFT_LAMBDA_UDF_ROLE_ARN=%s\n' "$lambda_udf_role_arn"
  printf 'export LAKE_KMS_KEY_ARN=%s\n' "$kms_key_arn"
}

cmd_tunnel() {
  local instance_id
  instance_id=$(stack_output TunnelInstanceId)

  local rs_endpoint
  rs_endpoint=$(stack_output WorkgroupEndpoint)

  echo "Tunnel: localhost:${LOCAL_PORT} -> ${rs_endpoint}:5439"
  echo "Instance: ${instance_id}"
  echo "Press Ctrl+C to stop."
  echo ""

  aws ssm start-session \
    --target "$instance_id" \
    --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters "{\"host\":[\"${rs_endpoint}\"],\"portNumber\":[\"5439\"],\"localPortNumber\":[\"${LOCAL_PORT}\"]}" \
    --profile "$AWS_PROFILE" --region "$REGION"
}

cmd_prefect() {
  local instance_id
  instance_id=$(stack_output TunnelInstanceId)

  echo "Prefect UI tunnel: localhost:4200 -> prefect-server.access-iq.local:4200"
  echo "Instance: ${instance_id}"
  echo "Press Ctrl+C to stop."
  echo ""

  aws ssm start-session \
    --target "$instance_id" \
    --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters '{"host":["prefect-server.access-iq.local"],"portNumber":["4200"],"localPortNumber":["4200"]}' \
    --profile "$AWS_PROFILE" --region "$REGION"
}

case "${1:-tunnel}" in
  env)     cmd_env ;;
  tunnel)  cmd_tunnel ;;
  prefect) cmd_prefect ;;
  *)       echo "Usage: $0 [tunnel|env|prefect]"; exit 1 ;;
esac
