"""
Airline Operations & Passenger Analytics dashboard.

    streamlit run dashboard.py

Pages: Executive Overview, Operations, Passenger & Revenue.
Sidebar filters apply to every page.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import booking_metrics, executive_kpis, flight_metrics
from src.config import DB_PATH, ON_TIME_THRESHOLD_MIN
from src.database import run_query

st.set_page_config(page_title="Airline Analytics", page_icon="✈️", layout="wide")

# Chart palette (validated categorical order; single hue for single-series charts)
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
CABIN_COLORS = {"Economy": BLUE, "Premium Economy": ORANGE, "Business": AQUA}
INK, INK_2, MUTED, GRID, BASELINE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
DELAY_ORDER = ["On time (<15)", "15-29", "30-59", "60-119", "120-179", "180+", "Cancelled"]


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading data...")
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not DB_PATH.exists():  # e.g. fresh clone / Streamlit Cloud: build everything first
        import run_pipeline
        run_pipeline.main()
    flights = run_query("SELECT * FROM flights")
    bookings = run_query(
        """SELECT b.*, f.airline, f.route, f.origin, f.destination, f.month
           FROM bookings b JOIN flights f USING (flight_id)"""
    )
    one_year = flights["month"].str[:4].nunique() == 1
    for df in (flights, bookings):
        df["month_label"] = pd.to_datetime(df["month"]).dt.strftime("%b" if one_year else "%b %Y")
    return flights, bookings


flights_all, bookings_all = load_data()
months = sorted(flights_all["month"].unique())
month_labels = {m: pd.Timestamp(f"{m}-01").strftime("%b %Y") for m in months}

# --------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    airlines = st.multiselect("Airline", sorted(flights_all["airline"].unique()), placeholder="All airlines")
    origins = st.multiselect("Origin", sorted(flights_all["origin"].unique()), placeholder="All origins")
    destinations = st.multiselect("Destination", sorted(flights_all["destination"].unique()),
                                  placeholder="All destinations")
    month_range = st.select_slider("Month", options=months, value=(months[0], months[-1]),
                                   format_func=month_labels.get)
    cabins = st.multiselect("Cabin", list(CABIN_COLORS), placeholder="All cabins")
    st.caption("Cabin filters passenger and revenue figures; operational metrics are per flight.")


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    mask = df["month"].between(*month_range)
    for col, selected in (("airline", airlines), ("origin", origins), ("destination", destinations)):
        if selected:
            mask &= df[col].isin(selected)
    return df[mask]


flights = apply_filters(flights_all)
bookings = apply_filters(bookings_all)
if cabins:
    bookings = bookings[bookings["cabin_class"].isin(cabins)]
is_filtered = bool(airlines or origins or destinations or cabins or month_range != (months[0], months[-1]))


# --------------------------------------------------------------------------
# Formatting & chart helpers
# --------------------------------------------------------------------------
def fmt_count(n: float) -> str:
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e4:
        return f"{n / 1e3:.1f}K"
    return f"{n:,.0f}"


def fmt_money(n: float) -> str:
    if n >= 1e9:
        return f"${n / 1e9:.2f}B"
    if n >= 1e6:
        return f"${n / 1e6:.1f}M"
    return f"${n:,.0f}"


def style(fig: go.Figure, title: str, height: int = 360, pct_axis: str | None = None) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=INK), x=0, xanchor="left"),
        height=height,
        margin=dict(l=8, r=16, t=48, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=INK_2, size=12),
        hoverlabel=dict(bgcolor="white", bordercolor=GRID, font=dict(color=INK)),
        showlegend=False,
        bargap=0.3,
    )
    fig.update_xaxes(showgrid=False, linecolor=BASELINE, tickfont=dict(color=MUTED), zeroline=False)
    fig.update_yaxes(gridcolor=GRID, gridwidth=1, linecolor=BASELINE, tickfont=dict(color=MUTED), zeroline=False)
    if pct_axis:
        fig.update_layout({f"{pct_axis}axis": dict(tickformat=".0%")})
    return fig


def hbar(df: pd.DataFrame, x: str, y: str, title: str, fmt: str, hover: str, height: int = 360,
         ref: float | None = None, ref_label: str = "") -> go.Figure:
    """Horizontal bar, largest at the top. `fmt` is a d3 format for the value labels."""
    fig = go.Figure(go.Bar(
        x=df[x], y=df[y], orientation="h", marker=dict(color=BLUE, cornerradius=4),
        texttemplate=f"%{{x:{fmt}}}", textposition="outside", textfont=dict(color=INK_2, size=11),
        cliponaxis=False, customdata=df, hovertemplate=hover + "<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(color=INK_2))
    if ref is not None:
        fig.add_vline(x=ref, line=dict(color=MUTED, dash="dot", width=1.5),
                      annotation=dict(text=ref_label, font=dict(color=MUTED, size=11), yanchor="bottom"),
                      annotation_position="top")
    style(fig, title, height)
    fig.update_xaxes(showgrid=True, gridcolor=GRID, tickformat=fmt.replace(".1", ".0"),
                     range=[0, df[x].max() * 1.15])
    return fig


def column_hover(df: pd.DataFrame) -> dict:
    return {name: i for i, name in enumerate(df.columns)}


def kpi_row(items: list[tuple]) -> None:
    """items: (label, value_str, delta_str|None, delta_color)"""
    for col, (label, value, delta, color) in zip(st.columns(len(items)), items):
        col.metric(label, value, delta=delta if is_filtered else None, delta_color=color, border=True)


def pp_delta(current: float, baseline: float) -> str:
    return f"{(current - baseline) * 100:+.1f} pp vs network"


baseline = executive_kpis(flights_all, bookings_all)


def require_data() -> None:
    if flights.empty or bookings.empty:
        st.warning("No flights match the selected filters.")
        st.stop()


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
def executive_overview() -> None:
    st.title("Executive Overview")
    st.caption(f"{month_labels[month_range[0]]} to {month_labels[month_range[1]]}  |  "
               f"On time = departed less than {ON_TIME_THRESHOLD_MIN} minutes late")
    require_data()
    k = executive_kpis(flights, bookings)
    kpi_row([
        ("Total flights", f"{k['total_flights']:,}", None, "off"),
        ("Passengers", fmt_count(k["total_passengers"]), None, "off"),
        ("On-time rate", f"{k['on_time_rate']:.1%}", pp_delta(k["on_time_rate"], baseline["on_time_rate"]), "normal"),
        ("Avg delay (min)", f"{k['avg_delay_minutes']:.1f}",
         f"{k['avg_delay_minutes'] - baseline['avg_delay_minutes']:+.1f} min vs network", "inverse"),
        ("Cancellation rate", f"{k['cancellation_rate']:.1%}",
         pp_delta(k["cancellation_rate"], baseline["cancellation_rate"]), "inverse"),
        ("Revenue", fmt_money(k["total_revenue"]), None, "off"),
    ])

    monthly = flight_metrics(flights, ["month", "month_label"]).sort_values("month")
    monthly_pax = booking_metrics(bookings, ["month", "month_label"]).sort_values("month")

    left, right = st.columns(2)
    with left:
        fig = go.Figure(go.Bar(
            x=monthly["month_label"], y=monthly["flights"], marker=dict(color=BLUE, cornerradius=4),
            customdata=monthly[["on_time_rate", "cancellation_rate"]],
            hovertemplate="<b>%{x}</b><br>Flights: %{y:,}<br>On time: %{customdata[0]:.1%}"
                          "<br>Cancelled: %{customdata[1]:.1%}<extra></extra>",
        ))
        st.plotly_chart(style(fig, "Flights by month"), width="stretch")
    with right:
        by_airline = flight_metrics(flights, "airline").sort_values("on_time_rate", ascending=False)
        c = column_hover(by_airline)
        fig = hbar(by_airline, "on_time_rate", "airline", "On-time rate by airline", ".1%",
                   f"<b>%{{y}}</b><br>On time: %{{x:.1%}}<br>Flights: %{{customdata[{c['flights']}]:,}}",
                   ref=k["on_time_rate"], ref_label="Overall")
        st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        by_airport = flight_metrics(flights, "origin").sort_values("avg_delay_minutes", ascending=False)
        c = column_hover(by_airport)
        fig = hbar(by_airport, "avg_delay_minutes", "origin", "Average departure delay by airport (min)", ".1f",
                   f"<b>%{{y}}</b><br>Avg delay: %{{x:.1f}} min<br>Departures: %{{customdata[{c['flights']}]:,}}"
                   f"<br>On time: %{{customdata[{c['on_time_rate']}]:.1%}}", height=460)
        st.plotly_chart(fig, width="stretch")
    with right:
        fig = go.Figure(go.Scatter(
            x=monthly_pax["month_label"], y=monthly_pax["passengers"], mode="lines+markers",
            line=dict(color=BLUE, width=2), marker=dict(size=8, color=BLUE, line=dict(color="white", width=2)),
            customdata=monthly_pax[["revenue"]],
            hovertemplate="<b>%{x}</b><br>Passengers: %{y:,}<br>Revenue: $%{customdata[0]:,.0f}<extra></extra>",
        ))
        fig = style(fig, "Passenger volume trend", height=460)
        fig.update_layout(hovermode="x")
        fig.update_xaxes(showspikes=True, spikecolor=BASELINE, spikethickness=1, spikedash="solid")
        st.plotly_chart(fig, width="stretch")

    with st.expander("Key insights (full dataset, generated by the pipeline)"):
        from src.config import PROCESSED_DIR
        path = PROCESSED_DIR / "insights.md"
        st.markdown(path.read_text(encoding="utf-8").split("\n", 2)[2] if path.exists() else "Run the pipeline.")


def operations() -> None:
    st.title("Operations")
    require_data()
    k = executive_kpis(flights, bookings)
    kpi_row([
        ("Flights", f"{k['total_flights']:,}", None, "off"),
        ("On-time rate", f"{k['on_time_rate']:.1%}", pp_delta(k["on_time_rate"], baseline["on_time_rate"]), "normal"),
        ("Avg delay (min)", f"{k['avg_delay_minutes']:.1f}",
         f"{k['avg_delay_minutes'] - baseline['avg_delay_minutes']:+.1f} min vs network", "inverse"),
        ("Cancelled", f"{int(flights['is_cancelled'].sum()):,}", None, "off"),
        ("Cancellation rate", f"{k['cancellation_rate']:.1%}",
         pp_delta(k["cancellation_rate"], baseline["cancellation_rate"]), "inverse"),
    ])

    left, right = st.columns(2)
    with left:
        by_airline = flight_metrics(flights, "airline").sort_values("avg_delay_minutes", ascending=False)
        c = column_hover(by_airline)
        fig = hbar(by_airline, "avg_delay_minutes", "airline", "Average delay by airline (min)", ".1f",
                   f"<b>%{{y}}</b><br>Avg delay: %{{x:.1f}} min"
                   f"<br>Delayed 60+ min or cancelled: %{{customdata[{c['disruption_rate']}]:.1%}}",
                   ref=k["avg_delay_minutes"], ref_label="Overall")
        st.plotly_chart(fig, width="stretch")
    with right:
        routes = flight_metrics(flights, "route")
        min_flights = max(20, int(routes["flights"].quantile(0.25)))
        top = routes[routes["flights"] >= min_flights].nlargest(10, "avg_delay_minutes")
        c = column_hover(top)
        fig = hbar(top, "avg_delay_minutes", "route", "Top 10 delayed routes (avg min)", ".1f",
                   f"<b>%{{y}}</b><br>Avg delay: %{{x:.1f}} min<br>Flights: %{{customdata[{c['flights']}]:,}}"
                   f"<br>On time: %{{customdata[{c['on_time_rate']}]:.1%}}")
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Routes with at least {min_flights} flights in the selection.")

    left, right = st.columns(2)
    with left:
        by_airport = flight_metrics(flights, "origin").sort_values("cancellation_rate", ascending=False)
        c = column_hover(by_airport)
        fig = hbar(by_airport, "cancellation_rate", "origin", "Cancellation rate by departure airport", ".1%",
                   f"<b>%{{y}}</b><br>Cancelled: %{{x:.1%}}<br>Departures: %{{customdata[{c['flights']}]:,}}",
                   height=460, ref=k["cancellation_rate"], ref_label="Overall")
        st.plotly_chart(fig, width="stretch")
    with right:
        dist = flights["delay_category"].value_counts().reindex(DELAY_ORDER, fill_value=0)
        share = dist / dist.sum()
        fig = go.Figure(go.Bar(
            x=dist.index, y=dist.values, marker=dict(color=BLUE, cornerradius=4), customdata=share.values,
            texttemplate="%{customdata:.1%}", textposition="outside", textfont=dict(color=INK_2, size=11),
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>Flights: %{y:,}<br>Share: %{customdata:.1%}<extra></extra>",
        ))
        fig = style(fig, "Delay distribution (minutes late)", height=460)
        fig.update_xaxes(tickfont=dict(color=INK_2))
        st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        hours = flight_metrics(flights, "departure_hour")
        fig = go.Figure(go.Bar(
            x=hours["departure_hour"], y=hours["flights"], marker=dict(color=BLUE, cornerradius=4),
            customdata=hours[["avg_delay_minutes", "on_time_rate"]],
            hovertemplate="<b>%{x}:00</b><br>Flights: %{y:,}<br>Avg delay: %{customdata[0]:.1f} min"
                          "<br>On time: %{customdata[1]:.1%}<extra></extra>",
        ))
        fig = style(fig, "Flights by scheduled departure hour")
        fig.update_xaxes(tickmode="linear", dtick=2, ticksuffix=":00")
        st.plotly_chart(fig, width="stretch")
    with right:
        fig = go.Figure(go.Scatter(
            x=hours["departure_hour"], y=hours["avg_delay_minutes"], mode="lines+markers",
            line=dict(color=BLUE, width=2), marker=dict(size=8, color=BLUE, line=dict(color="white", width=2)),
            customdata=hours[["on_time_rate", "flights"]],
            hovertemplate="<b>%{x}:00</b><br>Avg delay: %{y:.1f} min<br>On time: %{customdata[0]:.1%}"
                          "<br>Flights: %{customdata[1]:,}<extra></extra>",
        ))
        fig = style(fig, "Average delay by departure hour (min)")
        fig.update_xaxes(tickmode="linear", dtick=2, ticksuffix=":00")
        fig.update_yaxes(rangemode="tozero")
        st.plotly_chart(fig, width="stretch")

    demand_vs_punctuality(k["on_time_rate"])


def demand_vs_punctuality(network_on_time: float) -> None:
    """Business question: which busy routes run late?"""
    routes = flight_metrics(flights, "route")
    routes = routes[routes["flights"] >= 20]
    if len(routes) < 4:
        return
    busy = routes["passengers"] >= routes["passengers"].quantile(0.75)
    routes["flag"] = busy & (routes["on_time_rate"] < network_on_time)

    fig = go.Figure()
    for flagged, color, name in ((False, BASELINE, "Other routes"), (True, ORANGE, "Busy & below-average on time")):
        d = routes[routes["flag"] == flagged]
        fig.add_trace(go.Scatter(
            x=d["passengers"], y=d["on_time_rate"], mode="markers+text" if flagged else "markers", name=name,
            text=d["route"] if flagged else None, textposition="top center", textfont=dict(color=INK_2, size=11),
            marker=dict(size=11, color=color, line=dict(color="white", width=2)),
            customdata=d[["route", "flights", "avg_delay_minutes"]],
            hovertemplate="<b>%{customdata[0]}</b><br>Passengers: %{x:,}<br>On time: %{y:.1%}"
                          "<br>Avg delay: %{customdata[2]:.1f} min<br>Flights: %{customdata[1]:,}<extra></extra>",
        ))
    fig.add_hline(y=network_on_time, line=dict(color=MUTED, dash="dot", width=1.5),
                  annotation=dict(text="Average on-time rate", font=dict(color=MUTED, size=11)),
                  annotation_position="bottom left")
    fig.add_vline(x=routes["passengers"].quantile(0.75), line=dict(color=MUTED, dash="dot", width=1.5),
                  annotation=dict(text="Top-quartile demand", font=dict(color=MUTED, size=11)),
                  annotation_position="top left")
    fig = style(fig, "Route demand vs punctuality", height=460, pct_axis="y")
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, title=dict(text="Passengers", font=dict(color=MUTED)))
    fig.update_yaxes(title=dict(text="On-time rate", font=dict(color=MUTED)))
    st.plotly_chart(fig, width="stretch")

    flagged = routes[routes["flag"]].sort_values("passengers", ascending=False)
    if len(flagged):
        st.markdown(f"**{len(flagged)} high-demand routes run below the on-time rate.** "
                    "They affect the most passengers, so fix them first:")
        st.dataframe(
            flagged[["route", "flights", "passengers", "on_time_rate", "avg_delay_minutes", "cancellation_rate"]],
            hide_index=True, width="stretch",
            column_config={
                "route": "Route", "flights": "Flights",
                "passengers": st.column_config.NumberColumn("Passengers", format="localized"),
                "on_time_rate": st.column_config.NumberColumn("On-time rate", format="percent"),
                "avg_delay_minutes": st.column_config.NumberColumn("Avg delay (min)", format="%.1f"),
                "cancellation_rate": st.column_config.NumberColumn("Cancellation rate", format="percent"),
            },
        )


def passenger_revenue() -> None:
    st.title("Passenger & Revenue")
    require_data()
    k = executive_kpis(flights, bookings)
    cabin = booking_metrics(bookings, "cabin_class")
    biz_share = cabin.loc[cabin["cabin_class"] == "Business", "revenue"].sum() / max(k["total_revenue"], 1)
    kpi_row([
        ("Passengers", fmt_count(k["total_passengers"]), None, "off"),
        ("Revenue", fmt_money(k["total_revenue"]), None, "off"),
        ("Avg ticket price", f"${k['avg_fare']:,.0f}", None, "off"),
        ("Business share of revenue", f"{biz_share:.1%}", None, "off"),
    ])

    left, right = st.columns(2)
    with left:
        routes = booking_metrics(bookings, "route").nlargest(15, "passengers")
        c = column_hover(routes)
        fig = hbar(routes, "passengers", "route", "Passenger volume by route (top 15)", ",.0f",
                   f"<b>%{{y}}</b><br>Passengers: %{{x:,}}<br>Revenue: $%{{customdata[{c['revenue']}]:,.0f}}",
                   height=500)
        fig.update_traces(texttemplate="%{x:.3s}")
        st.plotly_chart(fig, width="stretch")
    with right:
        by_airline = booking_metrics(bookings, "airline").sort_values("revenue", ascending=False)
        c = column_hover(by_airline)
        fig = hbar(by_airline, "revenue", "airline", "Revenue by airline", "$.3s",
                   f"<b>%{{y}}</b><br>Revenue: $%{{x:,.0f}}<br>Passengers: %{{customdata[{c['passengers']}]:,}}"
                   f"<br>Avg fare: $%{{customdata[{c['avg_ticket_price']}]:,.0f}}", height=500)
        fig.update_xaxes(tickformat="$~s")
        st.plotly_chart(fig, width="stretch")

    cabin = cabin.set_index("cabin_class").reindex([c for c in CABIN_COLORS if c in set(cabin["cabin_class"])])
    left, right = st.columns(2)
    with left:
        fig = go.Figure(go.Bar(
            x=cabin.index, y=cabin["revenue"], marker=dict(color=[CABIN_COLORS[c] for c in cabin.index], cornerradius=4),
            customdata=cabin[["passengers", "avg_ticket_price"]], texttemplate="%{y:$.3s}", textposition="outside",
            textfont=dict(color=INK_2), cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>Revenue: $%{y:,.0f}<br>Passengers: %{customdata[0]:,}"
                          "<br>Avg fare: $%{customdata[1]:,.0f}<extra></extra>",
        ))
        fig = style(fig, "Revenue by cabin class")
        fig.update_yaxes(tickformat="$~s")
        fig.update_xaxes(tickfont=dict(color=INK_2))
        st.plotly_chart(fig, width="stretch")
    with right:
        fares = booking_metrics(bookings, ["airline", "cabin_class"])
        fig = go.Figure()
        for cab in cabin.index:
            d = fares[fares["cabin_class"] == cab]
            fig.add_trace(go.Bar(
                x=d["airline"], y=d["avg_ticket_price"], name=cab,
                marker=dict(color=CABIN_COLORS[cab], cornerradius=3, line=dict(color="white", width=1)),
                hovertemplate=f"<b>%{{x}}</b><br>{cab}: $%{{y:,.0f}}<extra></extra>",
            ))
        fig = style(fig, "Average ticket price by airline and cabin")
        fig.update_layout(showlegend=True, barmode="group", bargap=0.25, bargroupgap=0.05,
                          legend=dict(orientation="h", y=1.1, x=1, xanchor="right"))
        fig.update_yaxes(tickprefix="$")
        fig.update_xaxes(tickfont=dict(color=INK_2))
        st.plotly_chart(fig, width="stretch")

    monthly = booking_metrics(bookings, ["month", "month_label", "cabin_class"]).sort_values("month")
    fig = go.Figure()
    for cab in cabin.index:
        d = monthly[monthly["cabin_class"] == cab]
        fig.add_trace(go.Bar(
            x=d["month_label"], y=d["passengers"], name=cab,
            marker=dict(color=CABIN_COLORS[cab], line=dict(color="white", width=1)),
            hovertemplate=f"<b>%{{x}}</b><br>{cab}: %{{y:,}}<extra></extra>",
        ))
    fig = style(fig, "Monthly passenger trends by cabin", height=400)
    fig.update_layout(showlegend=True, barmode="stack", hovermode="x unified",
                      legend=dict(orientation="h", y=1.1, x=1, xanchor="right", traceorder="normal"))
    st.plotly_chart(fig, width="stretch")

    with st.expander("Top routes by revenue (table)"):
        top = booking_metrics(bookings, "route").nlargest(15, "revenue")
        top["revenue_share"] = top["revenue"] / k["total_revenue"]
        st.dataframe(top, hide_index=True, width="stretch", column_config={
            "route": "Route",
            "passengers": st.column_config.NumberColumn("Passengers", format="localized"),
            "revenue": st.column_config.NumberColumn("Revenue", format="dollar"),
            "avg_ticket_price": st.column_config.NumberColumn("Avg ticket price", format="dollar"),
            "revenue_share": st.column_config.NumberColumn("Share of revenue", format="percent"),
        })


page = st.navigation([
    st.Page(executive_overview, title="Executive Overview", icon="📊", default=True),
    st.Page(operations, title="Operations", icon="🛫"),
    st.Page(passenger_revenue, title="Passenger & Revenue", icon="💳"),
])
page.run()
