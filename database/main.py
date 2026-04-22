from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel

from db import (
    init_db,
    upsert_state,
    insert_slot_summary,
    insert_household_snapshots,
    fetch_state,
    fetch_summaries,
    fetch_household_history,
    fetch_household_ids,
)


class SimulationState(BaseModel):
    slot: int
    simulated_datetime: str
    status: str
    updated_at: str


class SlotSummary(BaseModel):
    recorded_at: str
    slot: int
    simulated_datetime: str
    predicted_demand_kwh: float
    actual_demand_kwh: float
    abs_error_kwh: float
    mae_kwh: float
    grid_bought_kwh: float
    p2p_trade_kwh: float
    trade_pct: float

    # Market-stage P2P
    planned_market_p2p_kwh: float = 0.0
    planned_market_p2p_value_gbp: float = 0.0
    avg_market_p2p_price_gbp_per_kwh: float = 0.0

    # Balancing-stage internal P2P
    balancing_internal_p2p_kwh: float = 0.0
    balancing_internal_p2p_value_gbp: float = 0.0

    # Combined total P2P across market + balancing
    total_internal_p2p_kwh: float = 0.0
    total_internal_p2p_value_gbp: float = 0.0
    avg_total_p2p_price_gbp_per_kwh: float = 0.0

    # External settlement
    grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    grid_import_cost_gbp: float = 0.0
    grid_export_revenue_gbp: float = 0.0
    avg_grid_import_price_gbp_per_kwh: float = 0.0
    avg_grid_export_price_gbp_per_kwh: float = 0.0

    balancing_penalties_gbp: float = 0.0
    net_external_cost_gbp: float = 0.0


class HouseholdSnapshot(BaseModel):
    recorded_at: str
    slot: int
    simulated_datetime: str
    h_id: str
    predicted_demand_kwh: float
    actual_demand_kwh: float
    forecast_error_kwh: float
    pv_kwh: float
    soc: float
    planned_import_kwh: float
    planned_export_kwh: float
    actual_buy_kwh: float
    actual_sell_kwh: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "database ok"}


@app.put("/state")
def put_state(state: SimulationState):
    upsert_state(state.model_dump())
    return {"status": "stored"}


@app.get("/state")
def get_state():
    state = fetch_state()
    return state if state else {"message": "no state yet"}


@app.post("/summary")
def add_summary(summary: SlotSummary):
    insert_slot_summary(summary.model_dump())
    return {"status": "stored"}


@app.get("/summary")
def list_summary():
    return fetch_summaries()


@app.post("/households/bulk")
def add_household_rows(rows: List[HouseholdSnapshot]):
    insert_household_snapshots([r.model_dump() for r in rows])
    return {"status": "stored", "count": len(rows)}


@app.get("/households")
def list_household_ids():
    return fetch_household_ids()


@app.get("/households/{h_id}")
def household_history(h_id: str):
    return fetch_household_history(h_id)