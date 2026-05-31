# ADR 0003: KMS CMK on lake bucket (no migration)

## Status
Accepted (Phase 1, 2026-05-12)

## Context
The original `PlatformBucketStack` used `BucketEncryption.S3_MANAGED` (SSE-S3).
For an NHS-shaped portfolio aligning to DSPT controls and the AWS Well-Architected
Analytics Lens, the lake bucket SHOULD use a customer-managed KMS key (CMK) so the
controller (this account) holds usage / access control over the encryption key,
not AWS.

The decision could either be:
(a) ship SSE-S3 first, migrate to CMK later (requires a re-encryption batch job
across all objects and a window where mixed-encryption is possible), or
(b) ship CMK from day 1, with bucket policy denying any non-KMS put.

## Decision
Option (b). Specifically:
- LakeStack creates a CMK with `RemovalPolicy.RETAIN` and 30-day pending deletion.
  (Pending-deletion window is well-documented gotcha - see pitfalls.md #8.)
- The lake bucket is created with `BucketEncryption.KMS` referencing that CMK.
- Bucket policy denies `s3:PutObject` where `s3:x-amz-server-side-encryption` != `aws:kms`.
- Bucket policy denies `s3:PutObject` where `s3:x-amz-server-side-encryption-aws-kms-key-id`
  is set but does not match the lake key ARN (prevents cross-key uploads).
- `bucket_key_enabled=True` so per-object KMS API calls are amortised (S3 Bucket Key).
- KMS rotation enabled.
- One alias per env: `alias/access-iq-{env}-lake`.

No migration code exists because no prod data has been deployed. Dev bucket is
recreated on first `cdk deploy LakeStack` (after destroying the legacy stack).

## Consequences
- `IngestionRoleStack` (and any future writer role) MUST grant
  `kms:Encrypt/Decrypt/GenerateDataKey` on the lake CMK in addition to S3 actions.
  Without it, `PutObject` against the KMS bucket fails with `AccessDenied`.
- Cross-account COPY to Bronze (none today; Phase 3 keeps Bronze writes inside the
  Platform account) would require a KMS key grant on the Trust principal.
- Spectrum reads from Redshift Serverless (Phase 4) require the Redshift namespace
  IAM role to have `kms:Decrypt` on the lake CMK - captured as a Phase 4 follow-up.
- Future stateful resources (Secrets, Glue, ECR) can re-use the same CMK or get
  their own.

## Alternatives considered
- SSE-S3 with a "we'll upgrade later" plan - rejected: re-encryption job overhead
  + a window where mixed-encryption is acceptable creates audit ambiguity.
- AWS-managed KMS key (`aws/s3`) - rejected: no control over key policy; cannot
  scope grants per principal; weaker DSPT story.

## References
- AWS Well-Architected Analytics Lens, Data Protection pillar
- .planning/research/architecture.md (ephemeral state preservation)
- .planning/research/pitfalls.md #8 (KMS/Secrets pending-deletion)
