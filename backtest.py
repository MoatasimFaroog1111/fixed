"""
Backtest Engine v2
التغييرات:
  - إصلاح H-04: إزالة short-selling (BullionVault لا يدعمه)
  - إصلاح H-05: إضافة عمولة 0.2% لكل صفقة
  - إصلاح M-07: Sharpe ratio يستخدم annualization صحيحاً حسب POLL_INTERVAL
"""
import numpy as np
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

COMMISSION_PCT  = 0.002   # عمولة BullionVault ≈ 0.12–0.50%، نستخدم 0.2% تقديراً متحفظاً
POLL_INTERVAL_S = 15      # ثواني بين كل دورة (15 ثانية)


class BacktestEngine:
    """
    يُحاكي منطق البوت على سلسلة أسعار تاريخية.
    يقيس: PnL، نسبة الربح، Sharpe ratio، max drawdown.
    ملاحظة: BUY فقط — لا short-selling على المعادن الفيزيائية.
    """
    def __init__(self, predictor, risk_manager, strategy_class):
        self.predictor      = predictor
        self.risk           = risk_manager
        self.strategy_class = strategy_class
        self.trades: List[Dict] = []

    def run(self, prices: List[float], security_id="AUXLN", currency="USD",
            poll_interval_s: int = POLL_INTERVAL_S) -> Dict:
        strategy    = self.strategy_class(self.predictor, self.risk)
        balance     = {"USD": {"available": 10000.0}}
        equity_curve = [10000.0]
        cash        = 10000.0
        position    = 0.0
        entry_price = 0.0

        for i, price in enumerate(prices):
            spread      = price * 0.0003
            market_data = [{
                "securityId": security_id,
                "currency":   currency,
                "bids": [{"action": "B", "quantity": 1.0, "limit": price - spread}],
                "asks": [{"action": "S", "quantity": 1.0, "limit": price + spread}],
            }]
            balance["USD"]["available"] = cash

            signal = strategy.evaluate(market_data, balance, security_id, currency)

            # BUY فقط — إصلاح H-04
            if signal and signal.action == "B" and position == 0:
                position    = signal.quantity
                entry_price = price + spread
                # طرح الكمية + العمولة — إصلاح H-05
                cost        = position * entry_price * (1 + COMMISSION_PCT)
                if cost <= cash:
                    cash -= cost
                    self.trades.append({
                        "type": "BUY", "entry": entry_price,
                        "quantity": position, "index": i,
                    })
                else:
                    position = 0   # رصيد غير كافٍ

            elif position > 0:
                # الخروج: Take Profit أو Stop Loss وقائي
                pnl_pct = (price - entry_price) / entry_price
                if pnl_pct >= self.risk.config.take_profit_pct or pnl_pct <= -getattr(self.risk.config, "stop_loss_pct", 0.05):
                    proceeds = position * price * (1 - COMMISSION_PCT)
                    cash    += proceeds
                    pnl      = (price - entry_price) * position - \
                               position * entry_price * COMMISSION_PCT - \
                               position * price * COMMISSION_PCT
                    self.trades[-1]["exit"] = price
                    self.trades[-1]["pnl"]  = pnl
                    position = 0

            total_equity = cash + position * price
            equity_curve.append(total_equity)

        # تقدير عدد الدورات في السنة بناءً على poll_interval
        periods_per_year = int(365 * 24 * 3600 / poll_interval_s)
        return self._compute_stats(equity_curve, periods_per_year)

    def _compute_stats(self, equity: List[float],
                        periods_per_year: int = 2_102_400) -> Dict:
        e        = np.array(equity)
        returns  = np.diff(e) / (e[:-1] + 1e-10)
        total_return = (e[-1] - e[0]) / e[0] * 100

        # إصلاح M-07: sqrt(periods_per_year) بدلاً من sqrt(252)
        sharpe = (returns.mean() / (returns.std() + 1e-10)) * np.sqrt(periods_per_year)

        drawdowns = (e - np.maximum.accumulate(e)) / (np.maximum.accumulate(e) + 1e-10)
        max_dd    = drawdowns.min() * 100

        closed   = [t for t in self.trades if "pnl" in t]
        win_rate = sum(1 for t in closed if t["pnl"] > 0) / max(len(closed), 1) * 100

        stats = {
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio":     round(sharpe, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct":     round(win_rate, 1),
            "total_trades":     len(closed),
            "final_equity":     round(e[-1], 2),
            "commission_paid":  round(
                sum(t.get("quantity", 0) * (t.get("entry", 0) + t.get("exit", t.get("entry", 0))) * COMMISSION_PCT
                    for t in closed), 2
            ),
        }
        logger.info("Backtest Results:")
        for k, v in stats.items():
            logger.info(f"  {k}: {v}")
        return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    sys.path.insert(0, ".")
    from ml_predictor import get_predictor
    from risk_manager import RiskManager, RiskConfig
    from strategy import TradingStrategy

    np.random.seed(42)
    n      = 500
    prices = 3000 + np.cumsum(np.random.randn(n) * 2)

    predictor = get_predictor(use_ml=False)
    risk      = RiskManager(RiskConfig())
    engine    = BacktestEngine(predictor, risk, TradingStrategy)
    results   = engine.run(prices.tolist())
    print("\nBacktest complete:", results)
