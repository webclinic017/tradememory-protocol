"""Merkle tree over hex SHA-256 leaves.

Pure Python, no dependencies. The implementation uses the same duplicate-
last-leaf rule as Bitcoin to handle odd levels, so a tree with one leaf
returns that leaf as the root.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, List


def _hash_pair(a: str, b: str) -> str:
    """SHA256 of the concatenated raw bytes of two hex hashes."""
    return hashlib.sha256(bytes.fromhex(a) + bytes.fromhex(b)).hexdigest()


def merkle_root(leaves: Iterable[str]) -> str:
    """Compute Merkle root over an iterable of hex SHA-256 leaves.

    Empty input returns the zero hash (64 chars of '0') — used as a sentinel
    for empty audit periods. Odd levels duplicate the last node before
    pairing (Bitcoin-compatible).
    """
    level: List[str] = [leaf.lower() for leaf in leaves]
    if not level:
        return "0" * 64
    if len(level) == 1:
        return level[0]

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        next_level: List[str] = []
        for i in range(0, len(level), 2):
            next_level.append(_hash_pair(level[i], level[i + 1]))
        level = next_level

    return level[0]
