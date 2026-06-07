"""Generate synthetic Gold-layer Parquet files for local dashboard testing.

Creates data/gold/<table>/export_date=2025-01-15/*.parquet for all 10 GOLD_TABLES.
Run from repo root: python scripts/generate_stub_gold.py
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

EXPORT_DATE = "2025-01-15"
BASE = Path("data/gold")
N_PATIENTS = 200
N_SITES = 5
N_SPECIALTIES = 8
N_WAIT = 500
N_UC = 400
N_INEQ = 120

random.seed(42)

SITE_NAMES = [
    "Northshire General",
    "Westmoor Community",
    "Eastdale Royal",
    "Southvale District",
    "Central NHS Trust",
]
SPECIALTY_NAMES = [
    "Cardiology",
    "Orthopaedics",
    "Dermatology",
    "Neurology",
    "Ophthalmology",
    "Gastroenterology",
    "Respiratory",
    "Rheumatology",
]
ETHNICITIES = ["White British", "Asian", "Black", "Mixed", "Other"]
AGE_BANDS = ["0-17", "18-34", "35-49", "50-64", "65-79", "80+"]
SEXES = ["Female", "Male"]


def write_table(name: str, table: pa.Table) -> None:
    out = BASE / name / f"export_date={EXPORT_DATE}"
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out / "part-00000.parquet")
    print(f"  {name}: {table.num_rows} rows")


def gen_dim_date() -> pa.Table:
    start = date(2024, 1, 1)
    dates = [start + timedelta(days=i) for i in range(400)]
    return pa.table(
        {
            "date_sk": list(range(1, len(dates) + 1)),
            "full_date": [d.isoformat() for d in dates],
            "year": [d.year for d in dates],
            "month": [d.month for d in dates],
            "day_of_week": [d.strftime("%A") for d in dates],
        }
    )


def gen_dim_site() -> pa.Table:
    return pa.table(
        {
            "site_sk": list(range(1, N_SITES + 1)),
            "site_code": [f"S{i:03d}" for i in range(1, N_SITES + 1)],
            "provider_name": SITE_NAMES,
            "region": ["North East"] * 3 + ["Yorkshire"] * 2,
        }
    )


def gen_dim_specialty() -> pa.Table:
    return pa.table(
        {
            "specialty_sk": list(range(1, N_SPECIALTIES + 1)),
            "specialty_code": [f"SP{i:02d}" for i in range(1, N_SPECIALTIES + 1)],
            "specialty_name": SPECIALTY_NAMES,
        }
    )


def gen_dim_patient() -> pa.Table:
    return pa.table(
        {
            "patient_sk": list(range(1, N_PATIENTS + 1)),
            "patient_pseudo_id": [f"P{i:06d}" for i in range(1, N_PATIENTS + 1)],
            "imd_decile": [random.randint(1, 10) for _ in range(N_PATIENTS)],
            "ethnicity_ons": [random.choice(ETHNICITIES) for _ in range(N_PATIENTS)],
            "age_band": [random.choice(AGE_BANDS) for _ in range(N_PATIENTS)],
            "sex": [random.choice(SEXES) for _ in range(N_PATIENTS)],
            "is_current": [True] * N_PATIENTS,
        }
    )


def gen_dim_ethnicity() -> pa.Table:
    return pa.table(
        {
            "ethnicity_sk": list(range(1, len(ETHNICITIES) + 1)),
            "ethnicity_code": [f"E{i}" for i in range(1, len(ETHNICITIES) + 1)],
            "ethnicity_ons": ETHNICITIES,
        }
    )


def gen_dim_imd() -> pa.Table:
    return pa.table(
        {
            "imd_sk": list(range(1, 11)),
            "imd_decile": list(range(1, 11)),
            "imd_label": [f"Decile {i}" for i in range(1, 11)],
        }
    )


def gen_fct_wait_times() -> pa.Table:
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    return pa.table(
        {
            "wait_sk": list(range(1, N_WAIT + 1)),
            "patient_sk": [random.randint(1, N_PATIENTS) for _ in range(N_WAIT)],
            "site_sk": [random.randint(1, N_SITES) for _ in range(N_WAIT)],
            "specialty_sk": [random.randint(1, N_SPECIALTIES) for _ in range(N_WAIT)],
            "referral_month": [random.choice(months) for _ in range(N_WAIT)],
            "wait_days": [random.randint(5, 400) for _ in range(N_WAIT)],
            "rtt_breach_flag": [random.random() > 0.7 for _ in range(N_WAIT)],
        }
    )


def gen_fct_urgent_care() -> pa.Table:
    base_dt = datetime(2024, 6, 1, 8, 0)
    arrivals = [base_dt + timedelta(hours=random.randint(0, 4000)) for _ in range(N_UC)]
    return pa.table(
        {
            "uc_sk": list(range(1, N_UC + 1)),
            "patient_sk": [random.randint(1, N_PATIENTS) for _ in range(N_UC)],
            "site_sk": [random.randint(1, N_SITES) for _ in range(N_UC)],
            "arrival_datetime": [a.isoformat() for a in arrivals],
            "arrival_month": [a.strftime("%Y-%m") for a in arrivals],
            "arrival_to_triage_mins": [random.randint(5, 45) for _ in range(N_UC)],
            "arrival_to_seen_mins": [random.randint(30, 120) for _ in range(N_UC)],
            "arrival_to_discharge_mins": [random.randint(60, 600) for _ in range(N_UC)],
            "four_hour_breach_flag": [random.random() > 0.75 for _ in range(N_UC)],
            "twelve_hour_breach_flag": [random.random() > 0.95 for _ in range(N_UC)],
            "admitted_flag": [random.random() > 0.7 for _ in range(N_UC)],
        }
    )


def gen_fct_inequality() -> pa.Table:
    rows: list[dict] = []
    strata_values: dict[str, list[str]] = {
        "imd_decile": [str(i) for i in range(1, 11)],
        "ethnicity_ons": ETHNICITIES,
        "age_band": AGE_BANDS,
        "sex": SEXES,
    }
    metrics = ["wait_time_median", "breach_rate", "dna_rate"]
    sk = 1
    for strat, strata in strata_values.items():
        for metric in metrics:
            for stratum in strata:
                pop = random.randint(50, 500) if random.random() > 0.1 else None
                rows.append(
                    {
                        "inequality_sk": sk,
                        "metric_name": metric,
                        "stratifier": strat,
                        "stratum": stratum,
                        "period": "2024-Q4",
                        "population_count": pop,
                        "metric_value": round(random.uniform(10, 80), 2),
                        "sii_value": round(random.uniform(-5, 15), 2)
                        if strat == "imd_decile" and metric == "wait_time_median"
                        else None,
                        "rii_value": round(random.uniform(0.8, 1.5), 2)
                        if strat == "imd_decile" and metric == "wait_time_median"
                        else None,
                    }
                )
                sk += 1

    return pa.table(
        {k: [r[k] for r in rows] for k in rows[0]},
    )


def gen_fct_utilisation() -> pa.Table:
    return pa.table(
        {
            "util_sk": list(range(1, 31)),
            "site_sk": [random.randint(1, N_SITES) for _ in range(30)],
            "period": [f"2024-{m:02d}" for m in range(1, 13)] * 2
            + [f"2024-{m:02d}" for m in range(1, 7)],
            "bed_occupancy_rate": [round(random.uniform(0.7, 0.98), 3) for _ in range(30)],
            "attendance_count": [random.randint(200, 1500) for _ in range(30)],
        }
    )


def main() -> None:
    print(f"Generating stub Gold data in {BASE}/ (export_date={EXPORT_DATE})")
    write_table("dim_date", gen_dim_date())
    write_table("dim_site", gen_dim_site())
    write_table("dim_specialty", gen_dim_specialty())
    write_table("dim_patient", gen_dim_patient())
    write_table("dim_ethnicity", gen_dim_ethnicity())
    write_table("dim_imd", gen_dim_imd())
    write_table("fct_wait_times", gen_fct_wait_times())
    write_table("fct_urgent_care", gen_fct_urgent_care())
    write_table("fct_inequality", gen_fct_inequality())
    write_table("fct_utilisation", gen_fct_utilisation())
    print("\nDone. Run: DATA_SOURCE=local streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
