"""
Run the full pipeline:

    raw CSV -> clean -> SQLite -> SQL analysis -> KPI outputs -> Excel report

Usage:  python run_pipeline.py
"""

import time

from src import analysis, data_cleaning, database, report_generator
from src.config import DB_PATH, KPI_DIR, PROCESSED_DIR, RAW_DATA, REPORT_PATH


def step(message: str) -> None:
    print(f"\n==> {message}")


def main() -> None:
    start = time.perf_counter()

    step(f"Loading raw data from {RAW_DATA.relative_to(RAW_DATA.parents[2])}")
    raw = data_cleaning.load_raw(RAW_DATA)
    print(f"    {len(raw):,} rows, {raw.shape[1]} columns")

    step("Cleaning and validating")
    clean_df, report = data_cleaning.clean(raw)
    flights, bookings = data_cleaning.split_tables(clean_df)
    data_cleaning.save_outputs(clean_df, flights, bookings, report)
    for key, value in report.items():
        print(f"    {key:<36} {value:>8,}")
    print(f"    -> {len(flights):,} flights, {len(bookings):,} cabin bookings saved to {PROCESSED_DIR.name}/")

    step(f"Building SQLite database ({DB_PATH.name})")
    database.create_database(flights, bookings)

    step("Running SQL analysis")
    results = analysis.run_sql_analysis()
    print(f"    {len(results)} queries -> {KPI_DIR.relative_to(PROCESSED_DIR.parent.parent)}/")

    step("Reconciling pandas KPIs against SQL")
    analysis.reconcile(flights, bookings, results)
    print("    pandas and SQL agree")

    step("Generating insights")
    insights = analysis.generate_insights(results)
    analysis.save_insights(insights)
    for line in insights:
        print(f"    - {line}")

    step("Writing Excel report")
    report_generator.build_report(results, insights, report)
    print(f"    -> {REPORT_PATH.relative_to(REPORT_PATH.parents[1])}")

    print(f"\nPipeline finished in {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    main()
