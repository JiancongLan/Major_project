import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

HOUSEHOLD_IDS = [x.strip() for x in os.getenv("HOUSEHOLD_IDS", "").split(",") if x.strip()]
OUTPUT_ROOT = Path(os.getenv("OUTPUT_ROOT", "/shared/outputs"))
TICK_SECONDS = float(os.getenv("TICK_SECONDS", "1.0"))

MAX_SLOTS_RAW = os.getenv("MAX_SLOTS", "").strip()
MAX_SLOTS = int(MAX_SLOTS_RAW) if MAX_SLOTS_RAW else None

CONTROL_FILE = Path(os.getenv("CONTROL_FILE", "/control/sim_control.json"))

MARKET_URL = os.getenv("MARKET_URL", "http://market:8000")
BALANCING_URL = os.getenv("BALANCING_URL", "http://balancing:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "http://database:8000")

_LAST_CONTROL = {"pause_simulation": False, "tick_seconds": TICK_SECONDS}
_LAST_CONTROL_MTIME_NS = None


def _clamp_tick_seconds(value) -> float:
    try:
        return max(float(value), 0.05)
    except Exception:
        return max(TICK_SECONDS, 0.05)


def load_runtime_control() -> tuple[bool, float]:
    global _LAST_CONTROL_MTIME_NS

    pause_simulation = bool(_LAST_CONTROL.get("pause_simulation", False))
    tick_seconds = _clamp_tick_seconds(_LAST_CONTROL.get("tick_seconds", TICK_SECONDS))

    if CONTROL_FILE.exists():
        try:
            mtime_ns = CONTROL_FILE.stat().st_mtime_ns
            if mtime_ns != _LAST_CONTROL_MTIME_NS:
                with open(CONTROL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)

                pause_simulation = bool(data.get("pause_simulation", pause_simulation))
                tick_seconds = _clamp_tick_seconds(data.get("tick_seconds", tick_seconds))

                _LAST_CONTROL.update(
                    {
                        "pause_simulation": pause_simulation,
                        "tick_seconds": tick_seconds,
                    }
                )
                _LAST_CONTROL_MTIME_NS = mtime_ns
        except Exception:
            pass

    return pause_simulation, tick_seconds


def wait_for(url: str):
    while True:
        try:
            r = requests.get(url, timeout=3)
            if r.ok:
                return
        except Exception:
            pass
        time.sleep(1)


def wait_for_household_files():
    while True:
        ok = True
        for h_id in HOUSEHOLD_IDS:
            base = OUTPUT_ROOT / h_id
            needed = [
                base / "predicted_results.csv",
                base / "market_input.csv",
                base / "actual_records.csv",
            ]
            if not all(p.exists() for p in needed):
                ok = False
                break
        if ok:
            return
        time.sleep(1)


def load_all():
    predicted = {}
    market = {}
    actual_records = {}

    for h_id in HOUSEHOLD_IDS:
        base = OUTPUT_ROOT / h_id
        predicted[h_id] = pd.read_csv(base / "predicted_results.csv")
        market[h_id] = pd.read_csv(base / "market_input.csv")
        actual_records[h_id] = pd.read_csv(base / "actual_records.csv")

    return predicted, market, actual_records


def validate_household_alignment(predicted_map, market_map, actual_rec_map):
    for h_id in HOUSEHOLD_IDS:
        predicted_df = predicted_map[h_id]
        market_df = market_map[h_id]
        actual_df = actual_rec_map[h_id]

        for name, df in [
            ("predicted_results.csv", predicted_df),
            ("market_input.csv", market_df),
            ("actual_records.csv", actual_df),
        ]:
            if "DateTime" not in df.columns:
                raise ValueError(f"{h_id}: missing DateTime column in {name}")

        if len(predicted_df) != len(market_df) or len(predicted_df) != len(actual_df):
            raise ValueError(
                f"{h_id}: row count mismatch "
                f"(predicted={len(predicted_df)}, market={len(market_df)}, actual_records={len(actual_df)})"
            )

        pred_dt = predicted_df["DateTime"].astype(str).reset_index(drop=True)
        market_dt = market_df["DateTime"].astype(str).reset_index(drop=True)
        actual_dt = actual_df["DateTime"].astype(str).reset_index(drop=True)

        if not pred_dt.equals(market_dt):
            mismatch_idx = (pred_dt != market_dt).idxmax()
            raise ValueError(
                f"{h_id}: DateTime mismatch between predicted_results.csv and market_input.csv "
                f"at row {mismatch_idx}: {pred_dt.iloc[mismatch_idx]} vs {market_dt.iloc[mismatch_idx]}"
            )

        if not pred_dt.equals(actual_dt):
            mismatch_idx = (pred_dt != actual_dt).idxmax()
            raise ValueError(
                f"{h_id}: DateTime mismatch between predicted_results.csv and actual_records.csv "
                f"at row {mismatch_idx}: {pred_dt.iloc[mismatch_idx]} vs {actual_dt.iloc[mismatch_idx]}"
            )


def post_json(url: str, payload):
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def put_json(url: str, payload):
    r = requests.put(url, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def _safe_float(x) -> float:
    if x is None or x == "":
        return 0.0
    return float(x)


def _get_first(record: dict, *keys, default=None):
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return default


def summarize_financials(market_resp: dict, balancing_resp: dict) -> dict:
    committed_trades = market_resp.get("committed_trades", [])
    part1 = (
        balancing_resp.get("part_1_unmatched_merged_table")
        or balancing_resp.get("part_1_unmatched_table")
        or []
    )
    part2 = balancing_resp.get("part_2_deviation_merged_table", [])

    # Market-stage priced P2P
    planned_market_p2p_kwh = 0.0
    planned_market_p2p_value_gbp = 0.0

    for trade in committed_trades:
        qty = _safe_float(_get_first(trade, "quantity_kwh", "quantity", "qty", default=0.0))
        price = _safe_float(_get_first(trade, "trade_price", "price", "unit_price", default=0.0))

        value_raw = _get_first(trade, "trade_value", "value", "matched_value_gbp", default=None)
        if value_raw is None:
            value = qty * price
        else:
            value = _safe_float(value_raw)
            if value == 0.0 and qty > 0.0 and price > 0.0:
                value = qty * price

        planned_market_p2p_kwh += qty
        planned_market_p2p_value_gbp += value

    # Balancing-stage internal P2P
    # Count shortage rows only to avoid double-counting buyer/seller mirror rows.
    balancing_internal_p2p_kwh = 0.0
    balancing_internal_p2p_value_gbp = 0.0

    for row in part2:
        deviation_type = str(row.get("deviation_type", "")).lower().strip()
        if deviation_type != "shortage":
            continue

        kwh = _safe_float(row.get("internal_matched_kwh", 0.0))
        amount = _safe_float(_get_first(row, "internal_trade_amount", default=0.0))

        if amount == 0.0 and kwh > 0.0:
            internal_price = _safe_float(
                _get_first(row, "internal_price_used", "internal_price", default=0.0)
            )
            amount = kwh * internal_price

        balancing_internal_p2p_kwh += kwh
        balancing_internal_p2p_value_gbp += amount

    total_internal_p2p_kwh = planned_market_p2p_kwh + balancing_internal_p2p_kwh
    total_internal_p2p_value_gbp = planned_market_p2p_value_gbp + balancing_internal_p2p_value_gbp

    avg_market_p2p_price_gbp_per_kwh = (
        0.0 if planned_market_p2p_kwh == 0.0
        else planned_market_p2p_value_gbp / planned_market_p2p_kwh
    )

    avg_total_p2p_price_gbp_per_kwh = (
        0.0 if total_internal_p2p_kwh == 0.0
        else total_internal_p2p_value_gbp / total_internal_p2p_kwh
    )

    # External grid settlement
    grid_import_kwh = 0.0
    grid_export_kwh = 0.0
    grid_import_cost_gbp = 0.0
    grid_export_revenue_gbp = 0.0
    balancing_penalties_gbp = 0.0

    def consume_grid_rows(rows):
        nonlocal grid_import_kwh
        nonlocal grid_export_kwh
        nonlocal grid_import_cost_gbp
        nonlocal grid_export_revenue_gbp
        nonlocal balancing_penalties_gbp

        for row in rows:
            direction = str(
                _get_first(
                    row,
                    "final_grid_trade_direction",
                    "grid_trade_direction",
                    "trade_direction",
                    "direction",
                    default="",
                )
            ).lower().strip()

            kwh = _safe_float(
                _get_first(
                    row,
                    "final_grid_kwh",
                    "grid_kwh",
                    "grid_trade_kwh",
                    "unmatched_grid_kwh",
                    "unmatched_buy_kwh",
                    "unmatched_sell_kwh",
                    default=0.0,
                )
            )

            gross_amount = _get_first(
                row,
                "final_grid_amount",
                "gross_grid_amount",
                "grid_trade_amount",
                "grid_amount",
                default=None,
            )

            if gross_amount is None:
                unit_price = _safe_float(
                    _get_first(
                        row,
                        "final_settlement_unit_price",
                        "settlement_unit_price",
                        "unit_price",
                        "grid_price",
                        default=0.0,
                    )
                )
                amount = kwh * unit_price
            else:
                amount = abs(_safe_float(gross_amount))

            penalty = abs(
                _safe_float(
                    _get_first(
                        row,
                        "penalty_amount",
                        "penalty",
                        "penalty_gbp",
                        default=0.0,
                    )
                )
            )

            if direction == "buy_from_grid":
                grid_import_kwh += kwh
                grid_import_cost_gbp += amount
                balancing_penalties_gbp += penalty
            elif direction == "sell_to_grid":
                grid_export_kwh += kwh
                grid_export_revenue_gbp += amount
                balancing_penalties_gbp += penalty
            else:
                balancing_penalties_gbp += penalty

    consume_grid_rows(part1)
    consume_grid_rows(part2)

    avg_grid_import_price_gbp_per_kwh = (
        0.0 if grid_import_kwh == 0.0
        else grid_import_cost_gbp / grid_import_kwh
    )

    avg_grid_export_price_gbp_per_kwh = (
        0.0 if grid_export_kwh == 0.0
        else grid_export_revenue_gbp / grid_export_kwh
    )

    net_external_cost_gbp = (
        grid_import_cost_gbp
        - grid_export_revenue_gbp
        + balancing_penalties_gbp
    )

    return {
        # Market-only diagnostics
        "planned_market_p2p_kwh": planned_market_p2p_kwh,
        "planned_market_p2p_value_gbp": planned_market_p2p_value_gbp,
        "avg_market_p2p_price_gbp_per_kwh": avg_market_p2p_price_gbp_per_kwh,

        # Balancing-added internal matching
        "balancing_internal_p2p_kwh": balancing_internal_p2p_kwh,
        "balancing_internal_p2p_value_gbp": balancing_internal_p2p_value_gbp,

        # Total internal P2P across both stages
        "total_internal_p2p_kwh": total_internal_p2p_kwh,
        "total_internal_p2p_value_gbp": total_internal_p2p_value_gbp,
        "avg_total_p2p_price_gbp_per_kwh": avg_total_p2p_price_gbp_per_kwh,

        # External settlement
        "grid_import_kwh": grid_import_kwh,
        "grid_export_kwh": grid_export_kwh,
        "grid_import_cost_gbp": grid_import_cost_gbp,
        "grid_export_revenue_gbp": grid_export_revenue_gbp,
        "avg_grid_import_price_gbp_per_kwh": avg_grid_import_price_gbp_per_kwh,
        "avg_grid_export_price_gbp_per_kwh": avg_grid_export_price_gbp_per_kwh,
        "balancing_penalties_gbp": balancing_penalties_gbp,
        "net_external_cost_gbp": net_external_cost_gbp,
    }


if __name__ == "__main__":
    wait_for(f"{MARKET_URL}/health")
    wait_for(f"{BALANCING_URL}/health")
    wait_for(f"{DATABASE_URL}/health")
    wait_for_household_files()

    predicted_map, market_map, actual_rec_map = load_all()
    validate_household_alignment(predicted_map, market_map, actual_rec_map)

    total_slots = min(len(df) for df in market_map.values())
    if MAX_SLOTS is not None:
        total_slots = min(total_slots, MAX_SLOTS)

    next_slot_earliest = time.monotonic()

    for slot in range(total_slots):
        while True:
            pause_simulation, tick_seconds = load_runtime_control()
            if pause_simulation:
                next_slot_earliest = time.monotonic()
                time.sleep(0.2)
                continue

            now = time.monotonic()
            if now < next_slot_earliest:
                time.sleep(min(0.2, next_slot_earliest - now))
                continue

            break

        slot_started_at = time.monotonic()

        slot_market_rows = []
        slot_actual_rows = []
        household_rows = []

        simulated_dt = None
        predicted_total = 0.0
        actual_total = 0.0
        abs_error_total = 0.0

        for h_id in HOUSEHOLD_IDS:
            m_row = market_map[h_id].iloc[slot].to_dict()
            a_row = actual_rec_map[h_id].iloc[slot].to_dict()
            p_row = predicted_map[h_id].iloc[slot].to_dict()

            if simulated_dt is None:
                simulated_dt = str(m_row["DateTime"])

            slot_market_rows.append(
                {
                    "DateTime": str(m_row["DateTime"]),
                    "h_id": str(m_row["h_id"]) if "h_id" in m_row else str(h_id),
                    "import_energy": float(m_row["import_energy"]),
                    "export_energy": float(m_row["export_energy"]),
                }
            )

            slot_actual_rows.append(
                {
                    "DateTime": str(a_row["DateTime"]),
                    "h_id": str(a_row["h_id"]) if "h_id" in a_row else str(h_id),
                    "actual_buy_kwh": float(a_row["actual_buy_kwh"]),
                    "actual_sell_kwh": float(a_row["actual_sell_kwh"]),
                }
            )

            predicted_total += float(p_row["predicted_demand_kwh"])
            actual_total += float(p_row["actual_demand_kwh"])
            abs_error_total += abs(float(p_row["forecast_error_kwh"]))

            household_rows.append(
                {
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "slot": slot,
                    "simulated_datetime": simulated_dt,
                    "h_id": h_id,
                    "predicted_demand_kwh": float(p_row["predicted_demand_kwh"]),
                    "actual_demand_kwh": float(p_row["actual_demand_kwh"]),
                    "forecast_error_kwh": float(p_row["forecast_error_kwh"]),
                    "pv_kwh": float(p_row["pv_kwh"]),
                    "soc": float(p_row["soc"]),
                    "planned_import_kwh": float(m_row["import_energy"]),
                    "planned_export_kwh": float(m_row["export_energy"]),
                    "actual_buy_kwh": float(a_row["actual_buy_kwh"]),
                    "actual_sell_kwh": float(a_row["actual_sell_kwh"]),
                }
            )

        market_resp = post_json(f"{MARKET_URL}/run-slot", slot_market_rows)
        balancing_resp = post_json(
            f"{BALANCING_URL}/run-slot",
            {
                "market_records": market_resp["market_records"],
                "actual_records": slot_actual_rows,
            },
        )

        planned_p2p_kwh = sum(float(t["quantity_kwh"]) for t in market_resp["committed_trades"])
        planned_grid_buy_kwh = sum(float(r["unmatched_buy_kwh"]) for r in market_resp["market_records"])

        part2 = balancing_resp["part_2_deviation_merged_table"]
        deviation_p2p_kwh = sum(
            float(r["internal_matched_kwh"])
            for r in part2
            if str(r.get("deviation_type", "")).lower() == "shortage"
        )
        deviation_grid_buy_kwh = sum(
            float(r["final_grid_kwh"])
            for r in part2
            if str(r.get("final_grid_trade_direction", "")).lower() == "buy_from_grid"
        )

        p2p_trade_kwh = planned_p2p_kwh + deviation_p2p_kwh
        grid_bought_kwh = planned_grid_buy_kwh + deviation_grid_buy_kwh
        trade_pct = 0.0 if (p2p_trade_kwh + grid_bought_kwh) == 0 else (
            100.0 * p2p_trade_kwh / (p2p_trade_kwh + grid_bought_kwh)
        )
        mae = abs_error_total / len(HOUSEHOLD_IDS)

        financials = summarize_financials(
            market_resp=market_resp,
            balancing_resp=balancing_resp,
        )

        put_json(
            f"{DATABASE_URL}/state",
            {
                "slot": slot,
                "simulated_datetime": simulated_dt,
                "status": "running" if slot < total_slots - 1 else "completed",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        post_json(
            f"{DATABASE_URL}/summary",
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "slot": slot,
                "simulated_datetime": simulated_dt,
                "predicted_demand_kwh": predicted_total,
                "actual_demand_kwh": actual_total,
                "abs_error_kwh": abs_error_total,
                "mae_kwh": mae,
                "grid_bought_kwh": grid_bought_kwh,
                "p2p_trade_kwh": p2p_trade_kwh,
                "trade_pct": trade_pct,
                **financials,
            },
        )

        post_json(f"{DATABASE_URL}/households/bulk", household_rows)

        print(
            f"[slot {slot}] simulated_datetime={simulated_dt} "
            f"p2p_trade_kwh={p2p_trade_kwh:.3f} "
            f"grid_bought_kwh={grid_bought_kwh:.3f} "
            f"total_internal_p2p_value_gbp={financials['total_internal_p2p_value_gbp']:.3f} "
            f"net_external_cost_gbp={financials['net_external_cost_gbp']:.3f} "
            f"trade_pct={trade_pct:.2f}"
        )

        if tick_seconds > 0:
            time.sleep(tick_seconds)