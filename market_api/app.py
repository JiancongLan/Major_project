import contextlib
import io
import os
import sys
from pathlib import Path
from typing import Any, List

import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

REPO_ROOT = Path("/repos/market_operator")
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from main import run_one_slot
from tariff import load_tou_profile, load_fit_profile


TARIFF_TARGET_YEAR = int(os.getenv("TARIFF_TARGET_YEAR", "2026"))
SIM_SEASON = os.getenv("SIM_SEASON", "").strip().lower() or None
TARIFF_AGG = os.getenv("TARIFF_AGG", "median").strip().lower()

# new: explicit tariff file selection
TOU_CSV_PATH = os.getenv("TOU_CSV_PATH", "").strip() or None
FIT_CSV_PATH = os.getenv("FIT_CSV_PATH", "").strip() or None


class MarketInputRow(BaseModel):
    DateTime: str
    h_id: str
    import_energy: float
    export_energy: float


def normalize_value(v: Any):
    if isinstance(v, dict):
        return {k: normalize_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [normalize_value(x) for x in v]
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
    except Exception:
        pass
    return v


app = FastAPI()

TOU_PROFILE = load_tou_profile(
    csv_path=TOU_CSV_PATH,
    target_year=TARIFF_TARGET_YEAR,
    season=SIM_SEASON,
    agg=TARIFF_AGG,
)
FIT_PROFILE = load_fit_profile(
    csv_path=FIT_CSV_PATH,
    target_year=TARIFF_TARGET_YEAR,
    season=SIM_SEASON,
    agg=TARIFF_AGG,
)

MARKET_STATE = {
    "trader_registry": {},
    "order_id_counter": 0,
    "id_map": {},
    "reverse_id_map": {},
    "next_numeric_id": 1,
}


def encode_household_id(h_id: str) -> int:
    if h_id not in MARKET_STATE["id_map"]:
        numeric_id = MARKET_STATE["next_numeric_id"]
        MARKET_STATE["next_numeric_id"] += 1
        MARKET_STATE["id_map"][h_id] = numeric_id
        MARKET_STATE["reverse_id_map"][numeric_id] = h_id
    return MARKET_STATE["id_map"][h_id]


def decode_household_id(numeric_id: int | str) -> str:
    try:
        numeric_id = int(numeric_id)
    except Exception:
        return str(numeric_id)
    return MARKET_STATE["reverse_id_map"].get(numeric_id, str(numeric_id))


def build_internal_df(rows: List[MarketInputRow]) -> pd.DataFrame:
    out = []
    for row in rows:
        out.append(
            {
                "DateTime": row.DateTime,
                "h_id": encode_household_id(str(row.h_id)),
                "import_energy": float(row.import_energy),
                "export_energy": float(row.export_energy),
            }
        )
    return pd.DataFrame(out)


@app.get("/health")
def health():
    return {"status": "market ok"}


@app.post("/reset")
def reset_market_state():
    MARKET_STATE["trader_registry"] = {}
    MARKET_STATE["order_id_counter"] = 0
    MARKET_STATE["id_map"] = {}
    MARKET_STATE["reverse_id_map"] = {}
    MARKET_STATE["next_numeric_id"] = 1
    return {"status": "reset"}


@app.post("/run-slot")
def run_slot(rows: List[MarketInputRow]):
    df = build_internal_df(rows)

    with contextlib.redirect_stdout(io.StringIO()):
        result, trader_registry, order_id_end = run_one_slot(
            slot_df=df,
            tou_profile=TOU_PROFILE,
            fit_profile=FIT_PROFILE,
            trader_registry=MARKET_STATE["trader_registry"],
            order_id_start=MARKET_STATE["order_id_counter"],
            verbose=False,
        )

    MARKET_STATE["trader_registry"] = trader_registry
    MARKET_STATE["order_id_counter"] = order_id_end

    committed_trades = []
    for t in result["committed_trades"]:
        td = normalize_value(vars(t))
        committed_trades.append(
            {
                "trade_id": td["trade_id"],
                "buyer_h_id": decode_household_id(td["buyer_h_id"]),
                "seller_h_id": decode_household_id(td["seller_h_id"]),
                "buyer_order_id": td["buyer_order_id"],
                "seller_order_id": td["seller_order_id"],
                "DateTime": td["DateTime"],
                "hour": td["hour"],
                "quantity_kwh": float(td["quantity"]),
                "trade_price": float(td["trade_price"]),
                "trade_value": float(td["trade_value"]),
                "trade_round": int(td["trade_round"]),
            }
        )

    unmatched_orders = []
    for u in result["unmatched_orders"]:
        ud = normalize_value(vars(u))
        unmatched_orders.append(
            {
                "unmatched_order_id": ud["unmatched_order_id"],
                "order_id": ud["order_id"],
                "h_id": decode_household_id(ud["h_id"]),
                "DateTime": ud["DateTime"],
                "hour": ud["hour"],
                "side": ud["side"],
                "original_quantity_kwh": float(ud["original_quantity"]),
                "remaining_quantity_kwh": float(ud["remaining_quantity"]),
                "limit_price": float(ud["limit_price"]),
                "submitted_price": float(ud["submitted_price"]),
            }
        )

    market_records = {}
    for row in rows:
        key = (row.h_id, row.DateTime)
        market_records[key] = {
            "DateTime": row.DateTime,
            "h_id": row.h_id,
            "committed_buy_kwh": 0.0,
            "committed_sell_kwh": 0.0,
            "unmatched_buy_kwh": 0.0,
            "unmatched_sell_kwh": 0.0,
        }

    for t in committed_trades:
        buyer_key = (str(t["buyer_h_id"]), str(t["DateTime"]))
        seller_key = (str(t["seller_h_id"]), str(t["DateTime"]))
        market_records[buyer_key]["committed_buy_kwh"] += float(t["quantity_kwh"])
        market_records[seller_key]["committed_sell_kwh"] += float(t["quantity_kwh"])

    for u in unmatched_orders:
        key = (str(u["h_id"]), str(u["DateTime"]))
        if str(u["side"]) == "buy":
            market_records[key]["unmatched_buy_kwh"] += float(u["remaining_quantity_kwh"])
        else:
            market_records[key]["unmatched_sell_kwh"] += float(u["remaining_quantity_kwh"])

    return {
        "committed_trades": committed_trades,
        "unmatched_orders": unmatched_orders,
        "market_records": list(market_records.values()),
    }