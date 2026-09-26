"""Project paths and shared constants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RAW_DATA = ROOT / "data" / "raw" / "airline_data.csv"
PROCESSED_DIR = ROOT / "data" / "processed"
KPI_DIR = PROCESSED_DIR / "kpis"
DB_PATH = ROOT / "database" / "airline.db"
SQL_DIR = ROOT / "sql"
REPORT_PATH = ROOT / "reports" / "airline_kpi_report.xlsx"

# A flight departing less than 15 minutes late counts as on time (US DOT convention).
ON_TIME_THRESHOLD_MIN = 15
