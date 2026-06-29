"""
Base Trading Bot v7
"""

import time
import json
from pathlib import Path
import logging
import signal
import sys
import os
from datetime import datetime, timezone
import requests

from api_client import BullionVaultAPI
from parser import parse_market, parse_balance, parse_orders, best_bid, best_ask
from ml_predictor import get_predictor
from risk_manager import RiskManager, RiskConfig, TradeRecord
from strategy import TradingStrategy
from hourly_scalp_strategy import HourlyScalpConfig, HourlyScalpStrategy
from telegram_controller import TelegramController
from monitoring import write_heartbeat
from state_manager import StateManager
from daily_reporter import DailyReporter
from shared_utils import (
    read_control_state,
    save_control_state,
    extract_usd_available,
    append_json_log,
    append_jsonl,
    setup_logger,
)

logger_init = logging.getLogger(__name__)

try:
    from db_logger import log_trade, update_bot_status
    DB_LOGGING_AVAILABLE = True
except Exception as e:
    logger_init.warning("DB logger disabled: %s", e)
    DB_LOGGING_AVAILABLE = False

try:
    from news_analyzer import NewsAnalyzer
    NEWS_AVAILABLE = True
except Exception as e:
    logger_init.warning("NewsAnalyzer unavailable: %s", e)
    NEWS_AVAILABLE = False


class DisabledTelegramController:
    is_paused = False
    is_paused = False
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


TRADE_MEMORY_FILE = "trade_history.jsonl"


def log_trade_memory(event: dict):
    append_jsonl(TRADE_MEMORY_FILE, event)


# ── Price Log ─────────────────────────────────────────────────────
def log_price_history(security_id: str, price: float, max_len: int = 200):
    """يحفظ آخر 200 سعر في ملف JSON لكل معدن."""
    path = f"price_log_{security_id}.json"
    append_json_log(path, {"price": price, "ts": datetime.utcnow().isoformat()}, max_entries=max_len)

# ── Trade Log ──────────────────────────────────────────────────────
def log_closed_trade(trade, exit_price: float, reason: str):
    """يسجل الصفقة المغلقة في trade_log.json."""
    pnl = (exit_price - trade.entry_price) * trade.quantity
    pnl_pct = (exit_price - trade.entry_price) / trade.entry_price * 100
    append_json_log("trade_log.json", {
        "symbol":      trade.security_id,
        "action":      trade.action,
        "quantity":    trade.quantity,
        "entry_price": trade.entry_price,
        "exit_price":  exit_price,
        "peak_price":  trade.peak_price,
        "pnl":         round(pnl, 4),
        "pnl_pct":     round(pnl_pct, 4),
        "reason":      reason,
        "timestamp":   datetime.utcnow().isoformat(),
        "dca_count":   trade.dca_count,
    }, max_entries=500)

MIN_DAILY_PROFIT_TARGET_USD = 100
PROFIT_LOCK_USD = 70
MAX_DAILY_LOSS_USD = 35
ADDONS_AVAILABLE = True


def _setup_logging(bot_name, log_file):
    return setup_logger(bot_name, log_file)



