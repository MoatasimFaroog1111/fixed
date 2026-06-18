"""Unit tests for risk_manager.py — Risk management logic."""
import pytest
from unittest.mock import patch
from datetime import date

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_manager import RiskConfig, TradeRecord, RiskManager


class TestRiskConfig:
    def test_default_values(self):
        config = RiskConfig()
        assert config.max_position_kg == 0.1
        assert config.max_daily_trades == 50
        assert config.take_profit_pct == 0.008
        assert config.stop_loss_pct == 0.050
        assert config.confidence_threshold == 0.45

    def test_custom_values(self):
        config = RiskConfig(max_position_kg=0.5, max_daily_trades=10)
        assert config.max_position_kg == 0.5
        assert config.max_daily_trades == 10

    def test_min_spread_pct_property(self):
        config = RiskConfig(max_acceptable_spread_pct=0.01)
        assert config.min_spread_pct == 0.01


class TestRiskManagerCanTrade:
    def test_can_trade_normal_conditions(self):
        rm = RiskManager()
        allowed, msg = rm.can_trade(balance_usd=1000.0, open_orders_count=0)
        assert allowed is True
        assert msg == "OK"

    def test_cannot_trade_daily_limit(self):
        rm = RiskManager(RiskConfig(max_daily_trades=2))
        today = rm._today()
        rm.daily_trades[today] = 2
        allowed, msg = rm.can_trade(balance_usd=1000.0, open_orders_count=0)
        assert allowed is False
        assert "Daily trade limit" in msg

    def test_cannot_trade_daily_loss_limit(self):
        rm = RiskManager(RiskConfig(max_daily_loss_usd=100.0))
        today = rm._today()
        rm.daily_pnl[today] = -100.0
        allowed, msg = rm.can_trade(balance_usd=1000.0, open_orders_count=0)
        assert allowed is False
        assert "Daily loss limit" in msg

    def test_cannot_trade_max_open_orders(self):
        rm = RiskManager(RiskConfig(max_open_orders=1))
        allowed, msg = rm.can_trade(balance_usd=1000.0, open_orders_count=1)
        assert allowed is False
        assert "Max open orders" in msg

    def test_cannot_trade_insufficient_balance(self):
        rm = RiskManager()
        allowed, msg = rm.can_trade(balance_usd=30.0, open_orders_count=0)
        assert allowed is False
        assert "Insufficient USD" in msg

    def test_boundary_balance_50(self):
        rm = RiskManager()
        allowed, _ = rm.can_trade(balance_usd=50.0, open_orders_count=0)
        assert allowed is True


class TestRiskManagerCalculateQuantity:
    def test_zero_balance(self):
        rm = RiskManager()
        assert rm.calculate_quantity(0.0, 1950.0) == 0.0

    def test_zero_price(self):
        rm = RiskManager()
        assert rm.calculate_quantity(1000.0, 0.0) == 0.0

    def test_negative_balance(self):
        rm = RiskManager()
        assert rm.calculate_quantity(-100.0, 1950.0) == 0.0

    def test_normal_calculation(self):
        rm = RiskManager(RiskConfig(max_position_kg=1.0))
        qty = rm.calculate_quantity(10000.0, 1950.0)
        # (10000 * 0.50) / 1950 = 2.564, capped at 1.0
        assert qty == 1.0

    def test_small_balance_minimum_quantity(self):
        rm = RiskManager()
        qty = rm.calculate_quantity(100.0, 50000.0)
        # (100 * 0.50) / 50000 = 0.001
        assert qty == 0.001

    def test_caps_at_max_position(self):
        rm = RiskManager(RiskConfig(max_position_kg=0.05))
        qty = rm.calculate_quantity(100000.0, 1950.0)
        assert qty == 0.05

    def test_quantity_rounded_to_3_decimals(self):
        rm = RiskManager(RiskConfig(max_position_kg=10.0))
        qty = rm.calculate_quantity(1000.0, 333.33)
        # (1000 * 0.5) / 333.33 = ~1.5000
        assert qty == round(qty, 3)


class TestRiskManagerTakeProfit:
    def test_buy_take_profit(self):
        rm = RiskManager(RiskConfig(take_profit_pct=0.008))
        tp = rm.calculate_take_profit("B", 1950.0)
        expected = round(1950.0 * 1.008, 2)
        assert tp == expected

    def test_sell_take_profit(self):
        rm = RiskManager(RiskConfig(take_profit_pct=0.008))
        tp = rm.calculate_take_profit("S", 1950.0)
        expected = round(1950.0 * 0.992, 2)
        assert tp == expected

    def test_custom_pct(self):
        rm = RiskManager(RiskConfig(take_profit_pct=0.02))
        tp = rm.calculate_take_profit("B", 100.0)
        assert tp == 102.0


