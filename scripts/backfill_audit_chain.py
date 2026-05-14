"""One-shot backfill: rebuild the audit_chain + audit_roots from trade_records.

Usage:
    python scripts/backfill_audit_chain.py                 # rebuild from default DB
    python scripts/backfill_audit_chain.py --db PATH.db    # rebuild from custom DB
    python scripts/backfill_audit_chain.py --dry-run       # print plan without writing

The backfill is destructive — it wipes audit_chain and audit_roots before
rebuilding from scratch. The trade_records table is never modified. Run on a
backup first if you're nervous.

Ordering rule: ORDER BY timestamp ASC, id ASC. This makes the chain
deterministic across re-runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python scripts/backfill_audit_chain.py` from repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tradememory.audit.chain import ChainBuilder  # noqa: E402
from tradememory.db import Database  # noqa: E402
from tradememory.domain.tdr import TradingDecisionRecord  # noqa: E402


def _trade_iter(db: Database):
    """Yield (record_id, content_hash, chained_at) in chain order."""
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, timestamp, symbol, direction, strategy, confidence, "
            "reasoning, market_context FROM trade_records "
            "ORDER BY timestamp ASC, id ASC"
        ).fetchall()

    for row in rows:
        market_ctx = row["market_context"]
        if isinstance(market_ctx, str):
            try:
                market_ctx = json.loads(market_ctx)
            except json.JSONDecodeError:
                market_ctx = {}

        content_hash = TradingDecisionRecord.compute_hash(
            trade_id=row["id"] or "",
            timestamp=row["timestamp"] or "",
            symbol=row["symbol"] or "",
            direction=row["direction"] or "",
            strategy=row["strategy"] or "",
            confidence=row["confidence"] if row["confidence"] is not None else 0.0,
            reasoning=row["reasoning"] or "",
            market_context=market_ctx,
        )

        # chained_at == the original trade timestamp, normalised to UTC ISO.
        ts = row["timestamp"] or datetime.now(timezone.utc).isoformat()
        if "T" not in ts:
            ts = ts + "T00:00:00+00:00"
        yield row["id"], content_hash, ts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Path to SQLite DB", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Count records but do not write")
    args = parser.parse_args()

    db = Database(args.db)
    count_row = None
    with db.get_connection() as conn:
        count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM trade_records"
        ).fetchone()
    total = count_row["n"] if count_row else 0
    print(f"trade_records: {total} rows")

    if args.dry_run:
        print("Dry run — no writes performed.")
        return 0

    with db.get_connection() as conn:
        builder = ChainBuilder(conn)
        summary = builder.backfill(_trade_iter(db))
    print(
        f"Backfill complete: chained {summary['records']} records, "
        f"built {summary['roots']} daily roots."
    )

    # Sanity verify.
    with db.get_connection() as conn:
        verify = ChainBuilder(conn).verify_chain()
    print(
        f"Chain verify: verified={verify['verified']}, "
        f"checked={verify['checked_count']}, "
        f"first_break={verify['first_break_at']}, "
        f"reason={verify['reason']}"
    )
    return 0 if verify["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
