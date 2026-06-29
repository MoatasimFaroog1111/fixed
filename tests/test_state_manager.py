"""Unit tests for state_manager.py — Persistent state management."""
import json
import os
import tempfile

import pytest

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state_manager import StateManager
from risk_manager import RiskManager, TradeRecord


class TestStateManagerInit:
    def test_new_state_file(self, tmp_path):
        path = str(tmp_path / "state.json")
        sm = StateManager(path=path)
        assert sm.data["version"] == 2
        assert sm.data["trades"] == {}
        assert sm.data["total_pnl"] == 0.0

    def test_load_existing_state(self, tmp_path):
        path = str(tmp_path / "state.json")
        data = {
            "version": 2,
            "trades": {"ORD1": {"order_id": "ORD1", "entry_price": 1950}},
            "daily": {},
            "total_pnl": 15.5,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        sm = StateManager(path=path)
        assert sm.data["total_pnl"] == 15.5
        assert "ORD1" in sm.data["trades"]

    def test_corrupted_state_file(self, tmp_path):
        path = str(tmp_path / "state.json")
        with open(path, "w") as f:
            f.write("not json at all {{{")
        sm = StateManager(path=path)
        # Should not crash, uses defaults
        assert sm.data["version"] == 2


class TestStateManagerRecordOpen:
    def _make_trade(self):
        return TradeRecord(
            order_id="ORD1",
            action="B",
            security_id="AUXLN",
            currency="USD",
            quantity=0.05,
            entry_price=1950.0,
            take_profit=1965.6,
            stop_loss=1900.0,
            timestamp="2024-01-01T12:00:00",
        )

    def test_record_open_persists(self, tmp_path):
        path = str(tmp_path / "state.json")
        sm = StateManager(path=path)
        trade = self._make_trade()
        sm.record_open(trade)
        assert "ORD1" in sm.data["trades"]
        # Verify file was written
        with open(path) as f:
            saved = json.load(f)
        assert "ORD1" in saved["trades"]
        assert saved["trades"]["ORD1"]["entry_price"] == 1950.0

    def test_record_multiple_trades(self, tmp_path):
        path = str(tmp_path / "state.json")
        sm = StateManager(path=path)
        t1 = self._make_trade()
        t2 = TradeRecord(
            order_id="ORD2", action="S", security_id="AGXLN",
            currency="USD", quantity=1.0, entry_price=25.0,
            take_profit=24.0, timestamp="2024-01-01T13:00:00",
        )
        sm.record_open(t1)
        sm.record_open(t2)
        assert len(sm.data["trades"]) == 2


class TestStateManagerRecordClose:
    def test_record_close(self, tmp_path):
        path = str(tmp_path / "state.json")
        sm = StateManager(path=path)
        trade = TradeRecord(
            order_id="ORD1", action="B", security_id="AUXLN",
            currency="USD", quantity=0.05, entry_price=1950.0,
            take_profit=1965.0, timestamp="2024-01-01T12:00:00",
        )
        sm.record_open(trade)
        sm.record_close("ORD1", pnl=10.0)
        assert "ORD1" not in sm.data["trades"]
        assert sm.data["total_pnl"] == 10.0

    def test_record_close_accumulates_pnl(self, tmp_path):
        path = str(tmp_path / "state.json")
        sm = StateManager(path=path)
        for i, pnl in enumerate([5.0, -2.0, 3.0]):
            trade = TradeRecord(
                order_id=f"ORD{i}", action="B", security_id="AUXLN",
                currency="USD", quantity=0.05, entry_price=1950.0,
                take_profit=1965.0, timestamp=f"2024-01-01T{12+i}:00:00",
            )
            sm.record_open(trade)
            sm.record_close(f"ORD{i}", pnl=pnl)
        assert sm.data["total_pnl"] == pytest.approx(6.0)

    def test_close_nonexistent_order(self, tmp_path):
        path = str(tmp_path / "state.json")
        sm = StateManager(path=path)
        sm.record_close("FAKE", pnl=5.0)
        assert sm.data["total_pnl"] == 5.0


class TestStateManagerRestoreToRisk:
    def test_restore_trades(self, tmp_path):
        path = str(tmp_path / "state.json")
        data = {
            "version": 2,
            "trades": {
                "ORD1": {
                    "order_id": "ORD1", "action": "B",
                    "security_id": "AUXLN", "currency": "USD",
                    "quantity": 0.05, "entry_price": 1950.0,
                    "take_profit": 1965.0, "stop_loss": 1900.0,
                    "timestamp": "2024-01-01T12:00:00",
                    "dca_count": 0, "peak_price": 1955.0,
                },
            },
            "daily": {},
            "total_pnl": 0.0,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        sm = StateManager(path=path)
        rm = RiskManager()
        restored = sm.restore_to_risk(rm)
        assert restored == 1
        assert "ORD1" in rm.open_trades
        assert rm.open_trades["ORD1"].entry_price == 1950.0
        assert rm.open_trades["ORD1"].peak_price == 1955.0

    def test_restore_updates_existing(self, tmp_path):
        path = str(tmp_path / "state.json")
        data = {
            "version": 2,
            "trades": {
                "ORD1": {
                    "order_id": "ORD1", "action": "B",
                    "security_id": "AUXLN", "currency": "USD",
                    "quantity": 0.05, "entry_price": 1950.0,
                    "take_profit": 1965.0, "stop_loss": 1900.0,
                    "timestamp": "2024-01-01T12:00:00",
                    "dca_count": 2, "peak_price": 1970.0,
                },
            },
            "daily": {},
            "total_pnl": 0.0,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        sm = StateManager(path=path)
        rm = RiskManager()
        # Pre-existing trade in risk manager with stale data
        rm.open_trades["ORD1"] = TradeRecord(
            order_id="ORD1", action="B", security_id="AUXLN",
            currency="USD", quantity=0.05, entry_price=0.0,
            take_profit=0.0, timestamp="old",
        )
        restored = sm.restore_to_risk(rm)
        assert restored == 1
        assert rm.open_trades["ORD1"].entry_price == 1950.0
        assert rm.open_trades["ORD1"].dca_count == 2


class TestStateManagerGetSummary:
    def test_empty_summary(self, tmp_path):
        path = str(tmp_path / "state.json")
        sm = StateManager(path=path)
        summary = sm.get_summary()
        assert summary["total_pnl"] == 0.0
        assert summary["trades_today"] == 0
        assert summary["open_positions"] == 0
        assert summary["trading_days"] == 0

    def test_summary_after_trades(self, tmp_path):
        path = str(tmp_path / "state.json")
        sm = StateManager(path=path)
        trade = TradeRecord(
            order_id="ORD1", action="B", security_id="AUXLN",
            currency="USD", quantity=0.05, entry_price=1950.0,
            take_profit=1965.0, timestamp="2024-01-01T12:00:00",
        )
        sm.record_open(trade)
        sm.record_close("ORD1", pnl=7.5)
        summary = sm.get_summary()
        assert summary["total_pnl"] == 7.5
        assert summary["trades_today"] == 1
        assert summary["open_positions"] == 0
        assert summary["trading_days"] == 1