class TestRiskManagerStopLoss:
    def test_stop_loss_disabled(self):
        rm = RiskManager(RiskConfig(stop_loss_pct=0.0))
        sl = rm.calculate_stop_loss("B", 1950.0)
        assert sl == 0.0

    def test_buy_static_stop_loss(self):
        rm = RiskManager(RiskConfig(stop_loss_pct=0.05))
        sl = rm.calculate_stop_loss("B", 1000.0, price_history=None)
        assert sl == round(1000.0 * 0.95, 2)

    def test_sell_stop_loss(self):
        rm = RiskManager(RiskConfig(stop_loss_pct=0.05))
        sl = rm.calculate_stop_loss("S", 1000.0)
        assert sl == round(1000.0 * 1.05, 2)

    def test_buy_with_short_history_uses_static(self):
        rm = RiskManager(RiskConfig(stop_loss_pct=0.05))
        short_history = [100.0] * 10  # less than 15
        sl = rm.calculate_stop_loss("B", 1000.0, price_history=short_history)
        assert sl == round(1000.0 * 0.95, 2)


class TestRiskManagerSpread:
    def test_acceptable_spread(self):
        rm = RiskManager(RiskConfig(max_acceptable_spread_pct=0.006))
        assert rm.is_spread_acceptable(1950.0, 1955.0) is True

    def test_unacceptable_spread(self):
        rm = RiskManager(RiskConfig(max_acceptable_spread_pct=0.001))
        assert rm.is_spread_acceptable(1950.0, 1955.0) is False

    def test_none_bid(self):
        rm = RiskManager()
        assert rm.is_spread_acceptable(None, 1955.0) is False

    def test_none_ask(self):
        rm = RiskManager()
        assert rm.is_spread_acceptable(1950.0, None) is False

    def test_zero_bid(self):
        rm = RiskManager()
        assert rm.is_spread_acceptable(0, 1955.0) is False

    def test_ask_less_than_bid(self):
        rm = RiskManager()
        assert rm.is_spread_acceptable(1955.0, 1950.0) is False

    def test_ask_equal_bid(self):
        rm = RiskManager()
        assert rm.is_spread_acceptable(1950.0, 1950.0) is False


class TestRiskManagerTradeLifecycle:
    def _make_trade(self, order_id="ORD1"):
        return TradeRecord(
            order_id=order_id,
            action="B",
            security_id="AUXLN",
            currency="USD",
            quantity=0.05,
            entry_price=1950.0,
            take_profit=1965.6,
            timestamp="2024-01-01T12:00:00",
        )

    def test_register_trade(self):
        rm = RiskManager()
        trade = self._make_trade()
        rm.register_trade(trade)
        today = rm._today()
        assert rm.daily_trades[today] == 1
        assert "ORD1" in rm.open_trades

    def test_update_pnl_buy(self):
        rm = RiskManager()
        trade = self._make_trade()
        rm.register_trade(trade)
        result = rm.update_pnl("ORD1", 1960.0)
        expected_pnl = (1960.0 - 1950.0) * 0.05
        assert result["pnl"] == pytest.approx(expected_pnl)

    def test_update_pnl_nonexistent_order(self):
        rm = RiskManager()
        result = rm.update_pnl("FAKE", 1960.0)
        assert result == {}

    def test_close_trade(self):
        rm = RiskManager()
        trade = self._make_trade()
        trade.pnl = 5.0
        rm.register_trade(trade)
        rm.close_trade("ORD1")
        assert "ORD1" not in rm.open_trades
        today = rm._today()
        assert rm.daily_pnl[today] == 5.0

    def test_close_nonexistent_trade(self):
        rm = RiskManager()
        rm.close_trade("FAKE")  # should not raise

    def test_get_stats(self):
        rm = RiskManager()
        trade = self._make_trade()
        rm.register_trade(trade)
        stats = rm.get_stats()
        assert stats["trades_today"] == 1
        assert stats["open_positions"] == 1

    def test_prune_old_days(self):
        rm = RiskManager()
        old_date = "2020-01-01"
        rm.daily_trades[old_date] = 5
        rm.daily_pnl[old_date] = -50.0
        trade = self._make_trade()
        rm.register_trade(trade)  # triggers prune
        assert old_date not in rm.daily_trades
        assert old_date not in rm.daily_pnl
