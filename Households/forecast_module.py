from pathlib import Path
import numpy as np
import pandas as pd
import tensorflow as tf
import Helper_functions

WINDOW_SIZE = 24
HORIZON = 6

FEATURE_COLS = [
    "kwh",
    "hour_sin",
    "hour_cos",
    "year_sin",
    "year_cos",
    "dow_sin",
    "dow_cos",
    "weekend",
    "temperature",
    "humidity",
]


def select_house_window(
    house_df: pd.DataFrame,
    start_date: str | None = None,
    end_date: str | None = None,
    season: str | None = None,
) -> pd.DataFrame:
    df = house_df.copy()

    date_filtered = False

    if start_date is not None:
        df = df[df["DateTime"] >= pd.to_datetime(start_date)].copy()
        date_filtered = True

    if end_date is not None:
        df = df[df["DateTime"] <= pd.to_datetime(end_date)].copy()
        date_filtered = True

    if season is not None:
        season = season.lower().strip()

        season_months = {
            "spring": [3, 4, 5],
            "summer": [6, 7, 8],
            "autumn": [9, 10, 11],
            "fall": [9, 10, 11],
            "winter": [12, 1, 2],
        }

        if season not in season_months:
            raise ValueError(
                f"Unknown season '{season}'. Use spring, summer, autumn/fall, or winter."
            )

        months = season_months[season]
        seasonal_df = df[df["DateTime"].dt.month.isin(months)].copy()

        if seasonal_df.empty:
            range_msg = ""
            if start_date is not None or end_date is not None:
                range_msg = f" inside date window {start_date} to {end_date}"
            raise ValueError(f"No rows found for season '{season}'{range_msg}.")

        if date_filtered:
            selected = seasonal_df.sort_values("DateTime").reset_index(drop=True)
        else:
            # Only group by season-year when no explicit date window was supplied.
            # If a date window is supplied, the user is already telling us which year to use.
            if season == "winter":
                seasonal_df["season_year"] = seasonal_df["DateTime"].dt.year
                seasonal_df.loc[
                    seasonal_df["DateTime"].dt.month == 12, "season_year"
                ] = seasonal_df.loc[
                    seasonal_df["DateTime"].dt.month == 12, "DateTime"
                ].dt.year + 1
            else:
                seasonal_df["season_year"] = seasonal_df["DateTime"].dt.year

            best_season_year = seasonal_df["season_year"].value_counts().idxmax()

            selected = (
                seasonal_df[seasonal_df["season_year"] == best_season_year]
                .drop(columns=["season_year"])
                .sort_values("DateTime")
                .reset_index(drop=True)
            )

        if len(selected) <= WINDOW_SIZE:
            raise ValueError(
                f"Season '{season}' selection has only {len(selected)} rows, "
                f"which is not enough for WINDOW_SIZE={WINDOW_SIZE}."
            )

        return selected

    if date_filtered and not df.empty:
        selected = df.sort_values("DateTime").reset_index(drop=True)
        if len(selected) <= WINDOW_SIZE:
            raise ValueError(
                f"Date selection has only {len(selected)} rows, "
                f"which is not enough for WINDOW_SIZE={WINDOW_SIZE}."
            )
        return selected

    if "split" in df.columns:
        test_df = (
            df[df["split"] == "test"]
            .copy()
            .sort_values("DateTime")
            .reset_index(drop=True)
        )
        if not test_df.empty:
            return test_df

    raise ValueError("No valid rows found after selection.")


def _make_xy_multistep(
    feature_df: pd.DataFrame,
    window_size: int,
    horizon: int,
    target_col: str = "kwh",
) -> tuple[np.ndarray, np.ndarray]:
    values = feature_df.to_numpy(dtype=np.float32)
    target_idx = feature_df.columns.get_loc(target_col)

    x_list = []
    y_list = []

    total = len(values) - window_size - horizon + 1
    if total <= 0:
        return (
            np.empty((0, window_size, values.shape[1]), dtype=np.float32),
            np.empty((0, horizon), dtype=np.float32),
        )

    for i in range(total):
        x_window = values[i : i + window_size]
        y_window = values[i + window_size : i + window_size + horizon, target_idx]
        x_list.append(x_window)
        y_list.append(y_window)

    return np.asarray(x_list, dtype=np.float32), np.asarray(y_list, dtype=np.float32)


def _make_xy_one_step(
    feature_df: pd.DataFrame,
    window_size: int,
    target_col: str = "kwh",
) -> tuple[np.ndarray, np.ndarray]:
    x, y = _make_xy_multistep(
        feature_df=feature_df,
        window_size=window_size,
        horizon=1,
        target_col=target_col,
    )
    return x, y.reshape(-1, 1)


def _inverse_minmax(arr: np.ndarray, min_val: float, max_val: float) -> np.ndarray:
    return arr * (max_val - min_val) + min_val


def _metric_dict(y_true: np.ndarray, y_pred: np.ndarray, prefix: str = "") -> dict:
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    if prefix:
        return {
            f"{prefix}mae": mae,
            f"{prefix}rmse": rmse,
        }
    return {"mae": mae, "rmse": rmse}


def _load_base_data():
    base_dir = Path(__file__).resolve().parent
    norm_data_path = base_dir / "selected_100_normalised_ph.parquet"
    weather_scaler_path = base_dir / "global_weather_scaler.csv"
    local_kwh_scaler_path = base_dir / "local_kwh_scaler.csv"

    df, local_kwh_scaler_df, *_ = Helper_functions.load_data(
        norm_data_path,
        weather_scaler_path,
        local_kwh_scaler_path,
    )
    return base_dir, df, local_kwh_scaler_df


