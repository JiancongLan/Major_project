from pathlib import Path
import pandas as pd


def pv_data() -> pd.DataFrame:
    base_dir = Path(__file__).resolve().parent
    csv_files = sorted(base_dir.glob("midas-open_uk-radiation-obs_dv-*.csv"))

    if not csv_files:
        raise FileNotFoundError("No MIDAS PV CSV files found in the Households folder.")

    frames = []

    for file in csv_files:
        df = pd.read_csv(file, skiprows=78)
        df.columns = df.columns.str.strip()
        df = df[["ob_end_time", "glbl_irad_amt"]].copy()
        frames.append(df)

    pv_df = pd.concat(frames, ignore_index=True)
    pv_df = pv_df.rename(columns={"ob_end_time": "DateTime"})
    pv_df["DateTime"] = pd.to_datetime(pv_df["DateTime"], format="mixed", errors="coerce")
    pv_df["glbl_irad_amt"] = pd.to_numeric(pv_df["glbl_irad_amt"], errors="coerce")

    pv_df = pv_df.dropna(subset=["DateTime", "glbl_irad_amt"])
    pv_df["DateTime"] = pv_df["DateTime"] - pd.Timedelta(hours=1)
    pv_df = pv_df.sort_values("DateTime").drop_duplicates(subset=["DateTime"]).reset_index(drop=True)

    return pv_df


def pv_data_for_house(
    pv_time_shift_hours: int = 0,
    pv_shading_factor: float = 1.0,
) -> pd.DataFrame:
    """
    Household-specific PV variant.

    pv_time_shift_hours:
        integer hour shift to mimic east/west roof timing differences.
        negative = earlier solar peak
        positive = later solar peak

    pv_shading_factor:
        scales irradiance to mimic shading/orientation differences.
        1.0 = unchanged
        0.9 = 10% lower
    """
    df = pv_data().copy()

    pv_time_shift_hours = int(pv_time_shift_hours)
    pv_shading_factor = float(pv_shading_factor)

    df["DateTime"] = df["DateTime"] + pd.to_timedelta(pv_time_shift_hours, unit="h")
    df["glbl_irad_amt"] = (df["glbl_irad_amt"] * pv_shading_factor).clip(lower=0.0)

    df = df.sort_values("DateTime").drop_duplicates(subset=["DateTime"]).reset_index(drop=True)
    return df


def pv_cal(glbl_irad_amt: float, pv_size_kwp: float = 12.0, performance_ratio: float = 0.85) -> float:
    solar_energy = glbl_irad_amt / 3600
    pv_kwh = solar_energy * performance_ratio * pv_size_kwp
    return pv_kwh