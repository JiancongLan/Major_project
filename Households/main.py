import os
import json
from pathlib import Path
import pandas as pd

from battery import Battery
from agent import Household
from pv import pv_data_for_house, pv_cal
from forecast_module import predict_house_demand
from output_adapters import build_market_input, build_actual_records

HOUSEHOLD_ID = os.getenv("HOUSEHOLD_ID", "MAC000018")
PARAMS_FILE = os.getenv("PARAMS_FILE", "household_params.csv")
OUTPUT_ROOT = os.getenv("OUTPUT_ROOT", "outputs")

SIM_SEASON = (os.getenv("SIM_SEASON") or None)
SIM_START_DATE = os.getenv("SIM_START_DATE")
SIM_END_DATE = os.getenv("SIM_END_DATE")

FORECAST_MODE = os.getenv("FORECAST_MODE", "cnn6")
FUTURE_SIGNAL_WEIGHTS = os.getenv("FUTURE_SIGNAL_WEIGHTS", "1.0,0.85,0.70,0.55,0.40,0.25")


OPTIONAL_NUMERIC_DEFAULTS = {
    "pv_shading_factor": 1.0,
    "pv_time_shift_hours": 0.0,
}


def parse_weight_string(s: str) -> list[float]:
    parts = [x.strip() for x in s.split(",") if x.strip()]
    weights = [float(x) for x in parts]
    if len(weights) != 6:
        raise ValueError(
            f"FUTURE_SIGNAL_WEIGHTS must contain 6 numbers, got {len(weights)}: {weights}"
        )
    return weights


WEIGHTS = parse_weight_string(FUTURE_SIGNAL_WEIGHTS)


def load_household_row(h_id: str, csv_path: str | Path = "household_params.csv") -> dict:
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path, dtype={"h_id": str})

    row = df.loc[df["h_id"] == h_id]
    if row.empty:
        raise ValueError(f"No parameter row found for household {h_id} in {csv_path}")

    cfg = row.iloc[0].to_dict()

    numeric_cols = [
        "capacity_kwh",
        "initial_soc",
        "max_charge_kw",
        "max_discharge_kw",
        "eff",
        "soc_max",
        "soc_min",
        "pv_size_kwp",
    ]
    for col in numeric_cols:
        cfg[col] = float(cfg[col])

    for col, default in OPTIONAL_NUMERIC_DEFAULTS.items():
        if col in cfg and pd.notna(cfg[col]):
            cfg[col] = float(cfg[col])
        else:
            cfg[col] = float(default)

    return cfg


def prepare_forecast_df(forecast_df: pd.DataFrame) -> pd.DataFrame:
    out = forecast_df.copy()
    if "predicted_demand_kwh_raw" not in out.columns:
        out["predicted_demand_kwh_raw"] = out["predicted_demand_kwh"]
    if "forecast_calibration_delta_kwh" not in out.columns:
        out["forecast_calibration_delta_kwh"] = 0.0
    return out


def add_future_signal_columns(sim_df: pd.DataFrame, weights: list[float]) -> pd.DataFrame:
    out = sim_df.copy()

    pred_cols = [f"pred_{i}h" for i in range(1, 7)]
    if all(col in out.columns for col in pred_cols):
        out["future_demand_6h_plain"] = out[pred_cols].sum(axis=1)
        out["future_demand_signal_kwh"] = sum(
            out[f"pred_{i}h"] * weights[i - 1] for i in range(1, 7)
        )
    else:
        out["future_demand_6h_plain"] = sum(
            out["predicted_demand_kwh"].shift(-(i - 1)).fillna(0.0) for i in range(1, 7)
        )
        out["future_demand_signal_kwh"] = sum(
            out["predicted_demand_kwh"].shift(-(i - 1)).fillna(0.0) * weights[i - 1]
            for i in range(1, 7)
        )

    out["future_pv_6h_plain"] = sum(
        out["pv_kwh"].shift(-i).fillna(0.0) for i in range(1, 7)
    )
    out["future_pv_signal_kwh"] = sum(
        out["pv_kwh"].shift(-i).fillna(0.0) * weights[i - 1] for i in range(1, 7)
    )

    out["future_energy_6h_plain"] = out["future_demand_6h_plain"] - out["future_pv_6h_plain"]
    out["future_energy_signal_kwh"] = out["future_demand_signal_kwh"] - out["future_pv_signal_kwh"]
    return out


