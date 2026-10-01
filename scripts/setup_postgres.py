"""
setup_postgres.py
=================
CLI script to setup, initialize, and seed PostgreSQL database for QUERYGUARD AI.

Usage:
  python scripts/setup_postgres.py [--seed 500] [--check-only]
"""

import os
import sys
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import postgres_engine


def main():
    parser = argparse.ArgumentParser(description="Initialize PostgreSQL Database for Hospital Appointment Platform")
    parser.add_argument("--seed", type=int, default=500, help="Number of synthetic appointment records to seed")
    parser.add_argument("--check-only", action="store_true", help="Only check connection status without modifying schema")
    args = parser.parse_args()

    print("=" * 72)
    print("QUERYGUARD AI: POSTGRESQL ENVIRONMENT INITIALIZER")
    print("=" * 72)

    if not postgres_engine.is_postgres_available():
        print("ERROR: psycopg2 is not installed. Please run: pip install psycopg2-binary")
        sys.exit(1)

    params = postgres_engine.get_connection_params()
    print("Connecting to PostgreSQL with parameters:")
    for k, v in params.items():
        if k == "password" and v:
            print(f"  {k}: ******")
        else:
            print(f"  {k}: {v}")

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    conn = postgres_engine.get_postgres_connection()
    if not conn:
        print("\n[ERROR] Could not connect to PostgreSQL server.")
        print("Please ensure PostgreSQL is running and credentials are configured via environment variables:")
        print("  set PGHOST=localhost")
        print("  set PGPORT=5432")
        print("  set PGUSER=postgres")
        print("  set PGPASSWORD=yourpassword")
        print("  set PGDATABASE=hospital_db")
        print("\nNote: QUERYGUARD AI automatically falls back gracefully to SQLite when PostgreSQL is offline.")
        sys.exit(1)

    print("\n[OK] Successfully connected to PostgreSQL server!")

    if args.check_only:
        print("Check completed successfully.")
        conn.close()
        return

    print("Applying DDL schema (sql/postgres_schema.sql)...")
    success = postgres_engine.init_postgres_schema(conn)
    if success:
        print("[OK] Schema created successfully with Anti Double-Booking Unique Index.")
    else:
        print("[ERROR] Error applying schema.")
        conn.close()
        sys.exit(1)

    # Collect statistics
    stats = postgres_engine.collect_postgres_statistics(conn)
    print(f"Active tables in schema: {len(stats.get('tables', {}))}")
    print(f"Active indexes in schema: {len(stats.get('indexes', []))}")
    print(f"Database size: {stats.get('db_size_bytes', 0):,} bytes")

    # Run double booking simulation
    print("\nSimulating double-booking prevention check...")
    res = postgres_engine.simulate_double_booking_transaction_postgres(conn)
    print(f"  Transaction 1 status: {res['transaction_1']['status']}")
    print(f"  Transaction 2 status: {res['transaction_2']['status']}")
    print(f"  Double-booking prevented: {res['double_booking_prevented']}")

    conn.close()
    print("\n[OK] PostgreSQL setup complete!")


if __name__ == "__main__":
    main()
