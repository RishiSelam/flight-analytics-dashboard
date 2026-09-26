"""
Analysis layer.

* run_sql_analysis() executes every named query in sql/ against SQLite and
  saves each result to data/processed/kpis/<name>.csv.
* The pandas functions below compute the same metrics on (filtered) DataFrames;
  the dashboard uses them so filters can recompute KPIs on the fly.
* reconcile() checks that pandas and SQL agree, so the two paths can't drift.
* generate_insights() turns the SQL results into plain-English findings.
"""

import pandas as pd

from src.config import DB_PATH, KPI_DIR
from src.database import load_all_queries, run_query


# --------------------------------------------------------------------------
# SQL analysis
# --------------------------------------------------------------------------
def run_sql_analysis(db_path=DB_PATH) -> dict[str, pd.DataFrame]:
    results = {name: run_query(sql, db_path) for name, sql in load_all_queries().items()}
    KPI_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in results.items():
        df.to_csv(KPI_DIR / f"{name}.csv", index=False)
    return results


# --------------------------------------------------------------------------
# pandas metrics (same definitions as the SQL)
# --------------------------------------------------------------------------
def flight_metrics(flights: pd.DataFrame, by: str | list[str] | None = None) -> pd.DataFrame | pd.Series:
    """Operational metrics; on-time rate and average delay are over operated flights."""
    f = flights.assign(
        disrupted=((flights["is_cancelled"] == 1) | (flights["delay_minutes"] >= 60)).astype(float),
        _all=0,
    )
    out = f.groupby(by if by is not None else "_all", observed=True).agg(
        flights=("flight_id", "size"),
        on_time_rate=("is_on_time", "mean"),
        avg_delay_minutes=("delay_minutes", "mean"),
        cancellation_rate=("is_cancelled", "mean"),
        disruption_rate=("disrupted", "mean"),
        passengers=("passengers", "sum"),
        revenue=("revenue", "sum"),
    )
    if by is None:
        return out.iloc[0] if len(out) else out.reindex([0]).iloc[0]
    return out.reset_index()


