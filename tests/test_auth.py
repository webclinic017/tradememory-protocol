"""Tests for tradememory.auth — bearer-token middleware + tenant routing.

Covers:
  - parser handles whitespace, missing tenant, multiple entries
  - middleware: open mode (no env) → all requests pass anonymous
  - middleware: configured mode → valid bearer → tenant attached
  - middleware: configured mode → missing / bad bearer → 401
  - exempt paths bypass auth even when configured
  - tenant_id column scaffold present after schema init
"""

from __future__ import annotations

import os
import sqlite3

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tradememory.auth import (
    AuthContext,
    BearerAuthMiddleware,
    DEFAULT_TENANT,
    _extract_bearer,
    _parse_api_keys,
    auth_enabled,
    load_api_keys,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parse_api_keys_simple_pair():
    assert _parse_api_keys("abc:acme") == {"abc": "acme"}


def test_parse_api_keys_multiple_entries():
    parsed = _parse_api_keys("k1:t1,k2:t2,k3:t3")
    assert parsed == {"k1": "t1", "k2": "t2", "k3": "t3"}


def test_parse_api_keys_bare_key_uses_default_tenant():
    assert _parse_api_keys("sk-test-1") == {"sk-test-1": DEFAULT_TENANT}


def test_parse_api_keys_whitespace_tolerant():
    parsed = _parse_api_keys(" k1 : t1 , k2:t2 , , k3 ")
    assert parsed == {"k1": "t1", "k2": "t2", "k3": DEFAULT_TENANT}


def test_parse_api_keys_empty_returns_empty():
    assert _parse_api_keys("") == {}


def test_parse_api_keys_key_with_empty_tenant_uses_default():
    assert _parse_api_keys("k1:") == {"k1": DEFAULT_TENANT}


# ---------------------------------------------------------------------------
# load_api_keys / auth_enabled — env-driven
# ---------------------------------------------------------------------------

def test_auth_disabled_when_env_unset(monkeypatch):
    monkeypatch.delenv("TRADEMEMORY_API_KEYS", raising=False)
    assert auth_enabled() is False
    assert load_api_keys() == {}


def test_auth_enabled_when_env_set(monkeypatch):
    monkeypatch.setenv("TRADEMEMORY_API_KEYS", "secret:tenant1")
    assert auth_enabled() is True
    assert load_api_keys() == {"secret": "tenant1"}


def test_auth_disabled_when_env_blank(monkeypatch):
    monkeypatch.setenv("TRADEMEMORY_API_KEYS", "   ")
    assert auth_enabled() is False


# ---------------------------------------------------------------------------
# Bearer extractor
# ---------------------------------------------------------------------------

def test_extract_bearer_normal():
    assert _extract_bearer("Bearer abc") == "abc"


def test_extract_bearer_case_insensitive_scheme():
    assert _extract_bearer("bearer xyz") == "xyz"


def test_extract_bearer_missing_token():
    assert _extract_bearer("Bearer ") is None


def test_extract_bearer_wrong_scheme():
    assert _extract_bearer("Basic abc") is None


def test_extract_bearer_none():
    assert _extract_bearer(None) is None


# ---------------------------------------------------------------------------
# Middleware integration
# ---------------------------------------------------------------------------

def _app_with_middleware() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/protected")
    def protected(request: Request):
        auth: AuthContext = request.state.auth
        return {
            "tenant_id": auth.tenant_id,
            "anonymous": auth.is_anonymous,
        }

    return app


def test_middleware_open_mode_passes_through(monkeypatch):
    monkeypatch.delenv("TRADEMEMORY_API_KEYS", raising=False)
    client = TestClient(_app_with_middleware())
    r = client.get("/protected")
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == DEFAULT_TENANT
    assert body["anonymous"] is True


def test_middleware_blocks_request_without_auth(monkeypatch):
    monkeypatch.setenv("TRADEMEMORY_API_KEYS", "secret:acme")
    client = TestClient(_app_with_middleware())
    r = client.get("/protected")
    assert r.status_code == 401


def test_middleware_blocks_request_with_wrong_key(monkeypatch):
    monkeypatch.setenv("TRADEMEMORY_API_KEYS", "secret:acme")
    client = TestClient(_app_with_middleware())
    r = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_middleware_accepts_valid_key_and_attaches_tenant(monkeypatch):
    monkeypatch.setenv("TRADEMEMORY_API_KEYS", "secret:acme")
    client = TestClient(_app_with_middleware())
    r = client.get("/protected", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["anonymous"] is False


def test_middleware_health_exempt_even_when_configured(monkeypatch):
    monkeypatch.setenv("TRADEMEMORY_API_KEYS", "secret:acme")
    client = TestClient(_app_with_middleware())
    r = client.get("/health")
    assert r.status_code == 200


def test_middleware_multiple_keys_route_to_different_tenants(monkeypatch):
    monkeypatch.setenv("TRADEMEMORY_API_KEYS", "k1:t1,k2:t2")
    client = TestClient(_app_with_middleware())
    r1 = client.get("/protected", headers={"Authorization": "Bearer k1"})
    r2 = client.get("/protected", headers={"Authorization": "Bearer k2"})
    assert r1.json()["tenant_id"] == "t1"
    assert r2.json()["tenant_id"] == "t2"


def test_middleware_rejects_basic_auth(monkeypatch):
    monkeypatch.setenv("TRADEMEMORY_API_KEYS", "secret:acme")
    client = TestClient(_app_with_middleware())
    r = client.get("/protected", headers={"Authorization": "Basic c2VjcmV0"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# tenant_id column scaffold
# ---------------------------------------------------------------------------

def test_trade_records_has_tenant_id_column(tmp_path):
    from tradememory.db import Database

    Database(str(tmp_path / "tm.db"))
    conn = sqlite3.connect(str(tmp_path / "tm.db"))
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(trade_records)"
    ).fetchall()}
    assert "tenant_id" in cols
    conn.close()


def test_tenant_id_column_idempotent_on_existing_db(tmp_path):
    """A pre-v0.5.2 DB without tenant_id should gain the column on init,
    and a second init should not re-add."""
    from tradememory.db import Database

    # Simulate legacy DB without tenant_id by creating bare table first.
    legacy = sqlite3.connect(str(tmp_path / "legacy.db"))
    legacy.execute("""
        CREATE TABLE trade_records (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            lot_size REAL NOT NULL,
            strategy TEXT NOT NULL,
            confidence REAL NOT NULL,
            reasoning TEXT NOT NULL,
            market_context TEXT NOT NULL,
            trade_references TEXT NOT NULL,
            exit_timestamp TEXT,
            exit_price REAL,
            pnl REAL,
            pnl_r REAL,
            hold_duration INTEGER,
            exit_reasoning TEXT,
            slippage REAL,
            execution_quality REAL,
            lessons TEXT,
            tags TEXT,
            grade TEXT
        )
    """)
    legacy.commit()
    legacy.close()

    # First init adds the column.
    Database(str(tmp_path / "legacy.db"))
    # Second init is a no-op.
    Database(str(tmp_path / "legacy.db"))

    conn = sqlite3.connect(str(tmp_path / "legacy.db"))
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(trade_records)"
    ).fetchall()}
    assert "tenant_id" in cols
    # Ensure no duplicate column shenanigans.
    assert sum(1 for r in conn.execute(
        "PRAGMA table_info(trade_records)"
    ).fetchall() if r[1] == "tenant_id") == 1
    conn.close()