def run_household_simulation(
    sim_df: pd.DataFrame,
    demand_col: str,
    household_id: str,
    params_file: str,
) -> pd.DataFrame:
    results = []

    battery = Battery.from_csv(household_id, params_file)
    house = Household(
        h_id=household_id,
        battery=battery,
        battery_charge_fraction_from_surplus=1.0,
    )

    for _, row in sim_df.iterrows():
        demand = row[demand_col]
        pv = row["pv_kwh"]
        t_h = 1.0

        future_energy_signal_kwh = None
        if "future_energy_signal_kwh" in row and pd.notna(row["future_energy_signal_kwh"]):
            future_energy_signal_kwh = float(row["future_energy_signal_kwh"])

        result = house.run_slot(
            demand=demand,
            pv=pv,
            t_h=t_h,
            future_energy_signal_kwh=future_energy_signal_kwh,
        )

        result["h_id"] = household_id
        result["DateTime"] = row["DateTime"]
        result["glbl_irad_amt"] = row["glbl_irad_amt"]
        result["pv_kwh"] = row["pv_kwh"]
        result["actual_demand_kwh"] = row["actual_demand_kwh"]
        result["predicted_demand_kwh"] = row["predicted_demand_kwh"]
        result["predicted_demand_kwh_raw"] = row["predicted_demand_kwh_raw"]
        result["forecast_calibration_delta_kwh"] = row["forecast_calibration_delta_kwh"]
        result["forecast_error_kwh"] = row["actual_demand_kwh"] - row["predicted_demand_kwh"]

        for col in [
            "future_demand_6h_plain",
            "future_pv_6h_plain",
            "future_energy_6h_plain",
            "future_demand_signal_kwh",
            "future_pv_signal_kwh",
            "future_energy_signal_kwh",
        ]:
            if col in row:
                result[col] = row[col]

        results.append(result)

    return pd.DataFrame(results)


def save_outputs(
    household_id: str,
    cfg: dict,
    metrics: dict,
    forecast_df: pd.DataFrame,
    predicted_results_df: pd.DataFrame,
    actual_results_df: pd.DataFrame,
    market_input_df: pd.DataFrame,
    actual_records_df: pd.DataFrame,
) -> Path:
    out_dir = Path(OUTPUT_ROOT) / household_id
    out_dir.mkdir(parents=True, exist_ok=True)

    forecast_df.to_csv(out_dir / "forecast_df.csv", index=False)
    predicted_results_df.to_csv(out_dir / "predicted_results.csv", index=False)
    actual_results_df.to_csv(out_dir / "actual_results.csv", index=False)
    market_input_df.to_csv(out_dir / "market_input.csv", index=False)
    actual_records_df.to_csv(out_dir / "actual_records.csv", index=False)

    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    with open(out_dir / "config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    return out_dir


cfg = load_household_row(HOUSEHOLD_ID, PARAMS_FILE)
MODEL_PATH = str(cfg.get("model_path", "")).strip()
if not MODEL_PATH:
    raise ValueError(f"No model_path found in {PARAMS_FILE} for household {HOUSEHOLD_ID}")

forecast_df, metrics = predict_house_demand(
    house_id=HOUSEHOLD_ID,
    model_path=MODEL_PATH,
    start_date=SIM_START_DATE,
    end_date=SIM_END_DATE,
    season=SIM_SEASON,
    forecast_mode=FORECAST_MODE,
)
forecast_df = prepare_forecast_df(forecast_df)

pv_df = pv_data_for_house(
    pv_time_shift_hours=int(cfg.get("pv_time_shift_hours", 0)),
    pv_shading_factor=float(cfg.get("pv_shading_factor", 1.0)),
)

merge_data = pd.merge(
    forecast_df,
    pv_df[["DateTime", "glbl_irad_amt"]],
    on="DateTime",
    how="inner"
)

merge_data["pv_kwh"] = merge_data["glbl_irad_amt"].apply(
    lambda x: pv_cal(x, pv_size_kwp=cfg["pv_size_kwp"])
)

merge_data = add_future_signal_columns(merge_data, WEIGHTS)

predicted_results_df = run_household_simulation(
    sim_df=merge_data,
    demand_col="predicted_demand_kwh",
    household_id=HOUSEHOLD_ID,
    params_file=PARAMS_FILE,
)

actual_results_df = run_household_simulation(
    sim_df=merge_data,
    demand_col="actual_demand_kwh",
    household_id=HOUSEHOLD_ID,
    params_file=PARAMS_FILE,
)

market_input_df = build_market_input(predicted_results_df, HOUSEHOLD_ID)
actual_records_df = build_actual_records(actual_results_df, HOUSEHOLD_ID)

out_dir = save_outputs(
    household_id=HOUSEHOLD_ID,
    cfg=cfg,
    metrics=metrics,
    forecast_df=forecast_df,
    predicted_results_df=predicted_results_df,
    actual_results_df=actual_results_df,
    market_input_df=market_input_df,
    actual_records_df=actual_records_df,
)

print(f"Household run complete: {HOUSEHOLD_ID}")
print(f"Outputs saved to: {out_dir}")
print(f"Requested season: {SIM_SEASON}")
print(f"Forecast mode: {FORECAST_MODE}")
print(f"Future signal weights: {WEIGHTS}")

if not forecast_df.empty:
    print(
        "Forecast actual date range used: "
        f"{forecast_df['DateTime'].min()} to {forecast_df['DateTime'].max()}"
    )

if not merge_data.empty:
    print(
        "Merged forecast+PV date range used: "
        f"{merge_data['DateTime'].min()} to {merge_data['DateTime'].max()}"
    )
