import pandas as pd


def build_market_input(predicted_results_df: pd.DataFrame, household_id: str) -> pd.DataFrame:
    market_input_df = predicted_results_df[["DateTime", "import_energy", "export_energy"]].copy()
    market_input_df.insert(0, "h_id", household_id)

    market_input_df["import_energy"] = pd.to_numeric(
        market_input_df["import_energy"], errors="coerce"
    ).fillna(0.0)
    market_input_df["export_energy"] = pd.to_numeric(
        market_input_df["export_energy"], errors="coerce"
    ).fillna(0.0)

    return market_input_df


def build_actual_records(actual_results_df: pd.DataFrame, household_id: str) -> pd.DataFrame:
    actual_records_df = pd.DataFrame({
        "h_id": household_id,
        "DateTime": actual_results_df["DateTime"],
        "actual_buy_kwh": pd.to_numeric(
            actual_results_df["import_energy"], errors="coerce"
        ).fillna(0.0),
        "actual_sell_kwh": pd.to_numeric(
            actual_results_df["export_energy"], errors="coerce"
        ).fillna(0.0),
    })

    return actual_records_df