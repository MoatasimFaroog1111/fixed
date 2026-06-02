"""
Advanced Execution Engine v9 — safe execution sophistication.

Features:
- Regime detection
- Dynamic confidence thresholds
- Dynamic position sizing
- Multi-timeframe proxy confirmation
- Safe SELL handling: no naked short by default
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Signal = Literal["BUY", "SELL", "HOLD"]
Regime = Literal["TRENDING", "SIDEWAYS", "VOLATILE", "QUIET"]


@dataclass
class ExecutionConfig:
    low_atr_pct: float = 0.004
    high_atr_pct: float = 0.015
    extreme_atr_pct: float = 0.030

    min_position_risk_pct: float = 0.010
    base_position_risk_pct: float = 0.025
    max_position_risk_pct: float = 0.060

    allow_naked_short: bool = False
    short_position_risk_pct: float = 0.010


@dataclass
class ExecutionDecision:
    action: Signal
    threshold: float
    position_risk_pct: float
    regime: Regime
    session: str
    mtf_bias: Signal
    allow_new_position: bool
    reason: str


class AdvancedExecutionEngine:
    def __init__(self, config: ExecutionConfig | None = None):
        self.config = config or ExecutionConfig()

    def detect_session(self, now_utc: datetime | None = None) -> str:
        now_utc = now_utc or datetime.now(timezone.utc)
        hour = now_utc.hour

        if 7 <= hour < 12:
            return "LONDON"
        if 12 <= hour < 17:
            return "LONDON_NY_OVERLAP"
        if 17 <= hour < 22:
            return "NEW_YORK"
        return "ASIA_QUIET"

    def detect_regime(self, atr_pct: float, ema_delta_pct: float, momentum_pct: float) -> Regime:
        trend_strength = abs(ema_delta_pct) + abs(momentum_pct)

        if atr_pct >= self.config.extreme_atr_pct:
            return "VOLATILE"
        if atr_pct <= self.config.low_atr_pct and trend_strength < 0.0015:
            return "QUIET"
        if trend_strength >= 0.003 or abs(ema_delta_pct) >= 0.002:
            return "TRENDING"
        return "SIDEWAYS"

    def dynamic_threshold(self, base_threshold: float, atr_pct: float, regime: Regime, session: str) -> float:
        threshold = base_threshold

        if regime == "TRENDING":
            threshold -= 0.05
        elif regime == "SIDEWAYS":
            threshold += 0.02
        elif regime == "QUIET":
            threshold += 0.02
        elif regime == "VOLATILE":
            threshold += 0.06

        if self.config.low_atr_pct <= atr_pct < self.config.high_atr_pct:
            threshold -= 0.02
        elif atr_pct >= self.config.high_atr_pct:
            threshold += 0.03

        if session == "LONDON_NY_OVERLAP":
            threshold -= 0.04
        elif session == "LONDON":
            threshold -= 0.03
        elif session == "ASIA_QUIET":
            threshold += 0.02

        return max(0.25, min(0.75, threshold))

    def multi_timeframe_bias(self, prices: list[float]) -> Signal:
        if len(prices) < 40:
            return "HOLD"

        s = (prices[-1] - prices[-10]) / prices[-10] if prices[-10] else 0.0
        m = (prices[-1] - prices[-25]) / prices[-25] if prices[-25] else 0.0
        l = (prices[-1] - prices[-40]) / prices[-40] if prices[-40] else 0.0

        if s > 0 and m > 0 and l > 0:
            return "BUY"
        if s < 0 and m < 0 and l < 0:
            return "SELL"
        return "HOLD"

    def dynamic_position_risk(
        self,
        confidence: float,
        threshold: float,
        atr_pct: float,
        regime: Regime,
        side: Signal,
    ) -> float:
        if side == "HOLD" or confidence < threshold:
            return 0.0

        edge = max(0.0, confidence - threshold)
        risk = self.config.base_position_risk_pct + (edge * 0.08)

        if regime == "TRENDING":
            risk *= 1.25
        elif regime == "SIDEWAYS":
            risk *= 0.90
        elif regime == "QUIET":
            risk *= 0.55
        elif regime == "VOLATILE":
            risk *= 0.65

        if atr_pct >= self.config.high_atr_pct:
            risk *= 0.70
        elif atr_pct <= self.config.low_atr_pct:
            risk *= 0.80

        if side == "SELL":
            risk = min(risk, self.config.short_position_risk_pct)

        return max(self.config.min_position_risk_pct, min(self.config.max_position_risk_pct, risk))

    def decide(
        self,
        buy_conf: float,
        sell_conf: float,
        base_threshold: float,
        atr_pct: float,
        ema_delta_pct: float,
        momentum_pct: float,
        prices: list[float],
        open_long_positions: int = 0,
    ) -> ExecutionDecision:
        session = self.detect_session()
        regime = self.detect_regime(atr_pct, ema_delta_pct, momentum_pct)
        mtf_bias = self.multi_timeframe_bias(prices)

        if mtf_bias == "BUY":
            buy_conf += 0.05
        elif mtf_bias == "SELL":
            sell_conf += 0.05

        threshold = self.dynamic_threshold(base_threshold, atr_pct, regime, session)

        action: Signal = "HOLD"
        confidence = 0.0

        if buy_conf >= threshold and buy_conf >= sell_conf:
            action = "BUY"
            confidence = buy_conf
        elif sell_conf >= threshold and sell_conf > buy_conf:
            action = "SELL"
            confidence = sell_conf

        if action == "SELL" and open_long_positions <= 0 and not self.config.allow_naked_short:
            return ExecutionDecision(
                action="SELL",
                threshold=threshold,
                position_risk_pct=0.0,
                regime=regime,
                session=session,
                mtf_bias=mtf_bias,
                allow_new_position=False,
                reason=(
                    f"SELL signal only; naked short disabled | "
                    f"Session={session} Regime={regime} MTF={mtf_bias} "
                    f"Conf={confidence:.0%} Need={threshold:.0%}"
                ),
            )

        risk = self.dynamic_position_risk(confidence, threshold, atr_pct, regime, action)

        return ExecutionDecision(
            action=action,
            threshold=threshold,
            position_risk_pct=risk,
            regime=regime,
            session=session,
            mtf_bias=mtf_bias,
            allow_new_position=(action != "HOLD"),
            reason=(
                f"Session={session} Regime={regime} MTF={mtf_bias} "
                f"Conf={confidence:.0%} Need={threshold:.0%} Risk={risk:.2%}"
            ),
        )
