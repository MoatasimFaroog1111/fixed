"""
Risk Manager v6
التغييرات:
  - إزالة stop_loss كاملاً من RiskConfig وTradeRecord
  - calculate_take_profit() بدلاً من calculate_stops()
  - إصلاح is_spread_acceptable (إزالة *10)
  - position_risk_pct بديلاً عن stop_loss في حساب الكمية
"""
from atr_stoploss import dynamic_stop_loss
import logging
from dataclasses import dataclass, field
from typing import Dict
from datetime import date, timedelta

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    max_position_kg:      float = 0.1
    max_daily_trades:     int   = 50
    max_daily_loss_usd:   float = 99999.0
    take_profit_pct:      float = 0.008
    stop_loss_pct:        float = 0.050
    max_acceptable_spread_pct: float = 0.006
    max_open_orders:      int   = 1
    confidence_threshold: float = 0.45
    position_risk_pct:    float = 0.02    # نسبة رأس المال لكل صفقة

    @property
    def min_spread_pct(self) -> float:
        # توافق خلفي مع الاسم القديم؛ المعنى الصحيح هو أقصى سبريد مقبول.
        return self.max_acceptable_spread_pct


@dataclass
class TradeRecord:
    order_id:    str
    action:      str
    security_id: str
    currency:    str
    quantity:    float
    entry_price: float
    take_profit: float
    timestamp:   str
    stop_loss:   float = 0.0
    pnl:         float = 0.0
    closed:      bool  = False
    peak_price:  float = 0.0
    dca_count:   int   = 0


class RiskManager:
    KEEP_DAYS = 7

    def __init__(self, config: RiskConfig = None):
        self.config       = config or RiskConfig()
        self.daily_trades: Dict[str, int]         = {}
        self.daily_pnl:    Dict[str, float]       = {}
        self.open_trades:  Dict[str, TradeRecord] = {}

    def _today(self) -> str:
        return date.today().isoformat()

    def _prune_old_days(self):
        cutoff = (date.today() - timedelta(days=self.KEEP_DAYS)).isoformat()
        for d in [k for k in list(self.daily_trades) if k < cutoff]:
            del self.daily_trades[d]
        for d in [k for k in list(self.daily_pnl) if k < cutoff]:
            del self.daily_pnl[d]

    def can_trade(self, balance_usd: float, open_orders_count: int):
        today        = self._today()
        trades_today = self.daily_trades.get(today, 0)
        pnl_today    = self.daily_pnl.get(today, 0.0)
        if trades_today >= self.config.max_daily_trades:
            return False, f"Daily trade limit ({trades_today})"
        if pnl_today <= -self.config.max_daily_loss_usd:
            return False, f"Daily loss limit (${pnl_today:.2f})"
        if open_orders_count >= self.config.max_open_orders:
            return False, f"Max open orders ({open_orders_count})"
        if balance_usd < 50:
            return False, f"Insufficient USD (${balance_usd:.2f})"
        return True, "OK"

    def calculate_quantity(self, balance_usd: float, price: float, override_risk_pct: float = None) -> float:
        """
        Compound sizing:
        يستخدم 50% من الرصيد المتاح، ومع نمو الرصيد تنمو الكمية تلقائيًا.
        """
        COMPOUND_FRACTION = 0.50

        if balance_usd <= 0 or price <= 0:
            return 0.0

        quantity = (balance_usd * COMPOUND_FRACTION) / price
        quantity = min(quantity, self.config.max_position_kg)

        quantity = max(0.001, round(quantity, 3))

        if quantity * price > balance_usd * COMPOUND_FRACTION:
            quantity = (balance_usd * COMPOUND_FRACTION * 0.99) / price
            quantity = max(0.001, round(quantity, 3))

        return quantity

    def calculate_take_profit(self, action: str, price: float) -> float:
        """حساب هدف الربح."""
        if action == "B":
            tp = price * (1 + self.config.take_profit_pct)
        else:
            tp = price * (1 - self.config.take_profit_pct)
        return round(tp, 2)

    def calculate_stop_loss(self, action: str, price: float, price_history=None) -> float:
        """حساب وقف الخسارة الوقائي - ديناميكي ATR أو ثابت كـ fallback."""
        if self.config.stop_loss_pct <= 0:
            return 0.0
        if action == "B":
            if price_history and len(price_history) >= 15:
                sl = dynamic_stop_loss(price, price_history,
                                       multiplier=2.0,
                                       fallback_pct=self.config.stop_loss_pct)
            else:
                sl = price * (1 - self.config.stop_loss_pct)
        else:
            sl = price * (1 + self.config.stop_loss_pct)
        return round(sl, 2)

    def is_spread_acceptable(self, bid: float, ask: float) -> bool:
        if bid is None or ask is None or bid <= 0 or ask <= bid:
            return False
        return (ask - bid) / bid <= self.config.max_acceptable_spread_pct

    def register_trade(self, trade: TradeRecord):
        self._prune_old_days()
        today = self._today()
        self.daily_trades[today] = self.daily_trades.get(today, 0) + 1
        self.open_trades[trade.order_id] = trade
        logger.info(
            f"Trade: {trade.action} {trade.quantity}kg @ {trade.entry_price} "
            f"| TP={trade.take_profit} | SL={trade.stop_loss}"
        )

    def update_pnl(self, order_id: str, current_price: float) -> Dict:
        trade = self.open_trades.get(order_id)
        if not trade:
            return {}
        if trade.action == "B":
            pnl = (current_price - trade.entry_price) * trade.quantity
        else:
            pnl = (trade.entry_price - current_price) * trade.quantity
        trade.pnl = pnl
        return {"pnl": pnl}

    def close_trade(self, order_id: str):
        trade = self.open_trades.pop(order_id, None)
        if trade:
            today = self._today()
            self.daily_pnl[today] = self.daily_pnl.get(today, 0) + trade.pnl

    def get_stats(self) -> Dict:
        today = self._today()
        return {
            "trades_today":   self.daily_trades.get(today, 0),
            "daily_pnl":      self.daily_pnl.get(today, 0.0),
            "open_positions": len(self.open_trades),
        }