def _prepare_house_df(
    house_id: str,
    start_date: str | None,
    end_date: str | None,
    season: str | None,
):
    _, df, local_kwh_scaler_df = _load_base_data()

    house_df = (
        df[df["LCLid"] == house_id]
        .copy()
        .sort_values("DateTime")
        .reset_index(drop=True)
    )

    if house_df.empty:
        raise ValueError(f"No rows found for household {house_id} in normalized dataset.")

    house_df = select_house_window(
        house_df=house_df,
        start_date=start_date,
        end_date=end_date,
        season=season,
    )

    feature_df = house_df[FEATURE_COLS].copy()
    kwh_min, kwh_max = Helper_functions.extract_kwh(local_kwh_scaler_df, house_id)

    return house_df, feature_df, float(kwh_min), float(kwh_max)


def _predict_lstm_one_step(
    house_id: str,
    model_path: str,
    start_date: str | None,
    end_date: str | None,
    season: str | None,
):
    base_dir, _, _ = _load_base_data()
    house_df, feature_df, kwh_min, kwh_max = _prepare_house_df(
        house_id=house_id,
        start_date=start_date,
        end_date=end_date,
        season=season,
    )

    x_test, y_test = _make_xy_one_step(
        feature_df=feature_df,
        window_size=WINDOW_SIZE,
        target_col="kwh",
    )

    if len(x_test) == 0:
        raise ValueError(f"Not enough rows for {house_id} for one-step forecast.")

    model = tf.keras.models.load_model(base_dir / model_path, compile=False)
    pred_scaled = np.asarray(model.predict(x_test, verbose=0)).reshape(-1, 1)

    y_raw = _inverse_minmax(y_test, kwh_min, kwh_max)
    pred_raw = _inverse_minmax(pred_scaled, kwh_min, kwh_max)

    forecast_times = (
        pd.to_datetime(house_df["DateTime"])
        .iloc[WINDOW_SIZE : WINDOW_SIZE + len(pred_raw)]
        .reset_index(drop=True)
    )

    forecast_df = pd.DataFrame(
        {
            "DateTime": forecast_times,
            "actual_demand_kwh": y_raw[:, 0],
            "predicted_demand_kwh": pred_raw[:, 0],
        }
    )

    metrics = _metric_dict(y_raw[:, 0], pred_raw[:, 0])
    metrics["forecast_mode"] = "lstm1"
    return forecast_df, metrics


def _predict_cnn_six_step(
    house_id: str,
    cnn_model_path: str,
    start_date: str | None,
    end_date: str | None,
    season: str | None,
):
    base_dir, _, _ = _load_base_data()
    house_df, feature_df, kwh_min, kwh_max = _prepare_house_df(
        house_id=house_id,
        start_date=start_date,
        end_date=end_date,
        season=season,
    )

    x_test, y_test = _make_xy_multistep(
        feature_df=feature_df,
        window_size=WINDOW_SIZE,
        horizon=HORIZON,
        target_col="kwh",
    )

    if len(x_test) == 0:
        raise ValueError(f"Not enough rows for {house_id} for six-step forecast.")

    model = tf.keras.models.load_model(base_dir / cnn_model_path, compile=False)
    pred_scaled = np.asarray(model.predict(x_test, verbose=0))

    if pred_scaled.ndim == 3:
        pred_scaled = pred_scaled.squeeze(-1)
    if pred_scaled.ndim == 1:
        pred_scaled = pred_scaled.reshape(-1, 1)

    if pred_scaled.shape[1] != HORIZON:
        raise ValueError(
            f"CNN model output shape {pred_scaled.shape} does not match horizon={HORIZON}."
        )

    y_raw = _inverse_minmax(y_test, kwh_min, kwh_max)
    pred_raw = _inverse_minmax(pred_scaled, kwh_min, kwh_max)

    forecast_times = (
        pd.to_datetime(house_df["DateTime"])
        .iloc[WINDOW_SIZE : WINDOW_SIZE + len(pred_raw)]
        .reset_index(drop=True)
    )

    forecast_df = pd.DataFrame(
        {
            "DateTime": forecast_times,
            "actual_demand_kwh": y_raw[:, 0],
            "predicted_demand_kwh": pred_raw[:, 0],
            "pred_1h": pred_raw[:, 0],
            "pred_2h": pred_raw[:, 1],
            "pred_3h": pred_raw[:, 2],
            "pred_4h": pred_raw[:, 3],
            "pred_5h": pred_raw[:, 4],
            "pred_6h": pred_raw[:, 5],
            "future_demand_6h_plain": pred_raw.sum(axis=1),
        }
    )

    metrics = {}
    metrics.update(_metric_dict(y_raw[:, 0], pred_raw[:, 0], prefix="one_step_"))
    metrics.update(_metric_dict(y_raw, pred_raw, prefix="six_step_"))
    metrics["forecast_mode"] = "cnn6"
    return forecast_df, metrics


def predict_house_demand(
    house_id: str,
    model_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
    season: str | None = None,
    forecast_mode: str = "cnn6",
    cnn_model_path: str = "models/CNN_LSTM.keras",
):
    forecast_mode = (forecast_mode or "cnn6").lower().strip()

    if forecast_mode == "cnn6":
        return _predict_cnn_six_step(
            house_id=house_id,
            cnn_model_path=cnn_model_path,
            start_date=start_date,
            end_date=end_date,
            season=season,
        )

    if forecast_mode == "lstm1":
        return _predict_lstm_one_step(
            house_id=house_id,
            model_path=model_path,
            start_date=start_date,
            end_date=end_date,
            season=season,
        )

    raise ValueError("forecast_mode must be either 'cnn6' or 'lstm1'")