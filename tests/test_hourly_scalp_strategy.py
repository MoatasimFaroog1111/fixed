"""Unit tests for hourly_scalp_strategy.py — Scalping strategy."""
import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hourly_scalp_strategy import (
    HourlyScalpConfig,
    HourlyScalpStrategy,
    ScalpSignal,
    calculate_rsi,
)


class TestCalculateRSI:
    def test_insufficient_data(self):
        prices = [100.0] * 5
        assert calculate_rsi(prices) == 50.0

    def test_all_gains(self):
        prices = [100.0 + i for i in range(20)]
        rsi = calculate_rsi(prices)
        assert rsi == 100.0

    def test_all_losses(self):
        prices = [200.0 - i for i in range(20)]
        rsi = calculate_rsi(prices)
        assert rsi == 0.0

    def test_mixed_prices_in_range(self):
        prices = [100, 101, 100, 102, 101, 103, 102, 104, 103, 105,
                  104, 103, 102, 101, 100, 99]
        rsi = calculate_rsi(prices)
        assert 0 <= rsi <= 100

    def test_zero_prices_filtered(self):
        prices = [0, 100, 101, 102, 103, 104, 105, 106, 107, 108,
                  109, 110, 111, 112, 113, 114, 115]
        rsi = calculate_rsi(prices)
        assert 0 <= rsi <= 100

    def test_custom_period(self):
        prices = [100 + i * 0.5 for i in range(30)]
        rsi = calculate_rsi(prices, period=7)
        assert rsi == 100.0


