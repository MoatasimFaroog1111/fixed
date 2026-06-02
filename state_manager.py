"""
State Manager — ذاكرة مستمرة تبقى بعد كل restart
"""
import json, os, logging, threading
from datetime import date
from typing import Dict, Any

logger  = logging.getLogger(__name__)
DEFAULT = "state.json"

class StateManager:
    def __init__(self, path: str = DEFAULT):
        self.path  = path
        self._lock = threading.Lock()
        self.data: Dict[str, Any] = {
            "trades": {}, "daily": {}, "total_pnl": 0.0, "version": 2,
        }
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            logger.info("StateManager: لا يوجد state.json — بداية جديدة")
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.data.update(saved)
            n     = len(self.data.get("trades", {}))
            total = self.data.get("total_pnl", 0.0)
            logger.info(f"StateManager: ✅ محمَّل — {n} صفقة | PnL تراكمي=${total:+.2f}")
        except Exception as e:
            logger.warning(f"StateManager: فشل التحميل: {e}")

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.error(f"StateManager: فشل الحفظ: {e}")

    def record_open(self, trade):
        with self._lock:
            self.data["trades"][trade.order_id] = {
                "order_id": trade.order_id, "action": trade.action,
                "security_id": trade.security_id, "currency": trade.currency,
                "quantity": trade.quantity, "entry_price": trade.entry_price,
                "take_profit": trade.take_profit, "stop_loss": trade.stop_loss,
                "timestamp": trade.timestamp, "dca_count": trade.dca_count,
                "peak_price": trade.peak_price,
            }
            self._save()
        logger.info(f"StateManager: حُفظ {trade.order_id} @ {trade.entry_price:,.0f}")

    def record_close(self, order_id: str, pnl: float):
        with self._lock:
            self.data["trades"].pop(order_id, None)
            today = date.today().isoformat()
            day   = self.data["daily"].setdefault(today, {"trades": 0, "pnl": 0.0})
            day["trades"] += 1
            day["pnl"]     = round(day["pnl"] + pnl, 4)
            self.data["total_pnl"] = round(self.data.get("total_pnl", 0.0) + pnl, 4)
            self._save()
        logger.info(f"StateManager: مُغلَق {order_id} | PnL={pnl:+.2f} | تراكمي={self.data['total_pnl']:+.2f}")

    def restore_to_risk(self, risk_manager) -> int:
        from risk_manager import TradeRecord
        restored = 0
        for oid, t in self.data.get("trades", {}).items():
            if oid in risk_manager.open_trades:
                ex = risk_manager.open_trades[oid]
                ex.entry_price = t["entry_price"]
                ex.take_profit = t["take_profit"]
                ex.stop_loss   = t.get("stop_loss", 0.0)
                ex.dca_count   = t.get("dca_count", 0)
                ex.peak_price  = t.get("peak_price", t["entry_price"])
                logger.info(f"StateManager: ✅ سعر حقيقي لـ {oid}: {t['entry_price']:,.0f}")
            else:
                trade = TradeRecord(
                    order_id=t["order_id"], action=t["action"],
                    security_id=t["security_id"], currency=t["currency"],
                    quantity=t["quantity"], entry_price=t["entry_price"],
                    take_profit=t["take_profit"], stop_loss=t.get("stop_loss", 0.0),
                    timestamp=t["timestamp"], peak_price=t.get("peak_price", t["entry_price"]),
                    dca_count=t.get("dca_count", 0),
                )
                risk_manager.open_trades[oid] = trade
                logger.info(f"StateManager: ✅ مُستعاد {oid} @ {t['entry_price']:,.0f}")
            restored += 1
        if restored:
            logger.info(f"StateManager: استُعيد {restored} مركز بأسعار دخول حقيقية")
        return restored

    def get_summary(self) -> dict:
        today = date.today().isoformat()
        day   = self.data.get("daily", {}).get(today, {})
        return {
            "total_pnl":      self.data.get("total_pnl", 0.0),
            "trades_today":   day.get("trades", 0),
            "pnl_today":      day.get("pnl", 0.0),
            "open_positions": len(self.data.get("trades", {})),
            "trading_days":   len(self.data.get("daily", {})),
        }
