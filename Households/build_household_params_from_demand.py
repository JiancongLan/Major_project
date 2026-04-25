from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

SIZE_RULES = [
    {"band": "B1_smallest", "avg_demand_upper": 0.15, "capacity_kwh": 3.0, "max_charge_kw": 1.5, "max_discharge_kw": 1.5, "pv_size_kwp": 1.68},
    {"band": "B2_small",    "avg_demand_upper": 0.35, "capacity_kwh": 5.0, "max_charge_kw": 2.0, "max_discharge_kw": 2.0, "pv_size_kwp": 2.10},
    {"band": "B3_medium",   "avg_demand_upper": 0.60, "capacity_kwh": 8.0, "max_charge_kw": 3.0, "max_discharge_kw": 3.0, "pv_size_kwp": 2.73},
    {"band": "B4_large",    "avg_demand_upper": 0.90, "capacity_kwh": 12.0, "max_charge_kw": 4.0, "max_discharge_kw": 4.0, "pv_size_kwp": 3.57},
    {"band": "B5_largest",  "avg_demand_upper": float("inf"), "capacity_kwh": 15.0, "max_charge_kw": 5.0, "max_discharge_kw": 5.0, "pv_size_kwp": 4.41},
]

DEFAULTS = {
    "initial_soc": 0.50,
    "eff": 0.93,
    "soc_max": 0.95,
    "soc_min": 0.20,
    "pv_shading_factor": 1.0,
    "pv_time_shift_hours": 0.0,
}

OUTPUT_COLUMNS = [
    "h_id",
    "avg_demand",
    "size_band",
    "model_path",
    "capacity_kwh",
    "initial_soc",
    "max_charge_kw",
    "max_discharge_kw",
    "eff",
    "soc_max",
    "soc_min",
    "pv_size_kwp",
    "pv_shading_factor",
    "pv_time_shift_hours",
]


def compute_avg_demand(raw_parquet: Path | None, normalized_parquet: Path | None, scaler_csv: Path | None) -> pd.DataFrame:
    if raw_parquet and raw_parquet.exists():
        raw_df = pd.read_parquet(raw_parquet)
        raw_df = raw_df[["LCLid", "kwh"]].copy()
        raw_df["LCLid"] = raw_df["LCLid"].astype(str)
        raw_df["kwh"] = pd.to_numeric(raw_df["kwh"], errors="coerce")
        raw_df = raw_df.dropna(subset=["LCLid", "kwh"])
        return (
            raw_df.groupby("LCLid", as_index=False)["kwh"].mean()
            .rename(columns={"LCLid": "h_id", "kwh": "avg_demand"})
            .sort_values("h_id")
            .reset_index(drop=True)
        )

    if normalized_parquet and normalized_parquet.exists() and scaler_csv and scaler_csv.exists():
        norm_df = pd.read_parquet(normalized_parquet)
        scaler_df = pd.read_csv(scaler_csv)

        norm_df = norm_df[["LCLid", "kwh"]].copy()
        norm_df["LCLid"] = norm_df["LCLid"].astype(str)
        norm_df["kwh"] = pd.to_numeric(norm_df["kwh"], errors="coerce")
        norm_df = norm_df.dropna(subset=["LCLid", "kwh"])

        scaler_df = scaler_df[["house_id", "kwh_min", "kwh_max"]].copy()
        scaler_df["house_id"] = scaler_df["house_id"].astype(str)

        merged = norm_df.merge(scaler_df, left_on="LCLid", right_on="house_id", how="left")
        merged = merged.dropna(subset=["kwh_min", "kwh_max"])
        merged["demand_kwh"] = merged["kwh"] * (merged["kwh_max"] - merged["kwh_min"]) + merged["kwh_min"]

        return (
            merged.groupby("LCLid", as_index=False)["demand_kwh"].mean()
            .rename(columns={"LCLid": "h_id", "demand_kwh": "avg_demand"})
            .sort_values("h_id")
            .reset_index(drop=True)
        )

    raise FileNotFoundError("Need selected_100.parquet or selected_100_normalised_ph.parquet + local_kwh_scaler.csv")


def pick_rule(avg_demand: float) -> dict:
    for rule in SIZE_RULES:
        if avg_demand < rule["avg_demand_upper"]:
            return rule
    return SIZE_RULES[-1]


def build_minimal_params(avg_df: pd.DataFrame, existing_params_path: Path, output_path: Path) -> pd.DataFrame:
    if existing_params_path.exists():
        existing = pd.read_csv(existing_params_path, dtype={"h_id": str})
    else:
        existing = pd.DataFrame(columns=["h_id"])
    existing["h_id"] = existing["h_id"].astype(str)

    out = avg_df.copy()

    # Keep existing non-model optional values if present
    for col, default in DEFAULTS.items():
        if col in existing.columns:
            out = out.merge(existing[["h_id", col]], on="h_id", how="left")
            out[col] = out[col].fillna(default)
        else:
            out[col] = default

    # Every household gets its own fine-tuned model path based on h_id
    out["model_path"] = out["h_id"].apply(
        lambda h: f"final_models/fine_tuned_LSTM64x32_{h}.keras"
    )

    size_bands = []
    capacities = []
    charge_limits = []
    discharge_limits = []
    pv_sizes = []

    for avg in out["avg_demand"]:
        rule = pick_rule(float(avg))
        size_bands.append(rule["band"])
        capacities.append(rule["capacity_kwh"])
        charge_limits.append(rule["max_charge_kw"])
        discharge_limits.append(rule["max_discharge_kw"])
        pv_sizes.append(rule["pv_size_kwp"])

    out["size_band"] = size_bands
    out["capacity_kwh"] = capacities
    out["max_charge_kw"] = charge_limits
    out["max_discharge_kw"] = discharge_limits
    out["pv_size_kwp"] = pv_sizes

    # Force core constants for clean realism-focused runs
    out["initial_soc"] = 0.50
    out["eff"] = 0.93
    out["soc_max"] = 0.95
    out["soc_min"] = 0.20

    out = out[OUTPUT_COLUMNS].sort_values("h_id").reset_index(drop=True)
    out.to_csv(output_path, index=False)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--existing-params", default="household_params.csv")
    parser.add_argument("--output", default="household_params.csv")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    existing_params_path = (base_dir / args.existing_params).resolve()
    output_path = (base_dir / args.output).resolve()

    raw_parquet = base_dir / "selected_100.parquet"
    normalized_parquet = base_dir / "selected_100_normalised_ph.parquet"
    scaler_csv = base_dir / "local_kwh_scaler.csv"

    avg_df = compute_avg_demand(raw_parquet, normalized_parquet, scaler_csv)
    out_df = build_minimal_params(avg_df, existing_params_path, output_path)

    print(f"Wrote {len(out_df)} rows to {output_path}")
    print(out_df.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
