"""
Generate the synthetic raw airline dataset (data/raw/airline_data.csv).

Why synthetic: public flight datasets (e.g. BTS On-Time Performance) contain
delays and cancellations but no passenger counts, fares or cabin classes.
This generator produces one year of flights for six fictional airlines across
15 real US airports, with realistic structure baked in:

  * hub congestion, seasonal weather (winter snow / summer storms),
    delays that build up through the day, and occasional storm days
  * load factors and fares that vary by season, day of week, distance and cabin
  * one row per flight x cabin class (the grain a booking system would export)

It also injects the kind of mess real exports have (inconsistent casing,
mixed date formats, "$" in prices, missing values, duplicates) so the
cleaning step has real work to do.

Run once:  python scripts/generate_raw_data.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
YEAR = 2025
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "airline_data.csv"

# code: (latitude, longitude, congestion factor)
AIRPORTS = {
    "ATL": (33.64, -84.43, 1.00),
    "ORD": (41.97, -87.91, 1.35),
    "DFW": (32.90, -97.04, 1.10),
    "DEN": (39.86, -104.67, 1.15),
    "LAX": (33.94, -118.41, 1.05),
    "JFK": (40.64, -73.78, 1.30),
    "SFO": (37.62, -122.38, 1.25),
    "SEA": (47.45, -122.31, 0.90),
    "MIA": (25.79, -80.29, 1.10),
    "BOS": (42.36, -71.01, 1.20),
    "LAS": (36.08, -115.15, 0.95),
    "PHX": (33.43, -112.01, 0.85),
    "MSP": (44.88, -93.22, 0.95),
    "CLT": (35.21, -80.94, 1.00),
    "EWR": (40.69, -74.17, 1.40),
}
WINTER_AIRPORTS = {"ORD", "DEN", "BOS", "MSP", "JFK", "EWR"}
STORM_AIRPORTS = {"ATL", "DFW", "MIA", "CLT", "JFK", "EWR", "ORD"}

# code: (name, delay multiplier, fare multiplier, hubs)
AIRLINES = {
    "NS": ("Northstar Airlines", 0.85, 1.05, ["MSP", "ORD", "DEN"]),
    "BW": ("Bluewing Airways", 1.00, 1.00, ["ATL", "MIA", "CLT"]),
    "SM": ("Summit Air", 1.30, 0.80, ["DEN", "LAS", "PHX"]),
    "CJ": ("Coastal Jet", 1.15, 0.90, ["JFK", "BOS", "MIA"]),
    "MR": ("Meridian Airlines", 0.90, 1.15, ["DFW", "LAX", "JFK"]),
    "PC": ("Pacific Crest Airways", 1.05, 1.00, ["SEA", "SFO", "LAX"]),
}

# aircraft: {cabin: seats}
AIRCRAFT = {
    "E175": {"Economy": 64, "Business": 12},
    "A320": {"Economy": 126, "Premium Economy": 12, "Business": 12},
    "B737-800": {"Economy": 138, "Premium Economy": 12, "Business": 16},
    "A321": {"Economy": 158, "Premium Economy": 16, "Business": 16},
    "B737 MAX 9": {"Economy": 150, "Premium Economy": 18, "Business": 20},
}
CABIN_LOAD = {"Economy": 0.86, "Premium Economy": 0.78, "Business": 0.70}
CABIN_FARE = {"Economy": 1.0, "Premium Economy": 1.7, "Business": 3.2}

MONTH_DELAY = {1: 1.15, 2: 1.10, 3: 0.90, 4: 0.85, 5: 0.95, 6: 1.30,
               7: 1.35, 8: 1.20, 9: 0.80, 10: 0.80, 11: 0.95, 12: 1.25}
MONTH_DEMAND = {1: 0.80, 2: 0.82, 3: 0.92, 4: 0.90, 5: 0.94, 6: 1.02,
                7: 1.05, 8: 1.00, 9: 0.86, 10: 0.90, 11: 0.92, 12: 0.99}
MONTH_FARE = {1: 0.88, 2: 0.90, 3: 1.00, 4: 0.97, 5: 1.02, 6: 1.14,
              7: 1.16, 8: 1.08, 9: 0.92, 10: 0.95, 11: 1.03, 12: 1.15}
# Monday=0 ... Sunday=6
DOW_DEMAND = {0: 1.02, 1: 0.90, 2: 0.91, 3: 1.00, 4: 1.08, 5: 0.95, 6: 1.07}


def haversine_miles(a: str, b: str) -> int:
    lat1, lon1, _ = AIRPORTS[a]
    lat2, lon2, _ = AIRPORTS[b]
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return int(round(2 * 3958.8 * np.arcsin(np.sqrt(h))))


def pick_aircraft(distance: int, rng: np.random.Generator) -> str:
    if distance < 650:
        return "E175"
    if distance < 1500:
        return rng.choice(["A320", "B737-800"])
    return rng.choice(["A321", "B737 MAX 9"])


def build_schedule(rng: np.random.Generator) -> pd.DataFrame:
    """Each airline flies from its hubs to a handful of destinations (both directions)."""
    rows = []
    airports = list(AIRPORTS)
    for code, (_, _, _, hubs) in AIRLINES.items():
        flight_no = 100 + int(rng.integers(0, 50)) * 10
        for hub in hubs:
            others = [a for a in airports if a != hub]
            for dest in rng.choice(others, size=2, replace=False):
                hub_to_hub = dest in hubs
                frequency = 2 if hub_to_hub or rng.random() < 0.2 else 1
                distance = haversine_miles(hub, dest)
                aircraft = pick_aircraft(distance, rng)
                demand = 1.05 if hub_to_hub else rng.uniform(0.85, 1.05)
                for origin, destination in ((hub, dest), (dest, hub)):
                    for _ in range(frequency):
                        hour = int(rng.choice(range(6, 22), p=_departure_wave()))
                        minute = int(rng.integers(0, 12)) * 5
                        rows.append({
                            "flight": f"{code}{flight_no}",
                            "airline_code": code,
                            "origin": origin,
                            "destination": destination,
                            "aircraft": aircraft,
                            "distance": distance,
                            "sched_minutes": hour * 60 + minute,
                            "route_demand": demand,
                        })
                        flight_no += 1
    return pd.DataFrame(rows)


def _departure_wave() -> np.ndarray:
    # Morning and late-afternoon banks, like a real hub schedule (hours 6..21)
    weights = np.array([8, 10, 9, 7, 6, 5, 6, 7, 8, 9, 9, 8, 6, 5, 4, 3], dtype=float)
    return weights / weights.sum()


def simulate_flights(schedule: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    dates = pd.date_range(f"{YEAR}-01-01", f"{YEAR}-12-31", freq="D")
    flights = schedule.merge(pd.DataFrame({"date": dates}), how="cross")
    # Not every flight operates every day (schedule changes, weekly patterns)
    flights = flights[rng.random(len(flights)) < 0.88].reset_index(drop=True)
    n = len(flights)

    month = flights["date"].dt.month
    dow = flights["date"].dt.dayofweek
    hour = flights["sched_minutes"] // 60

    airline_delay = flights["airline_code"].map({k: v[1] for k, v in AIRLINES.items()})
    congestion = flights["origin"].map({k: v[2] for k, v in AIRPORTS.items()})
    season = month.map(MONTH_DELAY)
    time_of_day = 1 + 0.045 * (hour - 6)

    weather = np.ones(n)
    winter = month.isin([12, 1, 2]) & flights["origin"].isin(WINTER_AIRPORTS)
    summer = month.isin([6, 7, 8]) & flights["origin"].isin(STORM_AIRPORTS)
    weather[winter.to_numpy()] = 1.25
    weather[summer.to_numpy()] = 1.2

    # Storm days: a whole airport has a bad day
    storm_days = {
        (ap, d)
        for ap in AIRPORTS
        for d in dates
        if rng.random() < (0.05 if (d.month in (1, 2, 6, 7, 12)) else 0.015)
    }
    storm = np.array([(o, d) in storm_days for o, d in zip(flights["origin"], flights["date"])])
    weather[storm] *= 2.2

    risk = (airline_delay * congestion * season * time_of_day).to_numpy() * weather

    p_delay = np.clip(0.15 * risk, 0.03, 0.8)
    delayed = rng.random(n) < p_delay
    variance = np.where(
        delayed,
        15 + rng.exponential(scale=26 * np.sqrt(risk)),
        np.clip(rng.normal(-3, 5, n), -15, 14),
    ).round()

    p_cancel = np.clip(0.009 * risk ** 2, 0.002, 0.35)
    cancelled = rng.random(n) < p_cancel

    flights["variance"] = np.where(cancelled, np.nan, variance)
    flights["cancelled"] = cancelled
    flights["demand"] = (
        month.map(MONTH_DEMAND) * dow.map(DOW_DEMAND) * flights["route_demand"]
    ).to_numpy()
    flights["fare_factor"] = (
        month.map(MONTH_FARE)
        * flights["airline_code"].map({k: v[2] for k, v in AIRLINES.items()})
        * np.where(dow.isin([4, 6]), 1.06, 1.0)
    ).to_numpy()
    return flights


def expand_cabins(flights: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    config = pd.DataFrame(
        [(ac, cabin, seats) for ac, cabins in AIRCRAFT.items() for cabin, seats in cabins.items()],
        columns=["aircraft", "cabin", "seats"],
    )
    rows = flights.merge(config, on="aircraft")
    n = len(rows)

    load = np.clip(rows["cabin"].map(CABIN_LOAD) * rows["demand"] * rng.normal(1, 0.06, n), 0.2, 0.99)
    passengers = rng.binomial(rows["seats"], load)
    rows["passengers"] = np.where(rows["cancelled"], 0, passengers)

    base_fare = 60 + 0.12 * rows["distance"]
    fare = base_fare * rows["cabin"].map(CABIN_FARE) * rows["fare_factor"] * rng.lognormal(0, 0.12, n)
    rows["price"] = fare.round(2)
    return rows


def format_raw(rows: pd.DataFrame) -> pd.DataFrame:
    sched = rows["sched_minutes"]
    actual = (sched + rows["variance"]) % 1440
    to_hhmm = lambda m: m.map(lambda v: "" if pd.isna(v) else f"{int(v) // 60:02d}:{int(v) % 60:02d}")

    raw = pd.DataFrame({
        "Flight": rows["flight"],
        "Date": rows["date"].dt.strftime("%Y-%m-%d"),
        "Airline": rows["airline_code"].map({k: v[0] for k, v in AIRLINES.items()}),
        "Origin": rows["origin"],
        "Destination": rows["destination"],
        "Aircraft": rows["aircraft"],
        "Scheduled Departure": to_hhmm(sched),
        "Actual Departure": to_hhmm(actual),
        "Delay (min)": rows["variance"].map(lambda v: "" if pd.isna(v) else str(int(v))),
        "Cancelled": np.where(rows["cancelled"], "Yes", "No"),
        "Distance (mi)": rows["distance"].astype(str),
        "Cabin Class": rows["cabin"],
        "Passengers": rows["passengers"].astype(str),
        "Ticket Price": rows["price"].map(lambda v: f"{v:.2f}"),
    })
    return raw.sort_values(["Date", "Scheduled Departure", "Flight"]).reset_index(drop=True)


def add_noise(raw: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Inject realistic data-quality problems for the cleaning step to handle."""
    raw = raw.copy()
    n = len(raw)
    pick = lambda frac: rng.random(n) < frac

    m = pick(0.03)
    raw.loc[m, "Airline"] = [rng.choice([a.upper(), a.lower(), f" {a}  "]) for a in raw.loc[m, "Airline"]]
    for col in ("Origin", "Destination"):
        m = pick(0.02)
        raw.loc[m, col] = raw.loc[m, col].str.lower()

    m = pick(0.03)
    raw.loc[m, "Date"] = pd.to_datetime(raw.loc[m, "Date"]).dt.strftime("%m/%d/%Y")

    m = pick(0.05)
    raw.loc[m, "Ticket Price"] = "$" + raw.loc[m, "Ticket Price"]
    raw.loc[pick(0.01), "Ticket Price"] = ""
    m = pick(0.002)
    raw.loc[m, "Ticket Price"] = "-" + raw.loc[m, "Ticket Price"].str.lstrip("$")

    raw.loc[pick(0.008), "Passengers"] = ""
    raw.loc[pick(0.01), "Distance (mi)"] = ""

    operated = raw["Cancelled"] == "No"
    raw.loc[pick(0.015) & operated, "Delay (min)"] = ""
    raw.loc[pick(0.005) & operated, "Actual Departure"] = ""

    cancel_styles = {"Yes": ["Y", "1", "TRUE", "yes"], "No": ["N", "0", "FALSE", "no"]}
    m = pick(0.06)
    raw.loc[m, "Cancelled"] = [rng.choice(cancel_styles[v]) for v in raw.loc[m, "Cancelled"]]

    duplicates = raw.sample(frac=0.012, random_state=SEED)
    return pd.concat([raw, duplicates]).sample(frac=1, random_state=SEED).reset_index(drop=True)


def main() -> None:
    rng = np.random.default_rng(SEED)
    schedule = build_schedule(rng)
    flights = simulate_flights(schedule, rng)
    rows = expand_cabins(flights, rng)
    raw = add_noise(format_raw(rows), rng)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(OUTPUT, index=False)
    print(f"Wrote {len(raw):,} rows ({len(flights):,} flights, {len(schedule)} scheduled services) -> {OUTPUT}")


if __name__ == "__main__":
    main()
