from pathlib import Path
import pandas as pd


def demand_data(household: str = "MAC000018") -> pd.DataFrame:
    base_dir = Path(__file__).resolve().parent
    parquet_path = base_dir / "selected_100.parquet"

    df = pd.read_parquet(parquet_path)

    house_df = df.loc[df["LCLid"] == household, ["DateTime", "kwh"]].copy()

    if house_df.empty:
        raise ValueError(f"No rows found for household {household} in {parquet_path}")

    house_df["DateTime"] = pd.to_datetime(house_df["DateTime"])
    house_df["demand_kwh"] = pd.to_numeric(house_df["kwh"], errors="coerce")

    house_df = house_df.dropna(subset=["DateTime", "demand_kwh"])
    house_df = house_df.sort_values("DateTime").reset_index(drop=True)

    return house_df[["DateTime", "demand_kwh"]]