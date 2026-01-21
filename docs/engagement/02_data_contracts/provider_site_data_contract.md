# Data Contract — Trust S3 Provider/Site Reference (Excel)

## 1) Source Overview

**Source name:** Trust-owned S3 Reference File (Provider/Site Reference)  
**Ownership:** Trust Performance / Informatics Team  
**Access pattern:** Excel file stored in Trust S3 bucket  
**Cadence:** Ad hoc (infrequent); checked daily for changes  
**Purpose in access-iq:** Canonical mapping for provider/site codes, names, and groupings used for benchmarking and consistent dashboard filters.

**Authoritative stance:**  
This reference is **authoritative for provider/site naming and grouping**. Facts from operational systems join to this dimension; unmapped codes are treated as DQ issues, not silently ignored.

---

## 2) Delivery Contract (S3 Object-Level)

**Bucket:** Provided via environment config  
**Key (expected stable path):** `reference/provider_site_reference.xlsx` (or equivalent)  
**Format:** `.xlsx` workbook (machine-readable; no merged headers)

**Audit requirements:**
- object key, last_modified, etag/version_id
- parsed row count
- ingested_at

---

## 3) Schema (Contracted)

**Dataset:** provider_site_reference (Excel)  
**Grain:** 1 row per provider_site_code  
**Primary key:** `provider_site_code` (unique, non-null)

**Columns (expected)**

| Column | Type | Required | Notes |
|---|---:|:---:|---|
| provider_site_code | STRING | ✅ | Canonical join key |
| provider_site_name | STRING | ✅ | Display name |
| site_type | STRING | ⚠️ | hospital/clinic/community |
| region | STRING | ⛔ | Optional |
| is_active | BOOLEAN | ⛔ | Optional |
| effective_from | DATE | ⛔ | Optional (if effective dating supported) |
| effective_to | DATE | ⛔ | Optional |
| notes | STRING | ⛔ | Optional |

**Sheet naming:** If workbook contains multiple sheets, the authoritative sheet name must be documented (default: first sheet).

---

## 4) Expected Volume (Indicative)

- Small dimension table (tens to hundreds of rows)
- Changes infrequent; monitored via etag/version_id

---

## 5) Late-Arriving and Change Behaviour

- Codes may be added/renamed/deactivated over time.
- If effective dating is not present, the latest file represents the current truth (limitation documented).

**Change policy:**
- Additions: new rows
- Renames: update provider_site_name
- Deactivation: is_active=false preferred (rather than removing rows)

---

## 6) Idempotency Strategy

- Copy the reference file to Bronze with version metadata.
- Parse into staging; promote to Silver dimension.
- If unchanged (same etag/version_id), no-op the update.

---

## 7) Failure Handling

**Fail fast (stop + alert):**
- File missing/unreadable
- provider_site_code duplicates
- Required columns missing (provider_site_code, provider_site_name)
- Excel formatting prevents parsing (merged headers, inconsistent columns)

**Warn + continue (flag DQ):**
- Missing optional grouping fields (site_type/region)
- High unmapped_code_rate detected in facts (this is a downstream signal)

---

## 8) Authoritative Conflict Rules (Explicit)

1. **Provider/site naming and grouping:** this reference wins over raw names in any operational source.  
2. If two sources use different text names for the same provider_site_code, the reference name is used everywhere.  
3. If an operational fact contains a provider_site_code not in the reference:
   - map to `Unknown`
   - retain the fact
   - count and alert on unmapped_code_rate

---

## 9) Summary

Provider/Site reference is a conformance layer enabling consistent benchmarking across sources. It is treated as authoritative and validated strictly to prevent silent, trust-eroding mismatches in dashboard outputs.
