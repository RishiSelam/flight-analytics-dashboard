"""
Clean the raw airline export and split it into analysis-ready tables.

The raw file has one row per flight x cabin class. Cleaning produces:
  * clean_airline_data.csv  - the cleaned row-level data
  * flights.csv             - one row per flight (operational metrics)
  * bookings.csv            - one row per flight x cabin (passengers & revenue)
  * cleaning_report.json    - what was fixed, imputed or dropped
"""

import json

import numpy as np
import pandas as pd

from src.config import ON_TIME_THRESHOLD_MIN, PROCESSED_DIR

COLUMN_NAMES = {
    "Flight": "flight_number",
    "Date": "flight_date",
    "Airline": "airline",
    "Origin": "origin",
    "Destination": "destination",
    "Aircraft": "aircraft",
    "Scheduled Departure": "scheduled_departure",
    "Actual Departure": "actual_departure",
    "Delay (min)": "departure_variance",
    "Cancelled": "is_cancelled",
    "Distance (mi)": "distance_miles",
    "Cabin Class": "cabin_class",
    "Passengers": "passengers",
    "Ticket Price": "ticket_price",
}
CANCELLED_VALUES = {"yes": 1, "y": 1, "1": 1, "true": 1, "no": 0, "n": 0, "0": 0, "false": 0}
CABIN_ORDER = ["Economy", "Premium Economy", "Business"]
FLIGHT_KEY = ["flight_number", "flight_date"]


