"""Unit tests for advanced_execution.py — Execution engine."""
import pytest
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advanced_execution import (
    ExecutionConfig,
    ExecutionDecision,
    AdvancedExecutionEngine,
)


class TestDetectSession:
    def test_london_session(self):
        engine = AdvancedExecutionEngine()
        dt = datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc)
        assert engine.detect_session(dt) == "LONDON"

    def test_london_ny_overlap(self):
        engine = AdvancedExecutionEngine()
        dt = datetime(2024, 1, 15, 14, 0, tzinfo=timezone.utc)
        assert engine.detect_session(dt) == "LONDON_NY_OVERLAP"

    def test_new_york_session(self):
        engine = AdvancedExecutionEngine()
        dt = datetime(2024, 1, 15, 19, 0, tzinfo=timezone.utc)
        assert engine.detect_session(dt) == "NEW_YORK"

    def test_asia_quiet(self):
        engine = AdvancedExecutionEngine()
        dt = datetime(2024, 1, 15, 3, 0, tzinfo=timezone.utc)
        assert engine.detect_session(dt) == "ASIA_QUIET"

    def test_boundary_london_start(self):
        engine = AdvancedExecutionEngine()
        dt = datetime(2024, 1, 15, 7, 0, tzinfo=timezone.utc)
        assert engine.detect_session(dt) == "LONDON"

    def test_boundary_ny_end(self):
        engine = AdvancedExecutionEngine()
        dt = datetime(2024, 1, 15, 21, 59, tzinfo=timezone.utc)
        assert engine.detect_session(dt) == "NEW_YORK"

    def test_boundary_asia_quiet_at_22(self):
        engine = AdvancedExecutionEngine()
        dt = datetime(2024, 1, 15, 22, 0, tzinfo=timezone.utc)
        assert engine.detect_session(dt) == "ASIA_QUIET"


class TestDetectRegime:
    def test_volatile_regime(self):
        engine = AdvancedExecutionEngine()
        regime = engine.detect_regime(atr_pct=0.035, ema_delta_pct=0.001, momentum_pct=0.001)
        assert regime == "VOLATILE"

    def test_quiet_regime(self):
        engine = AdvancedExecutionEngine()
        regime = engine.detect_regime(atr_pct=0.002, ema_delta_pct=0.0005, momentum_pct=0.0005)
        assert regime == "QUIET"

    def test_trending_regime(self):
        engine = AdvancedExecutionEngine()
        regime = engine.detect_regime(atr_pct=0.008, ema_delta_pct=0.003, momentum_pct=0.001)
        assert regime == "TRENDING"

    def test_sideways_regime(self):
        engine = AdvancedExecutionEngine()
        regime = engine.detect_regime(atr_pct=0.008, ema_delta_pct=0.0005, momentum_pct=0.0005)
        assert regime == "SIDEWAYS"


class TestDynamicThreshold:
    def test_trending_lowers_threshold(self):
        engine = AdvancedExecutionEngine()
        base = 0.50
        t = engine.dynamic_threshold(base, atr_pct=0.008, regime="TRENDING", session="LONDON")
        assert t < base

    def test_volatile_raises_threshold(self):
        engine = AdvancedExecutionEngine()
        base = 0.50
        t = engine.dynamic_threshold(base, atr_pct=0.02, regime="VOLATILE", session="LONDON")
        assert t > base

    def test_london_ny_overlap_lowers_threshold(self):
        engine = AdvancedExecutionEngine()
        base = 0.50
        t_overlap = engine.dynamic_threshold(base, atr_pct=0.008, regime="SIDEWAYS", session="LONDON_NY_OVERLAP")
        t_asia = engine.dynamic_threshold(base, atr_pct=0.008, regime="SIDEWAYS", session="ASIA_QUIET")
        assert t_overlap < t_asia

    def test_threshold_clamped_min(self):
        engine = AdvancedExecutionEngine()
        t = engine.dynamic_threshold(0.10, atr_pct=0.005, regime="TRENDING", session="LONDON_NY_OVERLAP")
        assert t >= 0.25

    def test_threshold_clamped_max(self):
        engine = AdvancedExecutionEngine()
        t = engine.dynamic_threshold(0.90, atr_pct=0.02, regime="VOLATILE", session="ASIA_QUIET")
        assert t <= 0.75


class TestMultiTimeframeBias:
    def test_insufficient_data(self):
        engine = AdvancedExecutionEngine()
        prices = list(range(30))
        assert engine.multi_timeframe_bias(prices) == "HOLD"

    def test_all_positive(self):
        engine = AdvancedExecutionEngine()
        # Prices consistently rising
        prices = [100 + i * 0.5 for i in range(50)]
        assert engine.multi_timeframe_bias(prices) == "BUY"

    def test_all_negative(self):
        engine = AdvancedExecutionEngine()
        # Prices consistently falling
        prices = [200 - i * 0.5 for i in range(50)]
        assert engine.multi_timeframe_bias(prices) == "SELL"

    def test_mixed_signals(self):
        engine = AdvancedExecutionEngine()
        # Short up, medium down
        prices = [100] * 50
        prices[-1] = 101  # short up
        prices[-25] = 105  # medium was higher -> down
        prices[-40] = 95   # long was lower -> up
        bias = engine.multi_timeframe_bias(prices)
        assert bias == "HOLD"