class BaseMetalBot:
    BOT_NAME      = "MetalBot"
    SECURITY_ID   = ""
    CURRENCY      = "USD"
    POLL_INTERVAL = 15
    USE_ML        = True
    DRY_RUN       = True
    LOG_FILE      = "bot.log"
    USE_NEWS      = True

    MAX_POSITION_KG             = 0.05
    MAX_DAILY_TRADES            = 50
    MAX_DAILY_LOSS_USD          = 99999
    TAKE_PROFIT_PCT             = 0.008
    MIN_SPREAD_PCT              = 0.002
    MAX_OPEN_ORDERS             = 1
    CONFIDENCE_THRESHOLD        = 0.62
    PRICE_ROUND_TO              = 10
    MAX_POSITION_PCT_OF_BALANCE = 0.25
    MAX_ACCEPTABLE_SPREAD_PCT   = 0.006
    POSITION_RISK_PCT           = 0.02
    STOP_LOSS_PCT               = 0.050

    # Hourly scalping gate: BUY is executed only when the core strategy and
    # this rolling-volatility scalp filter agree.
    SCALP_ENABLED                    = True
    SCALP_MIN_HOURLY_VOLATILITY_PCT  = 0.004
    SCALP_ENTRY_DROP_PCT             = 0.007
    SCALP_TAKE_PROFIT_PCT            = 0.012
    SCALP_STOP_LOSS_PCT              = 0.050
    SCALP_TRAILING_STOP_PCT          = 0.005
    SCALP_MAX_SPREAD_TO_TP_RATIO     = 0.75
    SCALP_MAX_TRADES_PER_DAY         = 3
    SCALP_RSI_BUY_LEVEL              = 45.0
    SCALP_RSI_SELL_LEVEL             = 58.0

    TRAILING_ACTIVATE_PCT = 0.005
    TRAILING_DISTANCE_PCT = 0.003
    DCA_ENABLED           = True
    DCA_TRIGGER_PCT       = 0.010
    DCA_MAX_TIMES         = 1
    DCA_SIZE_RATIO        = 0.50
    TRADING_HOURS_ONLY    = False
    TRADING_HOURS_UTC     = [(7, 12), (13, 19)]

    TG_TOKEN_ENV = ""
    TG_CHAT_ENV  = "TG_CHAT_ID"

    def __init__(self, username: str, password: str):
        _setup_logging(self.BOT_NAME, self.LOG_FILE)
        self.logger = logging.getLogger(self.BOT_NAME)
        self.api    = BullionVaultAPI(username, password)

        risk_config = RiskConfig(
            max_position_kg=self.MAX_POSITION_KG,
            max_daily_trades=self.MAX_DAILY_TRADES,
            max_daily_loss_usd=self.MAX_DAILY_LOSS_USD,
            take_profit_pct=self.TAKE_PROFIT_PCT,
            stop_loss_pct=self.STOP_LOSS_PCT,
            max_acceptable_spread_pct=self.MAX_ACCEPTABLE_SPREAD_PCT,
            max_open_orders=self.MAX_OPEN_ORDERS,
            confidence_threshold=self.CONFIDENCE_THRESHOLD,
            position_risk_pct=self.POSITION_RISK_PCT,
        )
        self.risk = RiskManager(risk_config)
        self.predictor = get_predictor(self.USE_ML, security_id=self.SECURITY_ID)

        self.news_analyzer = None
        if self.USE_NEWS and NEWS_AVAILABLE and os.environ.get("ANTHROPIC_API_KEY"):
            try:
                self.news_analyzer = NewsAnalyzer()
                self.logger.info("NewsAnalyzer مفعّل — تحليل الأخبار عبر Claude API")
            except Exception as e:
                self.logger.warning(f"فشل تهيئة NewsAnalyzer: {e}")
        elif self.USE_NEWS and not os.environ.get("ANTHROPIC_API_KEY"):
            self.logger.info("ANTHROPIC_API_KEY غير موجود — تحليل الأخبار معطّل")

        self.strategy = TradingStrategy(
            self.predictor,
            self.risk,
            news_analyzer=self.news_analyzer,
        )
        self.hourly_strategy = HourlyScalpStrategy(HourlyScalpConfig(
            min_hourly_volatility_pct=self.SCALP_MIN_HOURLY_VOLATILITY_PCT,
            entry_drop_pct=self.SCALP_ENTRY_DROP_PCT,
            take_profit_pct=self.SCALP_TAKE_PROFIT_PCT,
            stop_loss_pct=self.SCALP_STOP_LOSS_PCT,
            trailing_stop_pct=self.SCALP_TRAILING_STOP_PCT,
            max_spread_to_tp_ratio=self.SCALP_MAX_SPREAD_TO_TP_RATIO,
            max_trades_per_day=self.SCALP_MAX_TRADES_PER_DAY,
            rsi_buy_level=self.SCALP_RSI_BUY_LEVEL,
            rsi_sell_level=self.SCALP_RSI_SELL_LEVEL,
        ))
        self.running = False
        self._alerted_profit_100 = False
        self._alerted_loss_35    = False
        self._last_alert_date    = None

        self._tg_token = os.environ.get(self.TG_TOKEN_ENV, "")
        self._tg_chat  = os.environ.get(self.TG_CHAT_ENV,  "")

        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        # ── الأنظمة الإضافية ───────────────────────────────────────
        self.state_mgr = None
        self.tg_ctrl   = None
        self.reporter  = None
        if ADDONS_AVAILABLE:
            self.state_mgr = StateManager(path=f"state_{self.SECURITY_ID}.json")
            self.tg_ctrl   = DisabledTelegramController(token=self._tg_token, chat_id=self._tg_chat, bot_ref=self)
            self.reporter  = DailyReporter(tg_controller=self.tg_ctrl, bot_ref=self)

    # ── Telegram ──────────────────────────────────────────────────

    def tg(self, text: str):
        if not self._tg_token or not self._tg_chat:
            return
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self._tg_token}/sendMessage",
                data={"chat_id": self._tg_chat, "text": text},
                timeout=10,
            )
            if resp.status_code != 200:
                self.logger.warning(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            self.logger.error(f"Telegram: {e}")

    def _shutdown(self, signum, frame):
        self.logger.info(f"Shutdown. Stopping {self.BOT_NAME}...")
        self.tg(f"{self.BOT_NAME}\nBot stopping...")
        self.running = False
        self._alerted_profit_100 = False
        self._alerted_loss_35    = False
        self._last_alert_date    = None

    # ── مساعدات ───────────────────────────────────────────────────

    def _get_yesterday_pnl(self) -> float:
        """يجلب PnL اليوم الماضي من StateManager."""
        try:
            from datetime import date, timedelta
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            if self.state_mgr:
                summary = self.state_mgr.data.get("daily", {})
                return summary.get(yesterday, {}).get("pnl", 0.0)
        except Exception as e:
            self.logger.warning("Failed to get yesterday PnL: %s", e)
        return 0.0

    def _daily_target_adjustments(self) -> tuple:
        """
        يُعدِّل معاملات التداول بناءً على هدف 100$/يوم.
        يعيد: (confidence_threshold, position_multiplier, alert_type)
        alert_type: None | 'profit_100' | 'loss_35'
        """
        stats     = self.risk.get_stats()
        pnl_today = stats["daily_pnl"]

        # تعويض خسارة اليوم الماضي
        yesterday_pnl    = self._get_yesterday_pnl()
        pos_multiplier   = 1.25 if yesterday_pnl < -10 else 1.0

        # ضبط مستوى الثقة بناءً على PnL اليوم
        if pnl_today >= 100:
            return 0.85, pos_multiplier, "profit_100"
        elif pnl_today >= 50:
            return 0.75, pos_multiplier, None
        elif pnl_today <= -35:
            return self.CONFIDENCE_THRESHOLD, pos_multiplier, "loss_35"
        else:
            return self.CONFIDENCE_THRESHOLD, pos_multiplier, None

    def _is_trading_hours(self) -> bool:
        if not self.TRADING_HOURS_ONLY:
            return True
        hour = datetime.now(timezone.utc).hour
        return any(s <= hour < e for s, e in self.TRADING_HOURS_UTC)

    def _spread_acceptable(self, bid: float, ask: float) -> bool:
        if not bid or not ask or bid <= 0:
            return False
        spread_pct = (ask - bid) / bid
        if spread_pct > self.MAX_ACCEPTABLE_SPREAD_PCT:
            self.logger.info(f"سبريد مرفوض: {spread_pct*100:.2f}%")
            return False
        return True

    def _round_price(self, price: float) -> int:
        n = max(1, self.PRICE_ROUND_TO)
        return int(round(price / n) * n)

    def _fetch_market(self):
        root = self.api.view_market(
            currency=self.CURRENCY, security_id=self.SECURITY_ID,
            quantity=0.001, market_width=5,
        )
        return parse_market(root) if root is not None else None

    def _fetch_balance(self):
        now = time.time()

        if not hasattr(self, "_balance_cache"):
            self._balance_cache = {}
            self._balance_cache_time = 0

        # BullionVault rate-limit protection: لا تطلب الرصيد أكثر من مرة كل 60 ثانية
        if self._balance_cache and (now - self._balance_cache_time) < 60:
            return self._balance_cache

        try:
            root = self.api.view_balance(simple=True)
            bal = parse_balance(root) if root is not None else {}
            self._balance_cache = bal
            self._balance_cache_time = now
            return bal
        except Exception as e:
            self.logger.warning(f"Balance fetch failed, using cached balance if available: {e}")
            return self._balance_cache or {}

    def _calculate_quantity(self, balance_usd: float, price: float,
                             ratio: float = 1.0) -> float:
        """للاستخدام في DCA فقط."""
        max_by_cap = (balance_usd * self.MAX_POSITION_PCT_OF_BALANCE * ratio) / price
        quantity   = min(self.MAX_POSITION_KG * ratio, max_by_cap)
        quantity   = max(0.001, round(quantity, 3))
        if quantity * price > balance_usd * 0.95:
            return 0.0
        return quantity

    # ── تحميل المراكز الموجودة ────────────────────────────────────

    def _load_existing_positions(self):
        self.logger.info(f"فحص vault للمراكز الموجودة ({self.SECURITY_ID})...")
        bal      = self._fetch_balance()
        held_qty = float(bal.get(self.SECURITY_ID, {}).get("available", 0))
        if held_qty < 0.001:
            self.logger.info(f"لا يوجد {self.SECURITY_ID} في vault.")
            return
        market_data   = self._fetch_market()
        if not market_data:
            return
        current_price = best_bid(market_data, self.SECURITY_ID, self.CURRENCY)
        if not current_price:
            return

        # سعر الدخول الحقيقي غير متاح — نستخدم السعر الحالي مرجعاً فقط.
        # SL=0 لتعطيل وقف الخسارة على المراكز القديمة (تجنب إغلاق خاطئ).
        # TP واسع جداً حتى لا يُغلق تلقائياً بسعر خاطئ.
        # استخدام نفس منطق إدارة المخاطر لتحديد TP/SL للمراكز المحمَّلة من الـ vault
        take_profit  = self.risk.calculate_take_profit("B", current_price)
        stop_loss    = self.risk.calculate_stop_loss("B", current_price, self.strategy.price_history)
        synthetic_id = f"VAULT_{self.SECURITY_ID}_{int(time.time())}"

        trade = TradeRecord(
            order_id=synthetic_id, action="B",
            security_id=self.SECURITY_ID, currency=self.CURRENCY,
            quantity=held_qty, entry_price=current_price,
            take_profit=take_profit, stop_loss=stop_loss,
            timestamp="existing", peak_price=current_price,
        )
        self.risk.open_trades[synthetic_id] = trade
        msg = (f"✅ مركز موجود مُحمَّل\n"
               f"   {self.SECURITY_ID} | {held_qty}kg\n"
               f"   سعر مرجعي: {current_price:,.0f} | TP: {take_profit:,.0f} | SL: {stop_loss:,.0f}\n"
               f"   تنبيه: سعر الدخول الحقيقي غير متاح من الرصيد فقط؛ راجع سجل أوامر BullionVault عند الحاجة.")
        self.logger.info(msg)
        self.tg(f"{self.BOT_NAME}\n{msg}")

    # ── مراقبة المراكز المفتوحة ───────────────────────────────────

    def _control_state(self) -> dict:
        return read_control_state(logger=self.logger)

    def _save_control_state(self, state: dict):
        save_control_state(state)

    def _monitor_positions(self, market_data, balance: dict):
        control = self._control_state()

        if control.get("emergency_close_all", False):
            self.logger.warning("CONTROL: emergency_close_all active")
            # # self.tg(
#                 f"{self.BOT_NAME}\n"
#                 f"🚨 CLOSE ALL executing...\n"
#                 f"Open trades: {len(self.risk.open_trades)}"
#             )

            closed = 0
            failed = 0

            for order_id, trade in list(self.risk.open_trades.items()):
                current = best_bid(market_data, trade.security_id, trade.currency)

                if current is None:
                    self.logger.error(
                        f"CLOSE_ALL failed: no bid for {trade.security_id}"
                    )
                    failed += 1
                    continue

                if self.DRY_RUN:
                    ok = True
                else:
                    ok = self._place_close_order(trade, current)

                if ok:
                    self.risk.close_trade(order_id)
                    closed += 1
                else:
                    failed += 1

            control["emergency_close_all"] = False
            control["allow_buy"] = False

            if control.get("paused_after_close_all", True):
                control["paused"] = True

            self._save_control_state(control)

            # # self.tg(
#                 f"{self.BOT_NAME}\n"
#                 f"🚨 CLOSE ALL finished\n"
#                 f"Closed: {closed}\n"
#                 f"Failed: {failed}\n"
#                 f"Buying disabled. Paused={control.get('paused')}"
#             )

            return

        usd = extract_usd_available(balance)
        for order_id, trade in list(self.risk.open_trades.items()):
            current = (best_bid if trade.action == "B" else best_ask)(
                market_data, trade.security_id, trade.currency
            )
            if current is None:
                continue
            self.risk.update_pnl(order_id, current)
            pnl        = trade.pnl
            change_pct = (current - trade.entry_price) / trade.entry_price * 100

            if current > trade.peak_price:
                trade.peak_price = current

            # Break-even protection:
            # إذا وصل الربح إلى +0.6%، حرّك وقف الخسارة إلى سعر الدخول.
            # هذا يحوّل الصفقة إلى No-Lose Trade تقريباً بعد تغطية الحركة المطلوبة.
            pnl_pct_decimal = (current - trade.entry_price) / trade.entry_price
            if (
                trade.action == "B"
                and trade.stop_loss > 0
                and pnl_pct_decimal >= 0.006
                and trade.stop_loss < trade.entry_price
            ):
                trade.stop_loss = trade.entry_price
                be_msg = (
                    f"🔒 Break-even activated | {trade.security_id} | "
                    f"SL moved to entry: {trade.stop_loss:.2f}"
                )
                self.logger.info(be_msg)
                # # self.tg(
#                     f"{self.BOT_NAME}\n"
#                     f"🔒 Break-even activated\n"
#                     f"{trade.security_id}\n"
#                     f"StopLoss moved to entry: {trade.stop_loss:.2f}"
#                 )

            hit_stop      = trade.stop_loss > 0 and current <= trade.stop_loss
            hit_fixed_tp  = current >= trade.take_profit
            min_for_trail = trade.entry_price * (1 + self.TRAILING_ACTIVATE_PCT)
            trail_price   = trade.peak_price * (1 - self.TRAILING_DISTANCE_PCT)
            hit_trailing  = (trade.peak_price >= min_for_trail and current <= trail_price)

            if hit_stop or hit_fixed_tp or hit_trailing:
                label = "Stop Loss" if hit_stop else "Trailing TP" if hit_trailing else "Take Profit"
                icon = "🛑" if hit_stop else "✅"
                msg   = (f"{icon} {label}!\n"
                         f"   {order_id[:20]}\n"
                         f"   دخول={trade.entry_price:,.0f} قمة={trade.peak_price:,.0f} حالي={current:,.0f}\n"
                         f"   PnL: ${pnl:.2f} ({change_pct:+.2f}%)")
                self.logger.info(msg)
                self.tg(f"{self.BOT_NAME}\n{msg}")
                close_ok = True
                if not self.DRY_RUN:
                    close_ok = self._place_close_order(trade, current)
                if close_ok:
                    if self.state_mgr:
                        self.state_mgr.record_close(order_id, pnl)
                    self.risk.close_trade(order_id)
                else:
                    self.logger.error("لم يتم حذف المركز من الذاكرة لأن أمر البيع فشل.")
            else:
                dca_trigger = trade.entry_price * (1 - self.DCA_TRIGGER_PCT)
                if (self.DCA_ENABLED and trade.dca_count < self.DCA_MAX_TIMES
                        and current <= dca_trigger and usd > 100):
                    self._execute_dca(trade, current, usd)
                    _bal = self._fetch_balance()
                    usd = extract_usd_available(_bal)

                trail_info = (f" | trail@{trail_price:,.0f}"
                              if trade.peak_price >= min_for_trail else "")
                self.logger.info(
                    f"مركز | {trade.security_id} | "
                    f"دخول={trade.entry_price:,.0f} حالي={current:,.0f} "
                    f"({change_pct:+.2f}%) | PnL=${pnl:.2f} | TP={trade.take_profit:,.0f} | SL={trade.stop_loss:,.0f}"
                    f"{trail_info}"
                )

    # ── DCA ───────────────────────────────────────────────────────

    def _execute_dca(self, trade: TradeRecord, current_price: float,
                     balance_usd: float):
        dca_qty = self._calculate_quantity(balance_usd, current_price,
                                           self.DCA_SIZE_RATIO)
        if dca_qty <= 0:
            return
        limit_price = self._round_price(current_price)
        if self.DRY_RUN:
            msg = f"[DRY_RUN] DCA #{trade.dca_count + 1} | {dca_qty}kg @ {limit_price}"
            self.logger.info(msg)
            self.tg(f"{self.BOT_NAME}\n{msg}")
            return
        resp = self.api.place_order(
            action="B", security_id=trade.security_id,
            currency=trade.currency, quantity=dca_qty,
            limit=limit_price, type_code="TIL_CANCEL",
        )
        if resp is None:
            return
        orders = parse_orders(resp)
        if orders:
            o = orders[0]
            status = o.get("statusCode")
            if status == "OPEN":
                self.logger.info(f"DCA order OPEN ولم تُحدَّث الصفقة حتى يتم التنفيذ: {o.get('orderId')}")
                return
            if status not in {"DONE", "MATCHED", "PARTIALLY_MATCHED"}:
                self.logger.warning(f"DCA مرفوض/غير منفذ: {status}")
                return
            actual_qty = o.get("quantityMatched") or o.get("quantity") or dca_qty
            if actual_qty <= 0:
                self.logger.info("DCA لم يطابق أي كمية؛ لا تحديث للصفقة.")
                return
            new_qty   = round(trade.quantity + actual_qty, 3)
            avg_price = round(
                (trade.entry_price * trade.quantity + limit_price * actual_qty) / new_qty, 2
            )
            trade.quantity    = new_qty
            trade.entry_price = avg_price
            trade.dca_count  += 1
            # إصلاح H-03: تحديث take_profit بالمتوسط الجديد
            new_tp            = self.risk.calculate_take_profit("B", avg_price)
            new_sl            = self.risk.calculate_stop_loss("B", avg_price, self.strategy.price_history)
            trade.take_profit = new_tp
            trade.stop_loss   = new_sl
            msg = (f"💰 DCA #{trade.dca_count} | {actual_qty}kg @ {limit_price}\n"
                   f"   متوسط: {avg_price:,.0f} | TP: {new_tp:,.0f} | SL: {new_sl:,.0f}")
            self.logger.info(msg)
            self.tg(f"{self.BOT_NAME}\n{msg}")

    # ── إغلاق المركز ─────────────────────────────────────────────

    def _place_close_order(self, trade: TradeRecord, current_price: float,
                            retry: bool = True):
        """
        إصلاح L-01: إرسال تنبيه عند الفشل + محاولة واحدة إعادة.
        """
        # Safety sync before SELL:
        # لا تبيع كمية أكبر من المتاحة فعليًا في BullionVault لتجنب NOFUNDS.
        fresh_balance = self._fetch_balance()
        available_qty = float(
            fresh_balance.get(trade.security_id, {}).get("available", 0) or 0
        )

        if available_qty < 0.001:
            self.logger.error(
                f"SELL blocked: no available vault quantity for {trade.security_id}. "
                f"bot_qty={trade.quantity}kg vault_qty={available_qty}kg"
            )
            # # self.tg(
#                 f"{self.BOT_NAME}\n"
#                 f"🚨 SELL blocked: لا توجد كمية متاحة في BullionVault\n"
#                 f"{trade.security_id}\n"
#                 f"Bot qty={trade.quantity}kg | Vault qty={available_qty}kg\n"
#                 f"Removing phantom trade from bot memory."
#             )
            return True

        sell_qty = min(float(trade.quantity), available_qty)
        sell_qty = max(0.001, round(sell_qty, 3))

        if sell_qty < float(trade.quantity):
            self.logger.warning(
                f"SELL qty adjusted to vault balance: "
                f"bot_qty={trade.quantity}kg -> sell_qty={sell_qty}kg"
            )
            # # self.tg(
#                 f"{self.BOT_NAME}\n"
#                 f"⚠️ تم تعديل كمية البيع حسب الرصيد الحقيقي\n"
#                 f"Bot qty={trade.quantity}kg\n"
#                 f"Sell qty={sell_qty}kg"
#             )
            trade.quantity = sell_qty

        limit_price = self._round_price(current_price * 0.998)
        resp = self.api.place_order(
            action="S", security_id=trade.security_id,
            currency=trade.currency, quantity=sell_qty,
            limit=limit_price, type_code="TIL_CANCEL",
        )
        if resp is not None:
            orders = parse_orders(resp)
            if orders:
                o = orders[0]
                status = o.get('statusCode')
                self.logger.info(f"بيع: {o['orderId']} | {status}")
                # # self.tg(f"{self.BOT_NAME}\nبيع: {status}")
                if status in {"DONE", "MATCHED"}:
                    return True
                if status == "PARTIALLY_MATCHED":
                    matched = o.get("quantityMatched", 0.0)
                    if matched >= trade.quantity * 0.999:
                        return True
                    if matched > 0:
                        trade.quantity = round(max(0.0, trade.quantity - matched), 3)
                        self.logger.warning(f"بيع جزئي فقط؛ الكمية المتبقية في الذاكرة: {trade.quantity}kg")
                    return False
                if status == "OPEN":
                    self.logger.warning("أمر البيع OPEN ولم يُغلق المركز بعد؛ سيبقى المركز تحت المراقبة.")
                    return False
                self.logger.warning(f"أمر البيع غير مقبول: {status}")

        # فشل — محاولة ثانية بعد 3 ثوان
        if retry:
            self.logger.warning("فشل أمر البيع — إعادة المحاولة بعد 3s...")
            # # self.tg(f"{self.BOT_NAME}\n⚠️ فشل أمر البيع — إعادة المحاولة...")
            time.sleep(3)
            return self._place_close_order(trade, current_price, retry=False)

        # فشل نهائي — تنبيه مهم
        alert = (f"🚨 فشل نهائي في البيع!\n"
                 f"   {trade.security_id} | {trade.quantity}kg\n"
                 f"   سعر: {current_price:,.0f}\n"
                 f"   تحقق يدوياً من المركز في BullionVault!")
        self.logger.error(alert)
        self.tg(f"{self.BOT_NAME}\n{alert}")
        return False


    # ── فلتر المضاربة الساعية ───────────────────────────────────────

    def _scalp_window_prices(self) -> list:
        """Return a rolling window that approximates the last hour.

        The bot polls every POLL_INTERVAL seconds, so 1 hour is roughly
        3600 / POLL_INTERVAL samples. If there are fewer samples, the method
        uses the available history and the scalp strategy remains in warm-up.
        """
        history = list(getattr(self.strategy, "price_history", []))
        if not history:
            return []
        samples_per_hour = max(15, int(3600 / max(1, self.POLL_INTERVAL)))
        return history[-samples_per_hour:]

    def _passes_hourly_scalp_filter(self, sig, bid: float, ask: float) -> bool:
        if not self.SCALP_ENABLED:
            return True

        prices = self._scalp_window_prices()
        stats = self.risk.get_stats()
        try:
            trend = self.strategy._ma_trend()
        except Exception as e:
            self.logger.warning("MA trend calculation failed, defaulting to NEUTRAL: %s", e)
            trend = "NEUTRAL"

        scalp = self.hourly_strategy.evaluate_from_prices(
            prices=prices,
            bid=bid,
            ask=ask,
            trades_today=stats.get("trades_today", 0),
            trend=trend,
        )

        if scalp.action != "BUY":
            self.logger.info(
                "Scalp filter blocked BUY | "
                f"action={scalp.action} | reason={scalp.reason} | "
                f"vol={scalp.volatility_pct:.3%} | rsi={scalp.rsi:.1f} | trend={trend}"
            )
            return False

        # Use the tighter scalping exits for the actual order.
        sig.price = scalp.entry_price or sig.price
        sig.take_profit = scalp.take_profit or sig.take_profit
        sig.reason = f"{sig.reason} | {scalp.reason}"

        # RiskManager calculates SL from config during registration. Keep the
        # config aligned with the scalp stop loss while this strategy is active.
        self.risk.config.stop_loss_pct = self.SCALP_STOP_LOSS_PCT
        self.TAKE_PROFIT_PCT = self.SCALP_TAKE_PROFIT_PCT
        self.logger.info(
            "Scalp filter approved BUY | "
            f"entry={sig.price:.2f} | TP={sig.take_profit:.2f} | "
            f"SL={scalp.stop_loss:.2f} | vol={scalp.volatility_pct:.3%} | rsi={scalp.rsi:.1f}"
        )
        return True

    # ── تنفيذ إشارة BUY ──────────────────────────────────────────

    def _execute(self, sig, balance):
        """
        إصلاح H-02: يستخدم sig.quantity بدلاً من إعادة الحساب.
        يُنفِّذ BUY فقط (SELL يُصفَّى في run() قبل الوصول هنا).
        """
        usd_balance = extract_usd_available(balance)
        # تطبيق مضاعف التعويض إذا كان موجوداً
        _adj, _mult, _ = self._daily_target_adjustments()
        quantity = round(sig.quantity * _mult, 3)

        if quantity <= 0:
            return

        if quantity * sig.price > usd_balance * 0.95:
            self.logger.info("الكمية تتجاوز الرصيد المتاح — تخطي")
            if DB_LOGGING_AVAILABLE:
                update_bot_status(self.BOT_NAME, "SKIPPED", "Quantity exceeds available USD balance")
            return

        msg = (
            f"إشارة شراء | ثقة={sig.confidence:.0%} | "
            f"{quantity}kg @ {sig.price:.0f} | {sig.reason}"
        )

        self.logger.info(msg)
        self.tg(f"{self.BOT_NAME}\n{msg}")

        if DB_LOGGING_AVAILABLE:
            update_bot_status(self.BOT_NAME, "BUY_SIGNAL", msg)

        if self.DRY_RUN:
            if DB_LOGGING_AVAILABLE:
                log_trade(
                    symbol=sig.security_id,
                    side="BUY",
                    quantity=quantity,
                    price=sig.price,
                    status="DRY_RUN_SIGNAL",
                    bot_name=self.BOT_NAME,
                )
            return

        limit_price = self._round_price(sig.price)

        resp = self.api.place_order(
            action="B",
            security_id=sig.security_id,
            currency=sig.currency,
            quantity=quantity,
            limit=limit_price,
            type_code="TIL_CANCEL",
        )

        if resp is None:
            if DB_LOGGING_AVAILABLE:
                log_trade(
                    symbol=sig.security_id,
                    side="BUY",
                    quantity=quantity,
                    price=limit_price,
                    status="API_NO_RESPONSE",
                    bot_name=self.BOT_NAME,
                )
                update_bot_status(self.BOT_NAME, "ERROR", "API returned no response on BUY order")
            return

        orders = parse_orders(resp)

        if orders:
            o = orders[0]
            status = o.get("statusCode", "")

            self.logger.info(f"أمر: {o['orderId']} | {status}")
            # tg: see logger line above

            if DB_LOGGING_AVAILABLE:
                log_trade(
                    symbol=sig.security_id,
                    side="BUY",
                    quantity=quantity,
                    price=limit_price,
                    status=status,
                    bot_name=self.BOT_NAME,
                )
                update_bot_status(
                    self.BOT_NAME,
                    "ORDER_" + str(status),
                    f"BUY order {o.get('orderId')} status {status}",
                )

            if status == "OPEN":
                self.logger.info("أمر الشراء OPEN ولم يتم تسجيله كمركز حتى تظهر كمية مطابقة.")
                return

            if status in {"DONE", "MATCHED", "PARTIALLY_MATCHED"}:
                actual_qty = o.get("quantityMatched") or o.get("quantity") or quantity

                if actual_qty <= 0:
                    self.logger.info("أمر الشراء لم يطابق أي كمية؛ لا تسجيل للمركز.")
                    return

                tp = self.risk.calculate_take_profit("B", limit_price)
                sl = self.risk.calculate_stop_loss("B", limit_price, self.strategy.price_history)

                _new_trade = TradeRecord(
                    order_id=o["orderId"],
                    action="B",
                    security_id=sig.security_id,
                    currency=sig.currency,
                    quantity=actual_qty,
                    entry_price=limit_price,
                    take_profit=tp,
                    stop_loss=sl,
                    timestamp=o.get("orderTime", ""),
                    peak_price=limit_price,
                )

                self.risk.register_trade(_new_trade)

                if self.state_mgr:
                    self.state_mgr.record_open(_new_trade)

                if DB_LOGGING_AVAILABLE:
                    log_trade(
                        symbol=sig.security_id,
                        side="BUY",
                        quantity=actual_qty,
                        price=limit_price,
                        status="POSITION_REGISTERED",
                        bot_name=self.BOT_NAME,
                    )
                    update_bot_status(
                        self.BOT_NAME,
                        "POSITION_OPENED",
                        f"BUY {actual_qty} {sig.security_id} @ {limit_price}",
                    )

            else:
                self.logger.warning(f"مرفوض: {status}")
        else:
            if DB_LOGGING_AVAILABLE:
                log_trade(
                    symbol=sig.security_id,
                    side="BUY",
                    quantity=quantity,
                    price=limit_price,
                    status="NO_ORDER_PARSED",
                    bot_name=self.BOT_NAME,
                )
                update_bot_status(
                    self.BOT_NAME,
                    "ERROR",
                    "Order response received but no order parsed",
                )

    # ── حلقة التشغيل الرئيسية ────────────────────────────────────

    def run(self):
        self.logger.info("=" * 60)
        self.logger.info(f"  {self.BOT_NAME} v7 | {self.SECURITY_ID}/{self.CURRENCY}")
        self.logger.info(f"  ML=تاريخي+حي | News={'✅' if self.news_analyzer else '❌'}")
        self.logger.info(f"  Trailing | DCA | SpreadFilter | StopLoss | HourlyScalp={'✅' if self.SCALP_ENABLED else '❌'}")
        self.logger.info("=" * 60)

        if not self.api.login():
            self.logger.error("فشل تسجيل الدخول.")
            sys.exit(1)

        self._load_existing_positions()

        if self.state_mgr:
            self.state_mgr.restore_to_risk(self.risk)
        if self.tg_ctrl:
            print("Telegram internal controller disabled")
        if self.reporter:
            self.reporter.start()

        self.running = True
        cycle = 0

        while self.running:
            cycle += 1
            self.logger.info(f"--- Cycle {cycle} ---")
            try:
                write_heartbeat(self.BOT_NAME, "RUNNING", f"Cycle {cycle}")
            except Exception as e:
                self.logger.warning(f"Heartbeat failed: {e}")
            try:
                market_data = self._fetch_market()
                if not market_data:
                    time.sleep(self.POLL_INTERVAL)
                    continue
                # تسجيل السعر الحالي
                try:
                    from parser import best_bid as _pb, best_ask as _pa
                    _bid = _pb(market_data, self.SECURITY_ID, self.CURRENCY)
                    _ask = _pa(market_data, self.SECURITY_ID, self.CURRENCY)
                    if _bid and _ask:
                        log_price_history(self.SECURITY_ID, (_bid+_ask)/2)
                except Exception as e:
                    self.logger.debug("Price logging failed: %s", e)

                balance = self._fetch_balance()
                usd = extract_usd_available(balance)

                # مراقبة المراكز الموجودة دائماً — حتى خارج ساعات التداول
                self._monitor_positions(market_data, balance)

                # فتح صفقات جديدة فقط في ساعات التداول
                if self.tg_ctrl and self.tg_ctrl.is_paused:
                    self.logger.info("⏸ البوت متوقف مؤقتاً بأمر تيليغرام")
                    time.sleep(15)
                    continue

                if not self._is_trading_hours():
                    self.logger.info("خارج ساعات التداول — مراقبة فقط، لا صفقات جديدة")
                    time.sleep(60)
                    continue

                # ── هدف 100$/يوم ──────────────────────────────────────
                from datetime import date as _date
                today_str = _date.today().isoformat()
                if self._last_alert_date != today_str:
                    self._alerted_profit_100 = False
                    self._alerted_loss_35    = False
                    self._last_alert_date    = today_str

                adj_threshold, pos_multiplier, alert_type = self._daily_target_adjustments()
                self.risk.config.confidence_threshold = adj_threshold

                if alert_type == "profit_100" and not self._alerted_profit_100:
                    msg = (f"🎯 {self.BOT_NAME}\n"
                           f"✅ هدف 100$/يوم تجاوزناه!\n"
                           f"PnL اليوم: ${self.risk.get_stats()['daily_pnl']:.2f}\n"
                           f"مستوى الثقة شُدِّد إلى 85%\n"
                           f"التداول مستمر بمعايير أصعب")
                    self.logger.info(msg)
                    self.tg(msg)
                    self._alerted_profit_100 = True

                elif alert_type == "loss_35" and not self._alerted_loss_35:
                    msg = (f"⚠️ {self.BOT_NAME}\n"
                           f"تنبيه خسارة!\n"
                           f"PnL اليوم: ${self.risk.get_stats()['daily_pnl']:.2f}\n"
                           f"تجاوزنا -35$ — البوت مستمر بحذر")
                    self.logger.info(msg)
                    self.tg(msg)
                    self._alerted_loss_35 = True

                if pos_multiplier > 1.0:
                    self.logger.info(f"💪 تعويض خسارة أمس — حجم الصفقة x{pos_multiplier}")

                if len(self.risk.open_trades) < self.MAX_OPEN_ORDERS:
                    bid = best_bid(market_data, self.SECURITY_ID, self.CURRENCY)
                    ask = best_ask(market_data, self.SECURITY_ID, self.CURRENCY)
                    if bid and ask and self._spread_acceptable(bid, ask):
                        sig = self.strategy.evaluate(
                            market_data, balance, self.SECURITY_ID, self.CURRENCY
                        )
                        # إصلاح C-03: فقط إشارات BUY تُنفَّذ كمراكز جديدة
                        if sig and sig.action == "B":
                            if self._passes_hourly_scalp_filter(sig, bid, ask):
                                self._execute(sig, balance)
                        elif sig and sig.action == "S":
                            self.logger.info(
                                f"إشارة بيع (السوق هبوطي) — لا مركز جديد | "
                                f"ثقة={sig.confidence:.0%}"
                            )

                stats = self.risk.get_stats()
                self.logger.info(
                    f"صفقات={stats['trades_today']} | "
                    f"PnL=${stats['daily_pnl']:.2f} | "
                    f"مفتوحة={stats['open_positions']} | "
                    f"USD=${usd:.2f}"
                )
            except Exception as e:
                self.logger.exception(f"خطأ: {e}")
                self.tg(f"{self.BOT_NAME}\nخطأ: {e}")
            time.sleep(self.POLL_INTERVAL)

        self.logger.info(f"{self.BOT_NAME} stopped.")
        self.tg(f"{self.BOT_NAME}\nBot stopped.")


def format_portfolio_snapshot(api):
    """
    يعرض الكاش والمخزون وقيمة المعادن.
    يحاول استخدام BullionVault API المتاح داخل المشروع.
    """
    try:
        data = None

        for method in ["get_portfolio", "portfolio", "get_balance", "get_account_balance", "get_holdings"]:
            if hasattr(api, method):
                data = getattr(api, method)()
                break

        if data is None:
            return "❌ لم أجد دالة portfolio/balance داخل API client."

        text = "💼 Portfolio Snapshot\n\n"

        if isinstance(data, dict):
            cash = data.get("cash") or data.get("available_cash") or data.get("balance") or data.get("cash_balance")
            holdings = data.get("holdings") or data.get("positions") or data.get("inventory") or data.get("assets")

            if cash is not None:
                text += f"💵 Cash: {cash}\n\n"

            if isinstance(holdings, dict):
                total_value = 0
                text += "📦 Metals Inventory:\n"
                for k, v in holdings.items():
                    if isinstance(v, dict):
                        qty = v.get("qty") or v.get("quantity") or v.get("kg") or v.get("amount")
                        value = v.get("value") or v.get("market_value") or v.get("usd_value")
                        total_value += float(value or 0)
                        text += f"- {k}: Qty={qty} | Value={value}\n"
                    else:
                        text += f"- {k}: {v}\n"

                text += f"\n📊 Metals Value: {total_value:.2f}\n"

            else:
                text += f"📦 Holdings: {holdings}\n"

            text += "\n✅ End of snapshot"
            return text

        return "💼 Portfolio Snapshot\n\n" + str(data)

    except Exception as e:
        return f"❌ Portfolio error: {e}"


# Manual portfolio command aliases:
# /portfolio
# /balance
# /inventory