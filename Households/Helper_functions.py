from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.metrics import mean_squared_error, mean_absolute_error

'''
Contains helper functions for loading in files
Extracting scaling max min values 
Splitting data back into train, val, test sets
Organising data into windowed form suitable for LSTM
Unscaling
Evaluating predictions
'''


def load_data(data_path, max_min_path, local_kwh_scaling):
    df = pd.read_parquet(data_path)
    df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
    df = df.sort_values(["LCLid", "DateTime"]).reset_index(drop=True)

    # test on house index 1
    #unique_houses = df["LCLid"].unique()

    # change to get unique house
    #house_id = unique_houses[index]


    weather_scaler_df = pd.read_csv(max_min_path)
    local_kwh_scaler_df = pd.read_csv(local_kwh_scaling)
    #kwh_min = float(local_kwh_scaler_df[local_kwh_scaler_df["house_id"] == house_id]["kwh_min"].item())
    #kwh_max = float(local_kwh_scaler_df[local_kwh_scaler_df["house_id"] == house_id]["kwh_max"].item())

    global_temp_min = float(weather_scaler_df["global_temp_min"].iloc[0])
    global_temp_max = float(weather_scaler_df["global_temp_max"].iloc[0])

    global_hum_min = float(weather_scaler_df["global_hum_min"].iloc[0])
    global_hum_max = float(weather_scaler_df["global_hum_max"].iloc[0])

    return df, local_kwh_scaler_df, global_temp_min, global_temp_max, global_hum_min, global_hum_max




def make_xy(df_house: pd.DataFrame, window_size: int = 24, target_col: str = "kwh"):
    values = df_house.to_numpy(dtype=np.float32)
    target_idx = df_house.columns.get_loc(target_col)       #get index of column

    X = []
    y = []

    for i in range(len(values) - window_size):
        X.append(values[i:i + window_size])
        y.append(values[i + window_size, target_idx])

    return np.array(X), np.array(y)




def get_house_split(df: pd.DataFrame, house_id: str, feature_cols):
    house_df = df[df["LCLid"] == house_id].copy().sort_values("DateTime")   #sort by date and time and obtain values for individual house

    train_df = house_df[house_df["split"] == "train"].copy()    #get training data
    val_df = house_df[house_df["split"] == "val"].copy()
    test_df = house_df[house_df["split"] == "test"].copy()

    train_df = train_df[feature_cols].copy()        #organise columns by input features as defined above
    val_df = val_df[feature_cols].copy()
    test_df = test_df[feature_cols].copy()

    return train_df, val_df, test_df




def unscale(arr_scaled, min_val, max_val):
    return arr_scaled * (max_val - min_val) + min_val




def evaluate_predictions(y_scaled, pred_scaled, min_val, max_val):
    y_raw = unscale(y_scaled, min_val, max_val)
    pred_raw = unscale(pred_scaled, min_val, max_val)

    rmse = np.sqrt(mean_squared_error(y_raw, pred_raw))
    mae = mean_absolute_error(y_raw, pred_raw)

    y_std = np.std(y_raw)
    y_mean = np.mean(y_raw)

    if y_std != 0:
        nrmse_std = rmse / y_std
    else:
        nrmse_std = np.nan

    if y_mean != 0:
        nrmse_mean = rmse / y_mean

    else:
        nrmse_mean = np.nan


    return {
        "rmse_kwh": rmse,
        "mae_kwh": mae,
        "nrmse_std": nrmse_std,
        "nrmse_mean": nrmse_mean,
    }, y_raw, pred_raw

def extract_kwh(local_kwh_scaler_df, house_id):

    kwh_min = float(local_kwh_scaler_df[local_kwh_scaler_df["house_id"] == house_id]["kwh_min"].item())
    kwh_max = float(local_kwh_scaler_df[local_kwh_scaler_df["house_id"] == house_id]["kwh_max"].item())

    return kwh_min, kwh_max