class TestHourlyScalpStrategyEvaluate:
    def test_invalid_price_returns_hold(self):
        strategy = HourlyScalpStrategy()
        signal = strategy.evaluate(
            current_price=0,
            bid=100,
            ask=101,
            hourly_high=105,
            hourly_low=95,
            rsi=50,
            trades_today=0,
        )
        assert signal.action == "HOLD"
        assert "Invalid" in signal.reason

    def test_invalid_spread_returns_hold(self):
        strategy = HourlyScalpStrategy()
        signal = strategy.evaluate(
            current_price=100,
            bid=101,
            ask=100,  # ask < bid
            hourly_high=105,
            hourly_low=95,
            rsi=50,
            trades_today=0,
        )
        assert signal.action == "HOLD"

    def test_daily_trade_limit_reached(self):
        strategy = HourlyScalpStrategy(HourlyScalpConfig(max_trades_per_day=3))
        signal = strategy.evaluate(
            current_price=100,
            bid=100,
            ask=100.1,
            hourly_high=105,
            hourly_low=95,
            rsi=30,
            trades_today=3,
        )
        assert signal.action == "HOLD"
        assert "daily trade limit" in signal.reason

    def test_spread_too_high(self):
        strategy = HourlyScalpStrategy(HourlyScalpConfig(
            take_profit_pct=0.012,
            max_spread_to_tp_ratio=0.40,
        ))
        # max spread = 0.012 * 0.40 = 0.0048; spread here: (102 - 100)/100 = 0.02
        signal = strategy.evaluate(
            current_price=100,
            bid=100,
            ask=102,
            hourly_high=105,
            hourly_low=95,
            rsi=30,
            trades_today=0,
        )
        assert signal.action == "HOLD"
        assert "Spread too high" in signal.reason

    def test_low_volatility(self):
        strategy = HourlyScalpStrategy(HourlyScalpConfig(min_hourly_volatility_pct=0.01))
        signal = strategy.evaluate(
            current_price=100,
            bid=99.99,
            ask=100.01,
            hourly_high=100.2,  # volatility = 0.4/100 = 0.004 < 0.01
            hourly_low=99.8,
            rsi=30,
            trades_today=0,
        )
        assert signal.action == "HOLD"
        assert "volatility too low" in signal.reason.lower()

    def test_buy_signal_near_support(self):
        strategy = HourlyScalpStrategy(HourlyScalpConfig(
            min_hourly_volatility_pct=0.005,
            entry_drop_pct=0.005,
            rsi_buy_level=35.0,
            take_profit_pct=0.012,
            max_spread_to_tp_ratio=0.40,
        ))
        # Price near support (hourly_low), RSI oversold
        signal = strategy.evaluate(
            current_price=95.2,  # near support of 95
            bid=95.1,
            ask=95.3,
            hourly_high=105,    # volatility = 10/95.2 = ~0.105 >> 0.005
            hourly_low=95,
            rsi=30,             # < 35
            trades_today=0,
        )
        assert signal.action == "BUY"
        assert signal.entry_price > 0
        assert signal.take_profit > signal.entry_price
        assert signal.stop_loss < signal.entry_price

    def test_sell_signal_near_resistance(self):
        strategy = HourlyScalpStrategy(HourlyScalpConfig(
            min_hourly_volatility_pct=0.005,
            entry_drop_pct=0.005,
            rsi_sell_level=70.0,
            take_profit_pct=0.012,
            max_spread_to_tp_ratio=0.40,
        ))
        signal = strategy.evaluate(
            current_price=104.8,  # near resistance of 105
            bid=104.7,
            ask=104.9,
            hourly_high=105,
            hourly_low=95,
            rsi=75,               # > 70
            trades_today=0,
        )
        assert signal.action == "SELL"

    def test_price_in_middle_returns_hold(self):
        strategy = HourlyScalpStrategy(HourlyScalpConfig(
            min_hourly_volatility_pct=0.005,
            take_profit_pct=0.012,
            max_spread_to_tp_ratio=0.40,
        ))
        signal = strategy.evaluate(
            current_price=100.0,  # midpoint of 95-105 range
            bid=99.9,
            ask=100.1,
            hourly_high=105,
            hourly_low=95,
            rsi=50,
            trades_today=0,
        )
        assert signal.action == "HOLD"
        assert "middle" in signal.reason.lower()

    def test_buy_rejected_in_downtrend(self):
        strategy = HourlyScalpStrategy(HourlyScalpConfig(
            min_hourly_volatility_pct=0.005,
            entry_drop_pct=0.005,
            rsi_buy_level=35.0,
            take_profit_pct=0.012,
            max_spread_to_tp_ratio=0.40,
        ))
        signal = strategy.evaluate(
            current_price=95.2,
            bid=95.1,
            ask=95.3,
            hourly_high=105,
            hourly_low=95,
            rsi=30,
            trades_today=0,
            trend="DOWN",
        )
        # Should not BUY in a downtrend
        assert signal.action == "HOLD"


class TestHourlyScalpEvaluateFromPrices:
    def test_insufficient_prices(self):
        strategy = HourlyScalpStrategy()
        signal = strategy.evaluate_from_prices(
            prices=[100.0] * 10,
            bid=99,
            ask=101,
            trades_today=0,
        )
        assert signal.action == "HOLD"
        assert "warm-up" in signal.reason

    def test_sufficient_prices(self):
        strategy = HourlyScalpStrategy(HourlyScalpConfig(
            min_hourly_volatility_pct=0.005,
        ))
        # Create prices with enough volatility
        prices = [100 + i * 0.1 for i in range(20)]
        signal = strategy.evaluate_from_prices(
            prices=prices,
            bid=101.8,
            ask=102.0,
            trades_today=0,
        )
        assert signal.action in ("BUY", "SELL", "HOLD")


class TestRangeVolatility:
    def test_normal(self):
        vol = HourlyScalpStrategy._range_volatility(105, 95, 100)
        assert vol == pytest.approx(0.10)

    def test_zero_price(self):
        vol = HourlyScalpStrategy._range_volatility(105, 95, 0)
        assert vol == 0.0

    def test_high_equal_low(self):
        vol = HourlyScalpStrategy._range_volatility(100, 100, 100)
        assert vol == 0.0

    def test_high_less_than_low(self):
        vol = HourlyScalpStrategy._range_volatility(95, 105, 100)
        assert vol == 0.0
