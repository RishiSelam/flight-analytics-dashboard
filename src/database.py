"""
SQLite database: schema, loading, and running the named queries in sql/.

Query files hold several queries each, separated by a marker line:

    -- name: airline_performance
    SELECT ...;
"""

import re
import sqlite3
from pathlib import Path

import pandas as pd

from src.config import DB_PATH, SQL_DIR

SCHEMA = """
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS flights;

CREATE TABLE flights (
    flight_id            TEXT PRIMARY KEY,
    flight_number        TEXT NOT NULL,
    flight_date          DATE NOT NULL,
    month                TEXT NOT NULL,      -- YYYY-MM
    day_of_week          TEXT NOT NULL,
    airline              TEXT NOT NULL,
    origin               TEXT NOT NULL,
    destination          TEXT NOT NULL,
    route                TEXT NOT NULL,      -- ORIGIN-DESTINATION
    aircraft             TEXT,
    scheduled_departure  TEXT NOT NULL,      -- HH:MM
    actual_departure     TEXT,               -- NULL when cancelled
    departure_hour       INTEGER NOT NULL,
    time_of_day          TEXT NOT NULL,
    departure_variance   REAL,               -- signed minutes vs schedule; NULL when cancelled
    delay_minutes        REAL,               -- variance floored at 0; NULL when cancelled
    delay_category       TEXT NOT NULL,
    is_cancelled         INTEGER NOT NULL CHECK (is_cancelled IN (0, 1)),
    is_on_time           INTEGER,            -- 1 if delay < 15 min; NULL when cancelled
    distance_miles       INTEGER NOT NULL,
    passengers           INTEGER NOT NULL,
    revenue              REAL NOT NULL
);

CREATE TABLE bookings (
    flight_id     TEXT NOT NULL REFERENCES flights (flight_id),
    cabin_class   TEXT NOT NULL,
    passengers    INTEGER NOT NULL,
    ticket_price  REAL NOT NULL,             -- average fare paid in this cabin
    revenue       REAL NOT NULL,
    PRIMARY KEY (flight_id, cabin_class)
);

CREATE INDEX idx_flights_airline ON flights (airline);
CREATE INDEX idx_flights_route   ON flights (origin, destination);
CREATE INDEX idx_flights_month   ON flights (month);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def create_database(flights: pd.DataFrame, bookings: pd.DataFrame, db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    flights = flights.assign(flight_date=flights["flight_date"].dt.strftime("%Y-%m-%d"))
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        flights.to_sql("flights", conn, if_exists="append", index=False)
        bookings.to_sql("bookings", conn, if_exists="append", index=False)
        conn.execute("VACUUM")


def load_queries(path: Path) -> dict[str, str]:
    """Split a .sql file into {query_name: sql} on '-- name:' markers."""
    text = path.read_text()
    blocks = re.split(r"^--\s*name:\s*(\w+)\s*$", text, flags=re.MULTILINE)
    return {name: sql.strip() for name, sql in zip(blocks[1::2], blocks[2::2])}


def load_all_queries(sql_dir: Path = SQL_DIR) -> dict[str, str]:
    queries = {}
    for path in sorted(sql_dir.glob("*.sql")):
        queries.update(load_queries(path))
    return queries


def run_query(sql: str, db_path: Path = DB_PATH, params: tuple = ()) -> pd.DataFrame:
    with connect(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)
