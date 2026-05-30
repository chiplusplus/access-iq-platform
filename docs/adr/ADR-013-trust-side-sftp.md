# ADR-013: Trust-Side SFTP, access-iq as Consumer Only

## Status

Accepted

## Context

The Northshire Trust simulator exports appointment data via SFTP. AWS Transfer Family
provides managed SFTP hosting at ~$0.30/hr (~$216/mo) idle for a single server endpoint.

The question is whether access-iq (Platform account) should host the Transfer Family
endpoint, or whether SFTP hosting belongs to the Trust account -- the data owner that
controls when and how appointment files are exported.

In a real NHS consultancy engagement, the Trust owns its data export mechanisms. The
consultant platform connects to the Trust's endpoint, authenticates, and pulls files.
The Trust controls access, rotation schedules, and file retention.

## Decision

**SFTP is Trust-side only.** The Northshire Hospital Simulator (`northshire-hospital-sim`
repo) owns the AWS Transfer Family SFTP endpoint in the Trust account. access-iq is a
consumer:

- ECS ingestion tasks connect to the Trust SFTP endpoint via VPC peering.
- SFTP credentials (host, port, username, key path) are stored in Platform Secrets
  Manager under `access-iq/{env}/sftp`.
- Ingestion code (`sftp.py`) uses paramiko over the peered VPC connection.
- No `AWS::Transfer::*` resource appears in any Platform CDK stack.

## Consequences

- Platform account has no Transfer Family cost ($0 vs ~$216/mo idle).
- Models a realistic vendor/client boundary -- the Trust owns its data export mechanism,
  the consultant consumes it.
- Platform ingestion code (`sftp.py`) depends on the Trust SFTP endpoint being available.
  If the Trust account is torn down, SFTP ingestion fails with a connection error (not a
  silent skip -- `fail_fast` controls the manifest status).
- Trust-side Transfer Family lifecycle is managed by the `northshire-hospital-sim` repo,
  not access-iq. Changes to the SFTP endpoint (key rotation, IP allowlisting) are
  coordinated out-of-band.
- VPC peering must allow port 22 traffic from Platform private subnets to Trust SFTP
  endpoint. The NetworkStack ECS security group has an explicit egress rule for this.