def load_raw(path) -> pd.DataFrame:
    # Read everything as text so every type conversion is explicit and auditable.
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _minutes(hhmm: pd.Series) -> pd.Series:
    parts = hhmm.str.split(":", expand=True)
    return pd.to_numeric(parts[0], errors="coerce") * 60 + pd.to_numeric(parts[1], errors="coerce")


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    report = {"raw_rows": len(raw)}
    df = raw.rename(columns=COLUMN_NAMES)
    df = df.apply(lambda col: col.str.strip()).replace("", np.nan)

    # --- Duplicates -------------------------------------------------------
    before = len(df)
    df = df.drop_duplicates()
    report["exact_duplicates_removed"] = before - len(df)

    # --- Text standardisation --------------------------------------------
    df["airline"] = df["airline"].str.title()
    for col in ("origin", "destination", "flight_number"):
        df[col] = df[col].str.upper()
    df["cabin_class"] = df["cabin_class"].str.title()

    # --- Types ------------------------------------------------------------
    df["flight_date"] = pd.to_datetime(df["flight_date"], format="mixed")
    df["is_cancelled"] = df["is_cancelled"].str.lower().map(CANCELLED_VALUES)
    price_had_symbol = df["ticket_price"].str.contains("$", regex=False, na=False).sum()
    df["ticket_price"] = pd.to_numeric(df["ticket_price"].str.replace("$", "", regex=False), errors="coerce")
    for col in ("departure_variance", "distance_miles", "passengers"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    report["prices_with_currency_symbol_fixed"] = int(price_had_symbol)

    # Duplicate keys can hide behind formatting differences, so check again after standardising.
    before = len(df)
    df = df.drop_duplicates(subset=FLIGHT_KEY + ["cabin_class"], keep="first")
    report["key_duplicates_removed"] = before - len(df)

    # --- Invalid values -----------------------------------------------------
    invalid_price = df["ticket_price"] <= 0
    report["invalid_prices_nulled"] = int(invalid_price.sum())
    df.loc[invalid_price, "ticket_price"] = np.nan

    before = len(df)
    df = df[(df["origin"] != df["destination"]) & df["is_cancelled"].notna()]
    report["invalid_rows_dropped"] = before - len(df)

    # --- Missing values ---------------------------------------------------
    df = _fill_departure_fields(df, report)

    missing = df["distance_miles"].isna()
    route_distance = df.groupby(["origin", "destination"])["distance_miles"].transform("median")
    df["distance_miles"] = df["distance_miles"].fillna(route_distance)
    report["distance_imputed_from_route"] = int(missing.sum())

    # Passengers: same flight number & cabin on other days is the best reference.
    missing = df["passengers"].isna()
    typical = df.groupby(["flight_number", "cabin_class"])["passengers"].transform("median").round()
    df["passengers"] = df["passengers"].fillna(typical)
    df.loc[df["is_cancelled"] == 1, "passengers"] = 0
    report["passengers_imputed"] = int(missing.sum())

    missing = df["ticket_price"].isna()
    typical = df.groupby(["origin", "destination", "cabin_class", df["flight_date"].dt.month])["ticket_price"]
    df["ticket_price"] = df["ticket_price"].fillna(typical.transform("median")).round(2)
    report["ticket_prices_imputed"] = int(missing.sum())

    df = _add_derived_columns(df)
    validate(df)
    report["clean_rows"] = len(df)
    report["flights"] = int(df[FLIGHT_KEY].drop_duplicates().shape[0])
    return df.reset_index(drop=True), report


def _fill_departure_fields(df: pd.DataFrame, report: dict) -> pd.DataFrame:
    """Delay and actual departure are redundant, so each can rebuild the other."""
    sched = _minutes(df["scheduled_departure"])
    actual = _minutes(df["actual_departure"])
    operated = df["is_cancelled"] == 0

    # Actual - scheduled, allowing for departures that slip past midnight.
    derived = actual - sched
    derived = derived.where(derived > -180, derived + 1440)

    missing_delay = operated & df["departure_variance"].isna() & derived.notna()
    df.loc[missing_delay, "departure_variance"] = derived[missing_delay]
    report["delays_derived_from_times"] = int(missing_delay.sum())

    missing_actual = operated & df["actual_departure"].isna() & df["departure_variance"].notna()
    rebuilt = (sched + df["departure_variance"]) % 1440
    df.loc[missing_actual, "actual_departure"] = rebuilt[missing_actual].map(
        lambda m: f"{int(m) // 60:02d}:{int(m) % 60:02d}"
    )
    report["actual_departures_rebuilt"] = int(missing_actual.sum())

    # A flight's delay is shared by all its cabin rows; borrow it from a sibling row if needed.
    df["departure_variance"] = df["departure_variance"].fillna(
        df.groupby(FLIGHT_KEY)["departure_variance"].transform("first")
    )
    unrecoverable = operated & df["departure_variance"].isna()
    report["rows_dropped_no_departure_data"] = int(unrecoverable.sum())

    cancelled = df["is_cancelled"] == 1
    df.loc[cancelled, ["departure_variance", "actual_departure"]] = np.nan
    return df[~unrecoverable].copy()


def _add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    df["flight_id"] = df["flight_number"] + "_" + df["flight_date"].dt.strftime("%Y%m%d")
    df["month"] = df["flight_date"].dt.strftime("%Y-%m")
    df["day_of_week"] = df["flight_date"].dt.day_name()
    df["route"] = df["origin"] + "-" + df["destination"]
    df["departure_hour"] = (_minutes(df["scheduled_departure"]) // 60).astype(int)
    df["time_of_day"] = pd.cut(
        df["departure_hour"], bins=[-1, 11, 16, 20, 23],
        labels=["Morning", "Afternoon", "Evening", "Night"],
    ).astype(str)

    # Early departures are not negative delay: delay_minutes floors at zero.
    df["delay_minutes"] = df["departure_variance"].clip(lower=0)
    operated = df["is_cancelled"] == 0
    df["is_on_time"] = np.where(operated, (df["delay_minutes"] < ON_TIME_THRESHOLD_MIN).astype(float), np.nan)
    df["delay_category"] = pd.cut(
        df["delay_minutes"], bins=[-1, 14, 29, 59, 119, 179, np.inf],
        labels=["On time (<15)", "15-29", "30-59", "60-119", "120-179", "180+"],
    ).astype(str).where(operated, "Cancelled")

    df["passengers"] = df["passengers"].astype(int)
    df["distance_miles"] = df["distance_miles"].astype(int)
    df["is_cancelled"] = df["is_cancelled"].astype(int)
    df["revenue"] = (df["passengers"] * df["ticket_price"]).round(2)
    df["cabin_class"] = pd.Categorical(df["cabin_class"], categories=CABIN_ORDER, ordered=True)
    return df.sort_values(["flight_date", "scheduled_departure", "flight_number", "cabin_class"])


def validate(df: pd.DataFrame) -> None:
    """Fail loudly if the cleaned data breaks an assumption the analysis relies on."""
    required = ["flight_id", "flight_date", "airline", "origin", "destination", "cabin_class",
                "passengers", "ticket_price", "distance_miles", "is_cancelled"]
    nulls = df[required].isna().sum()
    assert nulls.sum() == 0, f"Nulls in required columns:\n{nulls[nulls > 0]}"
    assert not df.duplicated(["flight_id", "cabin_class"]).any(), "Duplicate flight/cabin rows"
    assert set(df["cabin_class"].unique()) <= set(CABIN_ORDER), "Unexpected cabin class"
    assert (df["passengers"] >= 0).all() and (df["ticket_price"] > 0).all(), "Negative passengers/prices"
    operated = df["is_cancelled"] == 0
    assert df.loc[operated, "delay_minutes"].notna().all(), "Operated flight without delay value"
    assert df.loc[~operated, "passengers"].eq(0).all(), "Cancelled flight with passengers"
    per_flight = df.groupby("flight_id")[["airline", "origin", "destination", "is_cancelled", "delay_minutes"]]
    assert (per_flight.nunique(dropna=False) <= 1).all().all(), "Flight attributes differ across cabins"


def split_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalise to a flight-level table and a flight x cabin bookings table."""
    flight_cols = [
        "flight_id", "flight_number", "flight_date", "month", "day_of_week", "airline",
        "origin", "destination", "route", "aircraft", "scheduled_departure", "actual_departure",
        "departure_hour", "time_of_day", "departure_variance", "delay_minutes", "delay_category",
        "is_cancelled", "is_on_time", "distance_miles",
    ]
    totals = df.groupby("flight_id", observed=True).agg(passengers=("passengers", "sum"), revenue=("revenue", "sum"))
    flights = df.drop_duplicates("flight_id")[flight_cols].merge(totals, on="flight_id")
    flights["revenue"] = flights["revenue"].round(2)
    bookings = df[["flight_id", "cabin_class", "passengers", "ticket_price", "revenue"]].copy()
    bookings["cabin_class"] = bookings["cabin_class"].astype(str)
    return flights.reset_index(drop=True), bookings.reset_index(drop=True)


def save_outputs(clean_df: pd.DataFrame, flights: pd.DataFrame, bookings: pd.DataFrame, report: dict) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    clean_df.to_csv(PROCESSED_DIR / "clean_airline_data.csv", index=False)
    flights.to_csv(PROCESSED_DIR / "flights.csv", index=False)
    bookings.to_csv(PROCESSED_DIR / "bookings.csv", index=False)
    (PROCESSED_DIR / "cleaning_report.json").write_text(json.dumps(report, indent=2))
