# Pseudonymisation method — access-iq

## Method
HMAC-SHA-256 with a per-environment 32-byte secret key managed by AWS Secrets Manager.
Implementation: `src/access_iq/security/pseudonymise.py`.

## Why HMAC, not bare hashing
NHS numbers have a 10-digit decimal keyspace (10^10 = 10 billion). A bare SHA-256
hash is invertible in seconds via a precomputed rainbow table on commodity hardware.
HMAC with a secret key prevents this: the attacker would need both the rainbow table
AND the per-env secret, which is held only in Secrets Manager and never exfiltrated.

## Why not full anonymisation
Under UK GDPR Art. 4(5) + ICO guidance, pseudonymised data remains personal data
because the controller (this account) retains the key. Treating it as anonymous is
an audit-failure pattern. All medallion layers are personal data unless a formal
anonymisation assessment (k-anonymity + quasi-identifier removal) proves otherwise.

## Key management
- Storage: AWS Secrets Manager. Name: `access-iq/{env}/pseudonymisation-key`.
- Encryption-at-rest: customer-managed KMS CMK (LakeStack, see ADR 0003).
- Generation: CDK `Secret.generate_secret_string()` with `exclude_characters` to
  ensure URL-safe ASCII. 64 chars (>= 32 bytes entropy).
- Rotation: annual + on staff change (real-world DSPT cadence). Tooling for
  rotation is a Deferred Idea — built when first prod data lands.
- Access: only the ingestion task role and the Silver transform role (Phase 5)
  can `secretsmanager:GetSecretValue` against the secret ARN.

## Output
- 64-character hex digest of HMAC-SHA-256.
- Stable across runs within the same environment.
- Different across environments (different keys) — supports a Caldicott-aligned
  "dev cannot link to prod patients" property.

## Caveat
This primitive does NOT validate the NHS number Mod-11 checksum. Silver staging
(Phase 5) quarantines checksum-invalid rows and may still generate pseudonyms for
them so quarantine has a stable join key. Mod-11 is a Silver concern.
