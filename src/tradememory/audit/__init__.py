"""Audit chain — tamper-evident hash chain over trading decision records.

The chain links each TDR's content hash to the previous record via
`chained_hash = SHA256(prev_chained_hash || content_hash)`. Tampering with
any historical record invalidates every subsequent link in the chain.

Daily Merkle roots provide a compact verification anchor; future phases
will publish these roots to RFC 3161 TSA / OpenTimestamps / blockchain
for external time-binding.
"""

from .chain import (
    AuditChainEntry,
    ChainBuilder,
    DailyRoot,
    GENESIS_HASH,
    chained_hash,
)
from .merkle import merkle_root

__all__ = [
    "AuditChainEntry",
    "ChainBuilder",
    "DailyRoot",
    "GENESIS_HASH",
    "chained_hash",
    "merkle_root",
]