class TestDynamicPositionRisk:
    def test_hold_returns_zero(self):
        engine = AdvancedExecutionEngine()
        risk = engine.dynamic_position_risk(
            confidence=0.6, threshold=0.5, atr_pct=0.008, regime="TRENDING", side="HOLD"
        )
        assert risk == 0.0

    def test_below_threshold_returns_zero(self):
        engine = AdvancedExecutionEngine()
        risk = engine.dynamic_position_risk(
            confidence=0.4, threshold=0.5, atr_pct=0.008, regime="TRENDING", side="BUY"
        )
        assert risk == 0.0

    def test_buy_trending_higher_risk(self):
        engine = AdvancedExecutionEngine()
        risk_trending = engine.dynamic_position_risk(
            confidence=0.7, threshold=0.5, atr_pct=0.008, regime="TRENDING", side="BUY"
        )
        risk_sideways = engine.dynamic_position_risk(
            confidence=0.7, threshold=0.5, atr_pct=0.008, regime="SIDEWAYS", side="BUY"
        )
        assert risk_trending > risk_sideways

    def test_sell_capped_at_short_risk(self):
        engine = AdvancedExecutionEngine()
        risk = engine.dynamic_position_risk(
            confidence=0.9, threshold=0.5, atr_pct=0.008, regime="TRENDING", side="SELL"
        )
        assert risk <= engine.config.short_position_risk_pct

    def test_risk_within_bounds(self):
        engine = AdvancedExecutionEngine()
        risk = engine.dynamic_position_risk(
            confidence=0.8, threshold=0.4, atr_pct=0.01, regime="TRENDING", side="BUY"
        )
        assert engine.config.min_position_risk_pct <= risk <= engine.config.max_position_risk_pct


class TestDecide:
    def test_buy_signal(self):
        engine = AdvancedExecutionEngine()
        prices = [100 + i * 0.5 for i in range(50)]
        decision = engine.decide(
            buy_conf=0.7,
            sell_conf=0.3,
            base_threshold=0.5,
            atr_pct=0.008,
            ema_delta_pct=0.002,
            momentum_pct=0.001,
            prices=prices,
            open_long_positions=0,
        )
        assert decision.action == "BUY"
        assert decision.allow_new_position is True
        assert decision.position_risk_pct > 0

    def test_hold_signal(self):
        engine = AdvancedExecutionEngine()
        prices = [100] * 50
        decision = engine.decide(
            buy_conf=0.3,
            sell_conf=0.2,
            base_threshold=0.5,
            atr_pct=0.003,
            ema_delta_pct=0.0,
            momentum_pct=0.0,
            prices=prices,
            open_long_positions=0,
        )
        assert decision.action == "HOLD"
        assert decision.allow_new_position is False

    def test_sell_no_naked_short(self):
        engine = AdvancedExecutionEngine(ExecutionConfig(allow_naked_short=False))
        prices = [200 - i * 0.5 for i in range(50)]
        decision = engine.decide(
            buy_conf=0.2,
            sell_conf=0.8,
            base_threshold=0.5,
            atr_pct=0.008,
            ema_delta_pct=-0.002,
            momentum_pct=-0.001,
            prices=prices,
            open_long_positions=0,
        )
        assert decision.action == "SELL"
        assert decision.allow_new_position is False
        assert decision.position_risk_pct == 0.0

    def test_sell_with_open_positions(self):
        engine = AdvancedExecutionEngine(ExecutionConfig(allow_naked_short=False))
        prices = [200 - i * 0.5 for i in range(50)]
        decision = engine.decide(
            buy_conf=0.2,
            sell_conf=0.8,
            base_threshold=0.5,
            atr_pct=0.008,
            ema_delta_pct=-0.002,
            momentum_pct=-0.001,
            prices=prices,
            open_long_positions=1,
        )
        assert decision.action == "SELL"
        assert decision.allow_new_position is True
        assert decision.position_risk_pct > 0

    def test_naked_short_allowed(self):
        engine = AdvancedExecutionEngine(ExecutionConfig(allow_naked_short=True))
        prices = [200 - i * 0.5 for i in range(50)]
        decision = engine.decide(
            buy_conf=0.2,
            sell_conf=0.8,
            base_threshold=0.5,
            atr_pct=0.008,
            ema_delta_pct=-0.002,
            momentum_pct=-0.001,
            prices=prices,
            open_long_positions=0,
        )
        assert decision.action == "SELL"
        assert decision.allow_new_position is True
