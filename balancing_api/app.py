import os
import sys
from pathlib import Path
from typing import List

import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

REPO_ROOT = Path("/repos/balancing_operator")
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from main import final_settle  # type: ignore


class MarketRecord(BaseModel):
    DateTime: str
    h_id: str
    committed_buy_kwh: float
    committed_sell_kwh: float
    unmatched_buy_kwh: float
    unmatched_sell_kwh: float


class ActualRecord(BaseModel):
    DateTime: str
    h_id: str
    actual_buy_kwh: float
    actual_sell_kwh: float


class BalancingInput(BaseModel):
    market_records: List[MarketRecord]
    actual_records: List[ActualRecord]


def to_balancing_market_records(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        dt = pd.to_datetime(r["DateTime"])
        out.append(
            {
                "household_id": str(r["h_id"]),
                "timeslot": dt.strftime("%H:%M"),
                "matched_buy_kwh": float(r.get("committed_buy_kwh", 0.0)),
                "matched_sell_kwh": float(r.get("committed_sell_kwh", 0.0)),
                "unmatched_buy_kwh": float(r.get("unmatched_buy_kwh", 0.0)),
                "unmatched_sell_kwh": float(r.get("unmatched_sell_kwh", 0.0)),
            }
        )
    return out


def to_balancing_actual_records(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        dt = pd.to_datetime(r["DateTime"])
        out.append(
            {
                "household_id": str(r["h_id"]),
                "timeslot": dt.strftime("%H:%M"),
                "actual_buy_kwh": float(r.get("actual_buy_kwh", 0.0)),
                "actual_sell_kwh": float(r.get("actual_sell_kwh", 0.0)),
            }
        )
    return out


app = FastAPI()


@app.get("/health")
def health():
    return {"status": "balancing ok"}


@app.post("/run-slot")
def run_slot(payload: BalancingInput):
    market_records = to_balancing_market_records(
        [r.model_dump() for r in payload.market_records]
    )
    actual_records = to_balancing_actual_records(
        [r.model_dump() for r in payload.actual_records]
    )

    result = final_settle(market_records, actual_records)
    return result