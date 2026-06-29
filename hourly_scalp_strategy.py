"""
Hourly scalping filter for BullionVault bots.

This module does not place orders by itself. It gives a strict BUY/SELL/HOLD
filter using rolling intraday volatility, support/resistance, RSI, trend,
spread cost, and daily over-trading limits.
"""
from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from shared_utils import calculate_rsi as _shared_calculate_rsi

Action = Literal["BUY", "SELL", "HOLD"]


@dataclass
class HourlyScalpConfig:
    # Minimum rolling volatility required before scalping is allowed.
    min_hourly_volatility_pct: float = 0.008  # 0.8%

    # How close price must be to support/resistance.
    entry_drop_pct: float = 0.005  # 0.5%

    # Used to reject trades when spread consumes too much of the target.
    take_profit_pct: float = 0.012
    stop_loss_pct: float = 0.008
    trailing_stop_pct: float = 0.005
    max_spread_to_tp_ratio: float = 0.40

    # Anti-overtrading.
    max_trades_per_day: int = 3

    # RSI filters.
    rsi_buy_level: float = 35.0
    rsi_sell_level: float = 70.0


@dataclass
class ScalpSignal:
    action: Action
    reason: str
    entry_price: float = 0.0
    take_profit: float = 0.0
    stop_loss: float = 0.0
    trailing_stop_pct: float = 0.0
    volatility_pct: float = 0.0
    rsi: float = 50.0


class HourlyScalpStrategy:
    def __init__(self, config: Optional[HourlyScalpConfig] = None):
        self.config = config or HourlyScalpConfig()

    def evaluate_from_prices(
        self,
        prices: Sequence[float],
        bid: float,
        ask: float,
        trades_today: int,
        trend: str = "NEUTRAL",
    ) -> ScalpSignal:
        clean_prices = [float(p) for p in prices if p and float(p) > 0]
        if len(clean_prices) < 15:
            return ScalpSignal("HOLD", f"Scalp warm-up: {len(clean_prices)}/15 prices")
        current_price = clean_prices[-1]
        hourly_high = max(clean_prices)
        hourly_low = min(clean_prices)
        rsi = calculate_rsi(clean_prices)
        return self.evaluate(
            current_price=current_price,
            bid=bid,
            ask=ask,
            hourly_high=hourly_high,
            hourly_low=hourly_low,
            rsi=rsi,
            trades_today=trades_today,
            trend=trend,
        )

    def evaluate(
        self,
        current_price: float,
        bid: float,
        ask: float,
        hourly_high: float,
        hourly_low: float,
        rsi: float,
        trades_today: int,
        trend: str = "NEUTRAL",
    ) -> ScalpSignal:
        if current_price <= 0 or bid <= 0 or ask <= 0 or ask <= bid:
            return ScalpSignal("HOLD", "Invalid price/spread data")

        spread_pct = (ask - bid) / bid
        if trades_today >= self.config.max_trades_per_day:
            return ScalpSignal("HOLD", "Scalp daily trade limit reached", rsi=rsi)

        max_allowed_spread = self.config.take_profit_pct * self.config.max_spread_to_tp_ratio
        if spread_pct > max_allowed_spread:
            return ScalpSignal(
                "HOLD",
                f"Spread too high for scalp: {spread_pct:.3%} > {max_allowed_spread:.3%}",
                rsi=rsi,
            )

        volatility = self._range_volatility(hourly_high, hourly_low, current_price)
        if volatility < self.config.min_hourly_volatility_pct:
            return ScalpSignal(
                "HOLD",
                f"Rolling volatility too low: {volatility:.3%}",
                volatility_pct=volatility,
                rsi=rsi,
            )

        support = hourly_low
        resistance = hourly_high
        midpoint = (support + resistance) / 2
        near_support_price = support * (1 + self.config.entry_drop_pct)
        near_resistance_price = resistance * (1 - self.config.entry_drop_pct)

        if abs(current_price - midpoint) / current_price < 0.002:
            return ScalpSignal(
                "HOLD",
                "Price is in the middle of the rolling range",
                volatility_pct=volatility,
                rsi=rsi,
            )

        if current_price <= near_support_price and rsi <= self.config.rsi_buy_level and trend != "DOWN":
            entry = ask
            return ScalpSignal(
                action="BUY",
                reason="Scalp BUY: near support + RSI oversold + volatility enough + spread acceptable",
                entry_price=entry,
                take_profit=round(entry * (1 + self.config.take_profit_pct), 2),
                stop_loss=round(entry * (1 - self.config.stop_loss_pct), 2),
                trailing_stop_pct=self.config.trailing_stop_pct,
                volatility_pct=volatility,
                rsi=rsi,
            )

        if current_price >= near_resistance_price and rsi >= self.config.rsi_sell_level and trend != "UP":
            return ScalpSignal(
                action="SELL",
                reason="Scalp SELL: near resistance + RSI overbought",
                volatility_pct=volatility,
                rsi=rsi,
            )

        return ScalpSignal(
            "HOLD",
            "No high-quality hourly scalp setup",
            volatility_pct=volatility,
            rsi=rsi,
        )

    @staticmethod
    def _range_volatility(high: float, low: float, price: float) -> float:
        if price <= 0 or high <= low:
            return 0.0
        return (high - low) / price


def calculate_rsi(prices: Sequence[float], period: int = 14) -> float:
    """Delegates to shared_utils.calculate_rsi."""
    return _shared_calculate_rsi(prices, period)
