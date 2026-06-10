# ADR 003: KMS Customer-Managed Key for data lake encryption

## Status

Accepted

## Context

The data lake stores synthetic but structurally realistic NHS patient data (demographics, encounters, referrals, diagnostics). Even with pseudonymised identifiers, the dataset represents sensitive healthcare information that a real Trust engagement would classify as confidential.

Three encryption options were evaluated for the S3 lake bucket:

| Option                         | Key control    | Cross-account grants       | Audit trail                   | Cost                        |
| ------------------------------ | -------------- | -------------------------- | ----------------------------- | --------------------------- |
| **No encryption**              | N/A            | N/A                        | None                          | $0                          |
| **SSE-S3** (AES-256)           | AWS owns key   | Not possible               | No CloudTrail KMS events      | $0                          |
| **AWS-managed KMS** (`aws/s3`) | AWS manages    | Cannot scope per-principal | CloudTrail events             | ~$0 (free tier covers most) |
| **Customer-managed KMS (CMK)** | Account holder | Full key policy control    | CloudTrail + key policy audit | ~$1/mo + API calls          |

The decision hinges on whether the project needs to control who can decrypt the data, or whether encryption-at-rest is sufficient as a checkbox.

## Decision

Customer-managed KMS key (CMK). The marginal cost (~$1/month + API calls amortised by S3 Bucket Key) is negligible, and the benefits align with both DSPT expectations and portfolio demonstration value:

- **Key policy control** - the platform account holds the key, not AWS. IAM roles must be explicitly granted `kms:Decrypt` / `kms:GenerateDataKey` to read or write lake objects. This enforces least-privilege at the encryption layer, not just the bucket policy.
- **Cross-account readiness** - if the Trust account ever needs direct read access to specific prefixes, a KMS key grant scopes that access without sharing the full key. SSE-S3 and `aws/s3` cannot do this.
- **Audit trail** - every encrypt/decrypt call logs to CloudTrail, giving a per-principal access record that SSE-S3 silently handles server-side.
- **DSPT alignment** - the NHS Data Security and Protection Toolkit expects controllers to demonstrate they manage encryption keys, not delegate key lifecycle entirely to the cloud provider.

Implementation details:

- `LakeStack` creates a CMK with `RemovalPolicy.RETAIN` and 30-day pending deletion (the pending-deletion window blocks redeploy cycles if the key is destroyed and recreated).
- Bucket created with `BucketEncryption.KMS` referencing the CMK.
- Bucket policy denies `s3:PutObject` where encryption header is not `aws:kms` or key ID does not match the lake CMK (prevents unencrypted or cross-key uploads).
- `bucket_key_enabled=True` amortises per-object KMS API calls via S3 Bucket Key.
- KMS key rotation enabled.
- One alias per env: `alias/access-iq-{env}-lake`.

## Consequences

- Every IAM role that reads or writes lake objects (ingestion, Spectrum, dbt, export) MUST include `kms:Encrypt/Decrypt/GenerateDataKey` grants on the lake CMK. Without them, S3 operations fail with `AccessDenied` even if the bucket policy allows.
- Spectrum reads from Redshift Serverless require the namespace IAM role to have `kms:Decrypt` on the lake CMK.
- The KMS key uses `RETAIN` in both dev and prod because the pending-deletion window (7-30 days) would block redeploy cycles if the key were destroyed and recreated.

## Alternatives rejected

- **No encryption** - unacceptable for healthcare data, even synthetic. Portfolio should be representative of real world standards.
- **SSE-S3** - encryption at rest with zero key control. No CloudTrail visibility into decrypt operations, no ability to scope cross-account access, weaker DSPT posture.
- **AWS-managed KMS key** (`aws/s3`) - provides CloudTrail events but the key policy is AWS-controlled. Cannot add per-principal grants or restrict which roles decrypt. Marginally better than SSE-S3 but still insufficient for demonstrating key governance.

## References

- AWS Well-Architected Analytics Lens, Data Protection pillar
- NHS Data Security and Protection Toolkit (DSPT), Standard 8: Unsupported Systems