def booking_metrics(bookings: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    out = bookings.groupby(by, observed=True).agg(passengers=("passengers", "sum"), revenue=("revenue", "sum"))
    out["avg_ticket_price"] = out["revenue"] / out["passengers"].where(out["passengers"] > 0)
    return out.reset_index()


def executive_kpis(flights: pd.DataFrame, bookings: pd.DataFrame) -> dict:
    ops = flight_metrics(flights)
    passengers = bookings["passengers"].sum()
    revenue = bookings["revenue"].sum()
    return {
        "total_flights": int(ops["flights"]),
        "on_time_rate": ops["on_time_rate"],
        "avg_delay_minutes": ops["avg_delay_minutes"],
        "cancellation_rate": ops["cancellation_rate"],
        "total_passengers": int(passengers),
        "total_revenue": revenue,
        "avg_fare": revenue / passengers if passengers else float("nan"),
    }


def reconcile(flights: pd.DataFrame, bookings: pd.DataFrame, sql_results: dict[str, pd.DataFrame]) -> None:
    """Assert pandas and SQL produce the same headline KPIs."""
    py = executive_kpis(flights, bookings)
    sql = sql_results["executive_kpis"].iloc[0]
    checks = {
        "total_flights": 0,
        "total_passengers": 0,
        "on_time_rate": 1e-4,
        "cancellation_rate": 1e-4,
        "avg_delay_minutes": 0.01,
        "total_revenue": 1.0,
    }
    for key, tolerance in checks.items():
        assert abs(py[key] - sql[key]) <= tolerance, f"{key}: pandas={py[key]} sql={sql[key]}"

    by_airline = flight_metrics(flights, "airline").set_index("airline")["on_time_rate"]
    sql_airline = sql_results["airline_performance"].set_index("airline")["on_time_rate"]
    assert (by_airline - sql_airline).abs().max() < 1e-4, "Airline on-time rates differ"


# --------------------------------------------------------------------------
# Insights
# --------------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{x:.1%}"


def generate_insights(r: dict[str, pd.DataFrame]) -> list[str]:
    kpi = r["executive_kpis"].iloc[0]
    insights = []

    airlines = r["airline_performance"].sort_values("on_time_rate")
    worst, best = airlines.iloc[0], airlines.iloc[-1]
    insights.append(
        f"{worst.airline} has the highest delay rate: {_pct(worst.delay_rate)} of its flights left 15+ minutes "
        f"late (avg delay {worst.avg_delay_minutes:.1f} min), versus {_pct(best.delay_rate)} for "
        f"{best.airline}, the most punctual carrier."
    )

    airports = r["airport_performance"].sort_values("disruption_rate", ascending=False)
    top = airports.iloc[0]
    network_disruption = (airports["disruption_rate"] * airports["departures"]).sum() / airports["departures"].sum()
    calm = airports.iloc[-1]
    insights.append(
        f"{top.airport} is the most disrupted airport: {_pct(top.disruption_rate)} of departures were cancelled or "
        f"60+ minutes late, {top.disruption_rate / network_disruption:.1f}x the network average "
        f"({_pct(network_disruption)}). {calm.airport} was the least disrupted ({_pct(calm.disruption_rate)})."
    )

    cancel = airports.sort_values("cancellation_rate", ascending=False).iloc[0]
    insights.append(
        f"{cancel.airport} has the highest cancellation rate at {_pct(cancel.cancellation_rate)}, against a "
        f"network rate of {_pct(kpi.cancellation_rate)}."
    )

    routes = r["top_revenue_routes"]
    lead = routes.iloc[0]
    insights.append(
        f"{lead.route} is the top revenue route (${lead.revenue / 1e6:,.1f}M, {_pct(lead.revenue_share)} of total "
        f"revenue); the top 10 routes together generate {_pct(routes['revenue_share'].sum())}."
    )

    risky = r["high_demand_poor_performance"]
    if len(risky):
        names = ", ".join(
            f"{row.route} ({row.passengers:,} pax, {_pct(row.on_time_rate)} on time)"
            for row in risky.head(3).itertuples()
        )
        insights.append(
            f"{len(risky)} of the busiest routes (top passenger quartile) run below the {_pct(kpi.on_time_rate)} "
            f"network on-time rate. Biggest: {names}. These need operational attention first, because the "
            f"most passengers are affected."
        )

    hours = r["delay_by_hour"]
    morning = hours[hours["departure_hour"] < 9]
    evening = hours[hours["departure_hour"] >= 18]
    wavg = lambda h, col: (h[col] * h["flights"]).sum() / h["flights"].sum()
    insights.append(
        f"Delays build up through the day: departures before 09:00 average "
        f"{wavg(morning, 'avg_delay_minutes'):.1f} min of delay ({_pct(wavg(morning, 'on_time_rate'))} on time), "
        f"while departures from 18:00 average {wavg(evening, 'avg_delay_minutes'):.1f} min "
        f"({_pct(wavg(evening, 'on_time_rate'))} on time)."
    )

    months = r["monthly_trends"]
    worst_m = months.sort_values("on_time_rate").iloc[0]
    best_m = months.sort_values("on_time_rate").iloc[-1]
    peak = months.sort_values("passengers").iloc[-1]
    insights.append(
        f"{_month_name(worst_m.month)} was the worst month for punctuality ({_pct(worst_m.on_time_rate)} on time) "
        f"and {_month_name(best_m.month)} the best ({_pct(best_m.on_time_rate)}). Passenger volume peaked in "
        f"{_month_name(peak.month)} ({peak.passengers:,} passengers)."
    )

    cabins = r["cabin_class_summary"].set_index("cabin_class")
    biz = cabins.loc["Business"]
    insights.append(
        f"Business class is {_pct(biz.passenger_share)} of passengers but {_pct(biz.revenue_share)} of revenue, "
        f"with an average fare of ${biz.avg_ticket_price:,.0f} versus "
        f"${cabins.loc['Economy', 'avg_ticket_price']:,.0f} in Economy."
    )
    return insights


def _month_name(month: str) -> str:
    return pd.Timestamp(f"{month}-01").strftime("%B")


def save_insights(insights: list[str]) -> None:
    KPI_DIR.parent.mkdir(parents=True, exist_ok=True)
    text = "# Key Insights\n\n" + "\n".join(f"- {line}" for line in insights) + "\n"
    (KPI_DIR.parent / "insights.md").write_text(text, encoding="utf-8")
