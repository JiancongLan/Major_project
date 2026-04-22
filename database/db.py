import os
import sqlite3
from typing import Any

DB_PATH = os.getenv("DB_PATH", "/data/database.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(cur: sqlite3.Cursor, table: str, column: str, col_type: str) -> None:
    rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in rows}
    if column not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS simulation_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            slot INTEGER NOT NULL,
            simulated_datetime TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS slot_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            slot INTEGER NOT NULL,
            simulated_datetime TEXT NOT NULL,
            predicted_demand_kwh REAL NOT NULL,
            actual_demand_kwh REAL NOT NULL,
            abs_error_kwh REAL NOT NULL,
            mae_kwh REAL NOT NULL,
            grid_bought_kwh REAL NOT NULL,
            p2p_trade_kwh REAL NOT NULL,
            trade_pct REAL NOT NULL
        )
        """
    )

    extra_summary_columns = {
        # Market-stage P2P
        "planned_market_p2p_kwh": "REAL NOT NULL DEFAULT 0",
        "planned_market_p2p_value_gbp": "REAL NOT NULL DEFAULT 0",
        "avg_market_p2p_price_gbp_per_kwh": "REAL NOT NULL DEFAULT 0",

        # Balancing-stage internal P2P
        "balancing_internal_p2p_kwh": "REAL NOT NULL DEFAULT 0",
        "balancing_internal_p2p_value_gbp": "REAL NOT NULL DEFAULT 0",

        # Combined total P2P across market + balancing
        "total_internal_p2p_kwh": "REAL NOT NULL DEFAULT 0",
        "total_internal_p2p_value_gbp": "REAL NOT NULL DEFAULT 0",
        "avg_total_p2p_price_gbp_per_kwh": "REAL NOT NULL DEFAULT 0",

        # External settlement
        "grid_import_kwh": "REAL NOT NULL DEFAULT 0",
        "grid_export_kwh": "REAL NOT NULL DEFAULT 0",
        "grid_import_cost_gbp": "REAL NOT NULL DEFAULT 0",
        "grid_export_revenue_gbp": "REAL NOT NULL DEFAULT 0",
        "avg_grid_import_price_gbp_per_kwh": "REAL NOT NULL DEFAULT 0",
        "avg_grid_export_price_gbp_per_kwh": "REAL NOT NULL DEFAULT 0",
        "balancing_penalties_gbp": "REAL NOT NULL DEFAULT 0",
        "net_external_cost_gbp": "REAL NOT NULL DEFAULT 0",
    }

    for col, col_type in extra_summary_columns.items():
        ensure_column(cur, "slot_summary", col, col_type)

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS household_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            slot INTEGER NOT NULL,
            simulated_datetime TEXT NOT NULL,
            h_id TEXT NOT NULL,
            predicted_demand_kwh REAL NOT NULL,
            actual_demand_kwh REAL NOT NULL,
            forecast_error_kwh REAL NOT NULL,
            pv_kwh REAL NOT NULL,
            soc REAL NOT NULL,
            planned_import_kwh REAL NOT NULL,
            planned_export_kwh REAL NOT NULL,
            actual_buy_kwh REAL NOT NULL,
            actual_sell_kwh REAL NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def upsert_state(state: dict[str, Any]) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO simulation_state (id, slot, simulated_datetime, status, updated_at)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            slot=excluded.slot,
            simulated_datetime=excluded.simulated_datetime,
            status=excluded.status,
            updated_at=excluded.updated_at
        """,
        (
            state["slot"],
            state["simulated_datetime"],
            state["status"],
            state["updated_at"],
        ),
    )
    conn.commit()
    conn.close()


def insert_slot_summary(metric: dict[str, Any]) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO slot_summary (
            recorded_at,
            slot,
            simulated_datetime,
            predicted_demand_kwh,
            actual_demand_kwh,
            abs_error_kwh,
            mae_kwh,
            grid_bought_kwh,
            p2p_trade_kwh,
            trade_pct,
            planned_market_p2p_kwh,
            planned_market_p2p_value_gbp,
            avg_market_p2p_price_gbp_per_kwh,
            balancing_internal_p2p_kwh,
            balancing_internal_p2p_value_gbp,
            total_internal_p2p_kwh,
            total_internal_p2p_value_gbp,
            avg_total_p2p_price_gbp_per_kwh,
            grid_import_kwh,
            grid_export_kwh,
            grid_import_cost_gbp,
            grid_export_revenue_gbp,
            avg_grid_import_price_gbp_per_kwh,
            avg_grid_export_price_gbp_per_kwh,
            balancing_penalties_gbp,
            net_external_cost_gbp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            metric["recorded_at"],
            metric["slot"],
            metric["simulated_datetime"],
            metric["predicted_demand_kwh"],
            metric["actual_demand_kwh"],
            metric["abs_error_kwh"],
            metric["mae_kwh"],
            metric["grid_bought_kwh"],
            metric["p2p_trade_kwh"],
            metric["trade_pct"],
            metric.get("planned_market_p2p_kwh", 0.0),
            metric.get("planned_market_p2p_value_gbp", 0.0),
            metric.get("avg_market_p2p_price_gbp_per_kwh", 0.0),
            metric.get("balancing_internal_p2p_kwh", 0.0),
            metric.get("balancing_internal_p2p_value_gbp", 0.0),
            metric.get("total_internal_p2p_kwh", 0.0),
            metric.get("total_internal_p2p_value_gbp", 0.0),
            metric.get("avg_total_p2p_price_gbp_per_kwh", 0.0),
            metric.get("grid_import_kwh", 0.0),
            metric.get("grid_export_kwh", 0.0),
            metric.get("grid_import_cost_gbp", 0.0),
            metric.get("grid_export_revenue_gbp", 0.0),
            metric.get("avg_grid_import_price_gbp_per_kwh", 0.0),
            metric.get("avg_grid_export_price_gbp_per_kwh", 0.0),
            metric.get("balancing_penalties_gbp", 0.0),
            metric.get("net_external_cost_gbp", 0.0),
        ),
    )
    conn.commit()
    conn.close()


def insert_household_snapshots(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO household_snapshots (
            recorded_at,
            slot,
            simulated_datetime,
            h_id,
            predicted_demand_kwh,
            actual_demand_kwh,
            forecast_error_kwh,
            pv_kwh,
            soc,
            planned_import_kwh,
            planned_export_kwh,
            actual_buy_kwh,
            actual_sell_kwh
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["recorded_at"],
                r["slot"],
                r["simulated_datetime"],
                r["h_id"],
                r["predicted_demand_kwh"],
                r["actual_demand_kwh"],
                r["forecast_error_kwh"],
                r["pv_kwh"],
                r["soc"],
                r["planned_import_kwh"],
                r["planned_export_kwh"],
                r["actual_buy_kwh"],
                r["actual_sell_kwh"],
            )
            for r in rows
        ],
    )
    conn.commit()
    conn.close()


def fetch_state() -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM simulation_state WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_summaries() -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT *
        FROM slot_summary
        ORDER BY slot ASC, id ASC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_household_history(h_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT *
        FROM household_snapshots
        WHERE h_id = ?
        ORDER BY slot ASC, id ASC
        """,
        (h_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_household_ids() -> list[str]:
    conn = get_connection()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT DISTINCT h_id
        FROM household_snapshots
        ORDER BY h_id ASC
        """
    ).fetchall()
    conn.close()
    return [row["h_id"] for row in rows]