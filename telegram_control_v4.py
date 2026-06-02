"""
Guardian Telegram Command Center v4 — Cockpit Pro
أوامر + Inline Keyboard + Dashboard + Manual Trading + User Permissions
تقارير: يومي تلقائي | تنبيه اقتراب TP/SL
"""
import os, time, json, threading, requests, math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
from api_client import BullionVaultAPI
from parser import parse_market, parse_balance, best_bid, best_ask

TOKEN   = os.getenv("TG_TOKEN_SILVER") or os.getenv("TG_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")      or os.getenv("CHAT_ID")
OFFSET_FILE   = Path("telegram_offset.txt")
CONTROL_FILE  = Path("/home/moatasim/fixed/control_state.json")
TRADE_LOG     = Path("/home/moatasim/fixed/trade_log.json")
STATE_FILES   = {
    "gold":      Path("/home/moatasim/fixed/state_AUXLN.json"),
    "silver":    Path("/home/moatasim/fixed/state_AGXLN.json"),
    "platinum":  Path("/home/moatasim/fixed/state_PTXLN.json"),
    "palladium": Path("/home/moatasim/fixed/state_PDXLN.json"),
}
PRICE_LOG_FILES = {
    "gold":      Path("/home/moatasim/fixed/price_log_AUXLN.json"),
    "silver":    Path("/home/moatasim/fixed/price_log_AGXLN.json"),
    "platinum":  Path("/home/moatasim/fixed/price_log_PTXLN.json"),
    "palladium": Path("/home/moatasim/fixed/price_log_PDXLN.json"),
}
METALS = {
    "gold":      {"name":"Gold",      "symbol":"AUXLN","currency":"USD", "emoji":"🥇"},
    "silver":    {"name":"Silver",    "symbol":"AGXLN","currency":"USD", "emoji":"🥈"},
    "platinum":  {"name":"Platinum",  "symbol":"PTXLN","currency":"USD", "emoji":"⚪"},
    "palladium": {"name":"Palladium", "symbol":"PDXLN","currency":"USD", "emoji":"🔘"},
}
DAILY_REPORT_HOUR_UTC = 21

# ── Guardian Cockpit v4 additions ─────────────────────────────────
AUTH_FILE     = Path("authorized_users.json")
PENDING_ORDER = Path("pending_order.json")
DEFAULT_QTYS  = {
    "gold":      [0.001, 0.002, 0.005, 0.010],
    "silver":    [0.001, 0.005, 0.010, 0.025, 0.050],
    "platinum":  [0.001, 0.005, 0.010, 0.025],
    "palladium": [0.001, 0.005, 0.010, 0.025, 0.050],
}
ROUND_TO = {"gold": 10, "silver": 10, "platinum": 10, "palladium": 10}

_api = BullionVaultAPI(os.getenv("BV_USERNAME",""), os.getenv("BV_PASSWORD",""))
_api_logged_in    = False
_price_cache:dict = {}
_price_cache_time:dict = {}
CACHE_TTL      = 30
_alerted_tp_sl:set = set()

# ── Login ──────────────────────────────────────────────────────────
def _ensure_login():
    global _api_logged_in
    if not _api_logged_in:
        _api_logged_in = _api.login()
    return _api_logged_in

# ── Live Price ─────────────────────────────────────────────────────
def fetch_live_price(symbol, currency="USD"):
    key = f"{symbol}_{currency}"
    now = time.time()
    if key in _price_cache and (now-_price_cache_time.get(key,0)) < CACHE_TTL:
        return _price_cache[key]
    try:
        if not _ensure_login(): return None
        root = _api.view_market(currency=currency,security_id=symbol,quantity=0.001,market_width=3)
        if root is None: return None
        md = parse_market(root)
        bid = best_bid(md,symbol,currency)
        ask = best_ask(md,symbol,currency)
        if bid and ask:
            mid = (bid+ask)/2
            _price_cache[key] = mid
            _price_cache_time[key] = now
            return mid
    except Exception as e:
        print(f"fetch error ({symbol}): {e}")
    return None

def get_metal_price(mk):
    m = METALS[mk]
    p = fetch_live_price(m["symbol"],m["currency"])
    if p: return p
    return _price_cache.get(f"{m['symbol']}_{m['currency']}", 0.0)

# ── State & Logs ───────────────────────────────────────────────────
def read_state(mk):
    f = STATE_FILES.get(mk)
    if f and f.exists():
        try: return json.loads(f.read_text(encoding="utf-8"))
        except: pass
    return {"trades":{},"daily":{},"total_pnl":0.0}

def read_control():
    try:
        if CONTROL_FILE.exists():
            return json.loads(CONTROL_FILE.read_text(encoding="utf-8"))
    except: pass
    return {"paused": False, "allow_buy": True, "allow_sell": True,
            "gold_enabled": False, "silver_enabled": True,
            "platinum_enabled": False, "palladium_enabled": True,
            "stop_loss_enabled": True, "emergency_close_all": False,
            "paused_after_close_all": True}

def write_control(data):
    CONTROL_FILE.write_text(json.dumps(data,indent=2),encoding="utf-8")

def read_price_log(mk, n=100):
    f = PRICE_LOG_FILES.get(mk)
    if f and f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return [d["price"] for d in data[-n:]]
        except: pass
    return []

def read_trade_log():
    if TRADE_LOG.exists():
        try: return json.loads(TRADE_LOG.read_text(encoding="utf-8"))
        except: pass
    return []

# ── Technical Indicators ───────────────────────────────────────────
def calc_rsi(prices, period=14):
    if len(prices) < period+1: return 50.0
    gains,losses = [],[]
    for i in range(1,len(prices)):
        d = prices[i]-prices[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    g = sum(gains[:period])/period
    l = sum(losses[:period])/period
    for i in range(period,len(gains)):
        g = (g*(period-1)+gains[i])/period
        l = (l*(period-1)+losses[i])/period
    rs = g/(l+1e-10)
    return round(100-100/(1+rs),1)

def calc_ema(prices, period):
    if not prices: return 0.0
    k = 2/(period+1)
    ema = prices[0]
    for p in prices[1:]: ema = p*k+ema*(1-k)
    return ema

def calc_macd(prices):
    if len(prices) < 26: return 0.0, "N/A"
    ema12 = calc_ema(prices[-12:],12) if len(prices)>=12 else prices[-1]
    ema26 = calc_ema(prices[-26:],26) if len(prices)>=26 else prices[-1]
    macd  = ema12-ema26
    trend = "صاعد ↑" if macd > 0 else "هابط ↓"
    return round(macd,2), trend

def calc_ma_trend(prices):
    if len(prices) < 20: return "NEUTRAL"
    fast = sum(prices[-5:])/5
    slow = sum(prices[-20:])/20
    if fast > slow*1.002: return "UP ↑"
    if fast < slow*0.998: return "DOWN ↓"
    return "NEUTRAL →"

def progress_bar(pct, width=10):
    filled = int(pct/100*width)
    return "█"*filled + "░"*(width-filled)

def sparkline(prices, width=20):
    if len(prices) < 2: return "لا بيانات كافية"
    p = prices[-width:] if len(prices) >= width else prices
    mn, mx = min(p), max(p)
    if mn == mx: return "─"*len(p)
    bars = " ▁▂▃▄▅▆▇█"
    return "".join(bars[int((v-mn)/(mx-mn)*8)] for v in p)

def signal_label(rsi, macd_val, trend):
    buy_score = 0
    if rsi < 40: buy_score += 2
    elif rsi < 50: buy_score += 1
    if macd_val > 0: buy_score += 2
    if "UP" in trend: buy_score += 1
    if buy_score >= 4: return "شراء قوي 🟢", buy_score*20
    if buy_score >= 2: return "شراء محتمل 🟡", buy_score*15
    if buy_score == 1: return "محايد ⚪", 40
    return "بيع محتمل 🔴", 20

# ── Technical Levels ───────────────────────────────────────────────
def technical_levels(price, metal_name):
    if price <= 0: return f"⚠️ {metal_name}: السعر غير متاح"
    return (
        f"📊 {metal_name} Technical Levels\n"
        f"Current:      {price:,.2f}\n"
        f"Support 1:    {price*0.995:,.2f}\n"
        f"Support 2:    {price*0.990:,.2f}\n"
        f"Resistance 1: {price*1.005:,.2f}\n"
        f"Resistance 2: {price*1.010:,.2f}\n"
        f"Buy Zone:     near {price*0.995:,.2f}\n"
        f"Sell/TP Zone: near {price*1.005:,.2f}"
    )

# ── Commands ───────────────────────────────────────────────────────
def cmd_status():
    ctrl  = read_control()
    state = "⏸ متوقف" if ctrl.get("paused") else "▶️ نشط"
    lines = [f"🤖 Guardian Status — {state}","━"*22]
    total_open = 0
    for mk,mv in METALS.items():
        st = read_state(mk)
        for oid,t in st.get("trades",{}).items():
            price  = get_metal_price(mk)
            entry  = t.get("entry_price",0)
            qty    = t.get("quantity",0)
            tp     = t.get("take_profit",0)
            sl     = t.get("stop_loss",0)
            peak   = t.get("peak_price",entry)
            pnl    = round((price-entry)*qty,2) if price and entry else 0
            pct    = round((price-entry)/entry*100,2) if entry else 0
            # مدة الصفقة
            try:
                ts  = datetime.fromisoformat(t.get("timestamp","").replace(" UTC",""))
                dur = datetime.utcnow()-ts
                dur_str = f"{dur.days}ي {dur.seconds//3600}س"
            except: dur_str = "N/A"
            # نسبة المسافة لـ TP/SL
            tp_pct = round((price-entry)/(tp-entry)*100,0) if tp>entry and price else 0
            sl_pct = round((entry-price)/(entry-sl)*100,0) if sl>0 and sl<entry and price else 0
            lines.append(
                f"📈 {mv['symbol']} | {qty}kg @ {entry:,.0f}\n"
                f"   حالي={price:,.0f} | قمة={peak:,.0f}\n"
                f"   PnL={pnl:+.2f}$ ({pct:+.2f}%)\n"
                f"   TP={tp:,.0f} [{tp_pct:.0f}%] | SL={sl:,.0f} [{sl_pct:.0f}%]\n"
                f"   مدة={dur_str} | DCA={t.get('dca_count',0)}"
            )
            total_open += 1
    if total_open == 0: lines.append("📭 لا توجد مراكز مفتوحة")

    # تحليل تقني لكل معدن
    lines.append("━"*22)
    for mk,mv in METALS.items():
        prices = read_price_log(mk,50)
        if len(prices) >= 20:
            rsi       = calc_rsi(prices)
            macd_val, macd_trend = calc_macd(prices)
            trend     = calc_ma_trend(prices)
            sig_label, sig_str = signal_label(rsi,macd_val,trend)
            lines.append(
                f"📊 {mv['name']}\n"
                f"   RSI={rsi} | MACD={macd_val} ({macd_trend})\n"
                f"   اتجاه={trend}\n"
                f"   إشارة={sig_label}"
            )
    lines.append("━"*22)
    today = datetime.now(timezone.utc).date().isoformat()
    all_pnl,all_trades,total_pnl = 0.0,0,0.0
    for mk in METALS:
        st = read_state(mk)
        d  = st.get("daily",{}).get(today,{})
        all_pnl    += d.get("pnl",0.0)
        all_trades += d.get("trades",0)
        total_pnl  += st.get("total_pnl",0.0)
    lines.append(f"📅 اليوم: {all_trades} صفقات | {all_pnl:+.2f}$")
    lines.append(f"📊 الإجمالي: {total_pnl:+.2f}$")
    return "\n".join(lines)

def cmd_chart(metal="all"):
    lines = ["📈 Price Sparkline (آخر 20 دورة)","━"*22]
    metals = METALS.items() if metal=="all" else [(metal,METALS[metal])]
    for mk,mv in metals:
        prices = read_price_log(mk,20)
        if len(prices) < 2:
            lines.append(f"{mv['name']}: لا بيانات كافية بعد")
            continue
        mn,mx = min(prices),max(prices)
        spark = sparkline(prices,20)
        change = prices[-1]-prices[0]
        icon   = "↑" if change>0 else "↓" if change<0 else "→"
        lines.append(
            f"{mv['name']} {icon}\n"
            f"{spark}\n"
            f"Low={mn:,.0f} → High={mx:,.0f}\n"
            f"حالي={prices[-1]:,.0f} ({change:+.0f})"
        )
    return "\n".join(lines)

def _open_positions_summary():
    """Return open positions and unrealized PnL from state files."""
    rows = []
    total_unrealized = 0.0
    total_open = 0
    for mk, mv in METALS.items():
        st = read_state(mk)
        trades = st.get("trades", {}) or {}
        for oid, t in trades.items():
            price = get_metal_price(mk)
            entry = float(t.get("entry_price", 0) or 0)
            qty = float(t.get("quantity", 0) or 0)
            pnl = round((price - entry) * qty, 2) if price and entry and qty else 0.0
            pct = round((price - entry) / entry * 100, 2) if price and entry else 0.0
            total_unrealized += pnl
            total_open += 1
            rows.append(
                f"• {mv['name']} | {qty:.3f}kg\n"
                f"  Entry={entry:,.2f} | Now={price:,.2f}\n"
                f"  Unrealized PnL={pnl:+.2f}$ ({pct:+.2f}%)"
            )
    return total_open, round(total_unrealized, 2), rows


def _state_pnl_summary():
    """Return realized PnL from state files even when trade_log.json is empty."""
    today = datetime.now(timezone.utc).date().isoformat()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()

    result = {
        "today_pnl": 0.0, "today_trades": 0,
        "week_pnl": 0.0, "week_trades": 0,
        "month_pnl": 0.0, "month_trades": 0,
        "total_pnl": 0.0, "open_positions": 0,
    }
    for mk in METALS:
        st = read_state(mk)
        result["total_pnl"] += float(st.get("total_pnl", 0.0) or 0.0)
        result["open_positions"] += len(st.get("trades", {}) or {})
        for day, d in (st.get("daily", {}) or {}).items():
            pnl = float(d.get("pnl", 0.0) or 0.0)
            tr = int(d.get("trades", 0) or 0)
            if day == today:
                result["today_pnl"] += pnl
                result["today_trades"] += tr
            if day >= week_ago:
                result["week_pnl"] += pnl
                result["week_trades"] += tr
            if day >= month_ago:
                result["month_pnl"] += pnl
                result["month_trades"] += tr
    for k in list(result):
        if k.endswith("_pnl"):
            result[k] = round(result[k], 2)
    return result


def cmd_report():
    logs = read_trade_log()
    today = datetime.now(timezone.utc).date().isoformat()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()

    def _pnl_value(t):
        try:
            return float(t.get("pnl", 0) or 0)
        except Exception:
            return 0.0

    def stats(trades):
        clean = [t for t in trades if isinstance(t, dict)]
        if not clean:
            return None
        wins = [t for t in clean if _pnl_value(t) > 0]
        losses = [t for t in clean if _pnl_value(t) <= 0]
        total = sum(_pnl_value(t) for t in clean)
        best = max(clean, key=_pnl_value)
        worst = min(clean, key=_pnl_value)
        wr = round(len(wins) / len(clean) * 100, 1) if clean else 0
        avg_w = round(sum(_pnl_value(t) for t in wins) / len(wins), 2) if wins else 0
        avg_l = round(sum(_pnl_value(t) for t in losses) / len(losses), 2) if losses else 0
        return {
            "n": len(clean), "wins": len(wins), "losses": len(losses),
            "wr": wr, "total": round(total, 2), "best": best, "worst": worst,
            "avg_w": avg_w, "avg_l": avg_l,
        }

    today_trades = [t for t in logs if str(t.get("timestamp", ""))[:10] == today]
    week_trades = [t for t in logs if str(t.get("timestamp", ""))[:10] >= week_ago]
    month_trades = [t for t in logs if str(t.get("timestamp", ""))[:10] >= month_ago]
    all_trades = logs

    def fmt(s, label):
        if not s:
            return f"{label}: 0.00$ | 0 صفقة"
        bar = progress_bar(s["wr"], 10)
        best_symbol = s["best"].get("symbol", s["best"].get("security_id", "N/A"))
        worst_symbol = s["worst"].get("symbol", s["worst"].get("security_id", "N/A"))
        return (
            f"{label}: {s['total']:+.2f}$ | {s['n']} صفقة\n"
            f"   Win Rate: {bar} {s['wr']}% ({s['wins']}W/{s['losses']}L)\n"
            f"   متوسط ربح={s['avg_w']:+.2f}$ | متوسط خسارة={s['avg_l']:+.2f}$\n"
            f"   أفضل={_pnl_value(s['best']):+.2f}$ ({best_symbol})\n"
            f"   أسوأ={_pnl_value(s['worst']):+.2f}$ ({worst_symbol})"
        )

    state_sum = _state_pnl_summary()
    open_count, unrealized_pnl, open_rows = _open_positions_summary()

    lines = [
        "📊 Performance Report",
        "━━━━━━━━━━━━━━━━━━━━━━",
        fmt(stats(today_trades), "📅 اليوم"),
        fmt(stats(week_trades), "📆 الأسبوع"),
        fmt(stats(month_trades), "🗓 الشهر"),
        fmt(stats(all_trades), "📈 الإجمالي"),
        "━━━━━━━━━━━━━━━━━━━━━━",
        "📌 State Summary",
        f"Today Realized: {state_sum['today_pnl']:+.2f}$ | {state_sum['today_trades']} صفقة",
        f"Week Realized: {state_sum['week_pnl']:+.2f}$ | {state_sum['week_trades']} صفقة",
        f"Month Realized: {state_sum['month_pnl']:+.2f}$ | {state_sum['month_trades']} صفقة",
        f"Total Realized: {state_sum['total_pnl']:+.2f}$",
        f"Open Positions: {open_count}",
        f"Unrealized PnL: {unrealized_pnl:+.2f}$",
    ]

    if open_rows:
        lines += ["━━━━━━━━━━━━━━━━━━━━━━", "📈 Open Positions"] + open_rows[:6]
    elif not logs:
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━",
            "ℹ️ لا توجد صفقات مغلقة في trade_log.json حتى الآن.",
            "هذا طبيعي إذا لم تُغلق أي صفقة بعد أو إذا كان السجل جديداً.",
        ]

    return "\n".join(lines)

def cmd_pnl():
    today    = datetime.now(timezone.utc).date().isoformat()
    week_ago = (datetime.now(timezone.utc)-timedelta(days=7)).date().isoformat()
    lines    = ["📊 PnL Report","━"*22]
    g_today,g_week,g_total,g_trades = 0.0,0.0,0.0,0
    for mk,mv in METALS.items():
        st     = read_state(mk)
        d      = st.get("daily",{}).get(today,{})
        p_today= d.get("pnl",0.0); tr = d.get("trades",0)
        p_week = sum(v.get("pnl",0) for k,v in st.get("daily",{}).items() if k>=week_ago)
        total  = st.get("total_pnl",0.0)
        lines.append(f"{mv['name']}:\n  اليوم={p_today:+.2f}$ ({tr}صف) | أسبوع={p_week:+.2f}$ | كلي={total:+.2f}$")
        g_today+=p_today; g_week+=p_week; g_total+=total; g_trades+=tr
    lines += ["━"*22,
              f"اليوم:   {g_today:+.2f}$ ({g_trades} صفقات)",
              f"الأسبوع: {g_week:+.2f}$",
              f"الكلي:   {g_total:+.2f}$"]
    return "\n".join(lines)

def cmd_balance():
    if not _ensure_login(): return "❌ فشل الاتصال"
    try:
        root = _api.view_balance(simple=True)
        if root is None: return "❌ لم يتم جلب الرصيد"
        bal     = parse_balance(root)
        usd     = bal.get("USD",{})
        usd_val = usd.get("available",0) if isinstance(usd,dict) else float(usd or 0)
        lines   = ["💼 BullionVault Balance","━"*22,f"💵 USD: {usd_val:,.2f}$"]
        for mk,mv in METALS.items():
            qty   = float(bal.get(mv["symbol"],{}).get("available",0) or 0)
            price = get_metal_price(mk)
            val   = qty*price if price else 0
            lines.append(f"{mv['name']}: {qty:.3f}kg ≈ {val:,.2f}$")
        total_val = sum(
            float(bal.get(mv["symbol"],{}).get("available",0) or 0)*get_metal_price(mk)
            for mk,mv in METALS.items() if get_metal_price(mk)
        )
        lines.append(f"━"*22+f"\nإجمالي المحفظة: {usd_val+total_val:,.2f}$")
        return "\n".join(lines)
    except Exception as e: return f"❌ Balance error: {e}"

def cmd_pause():
    ctrl=read_control(); ctrl["paused"]=True; write_control(ctrl)
    return "⏸ تم إيقاف التداول\nلا صفقات جديدة حتى /resume"

def cmd_resume():
    ctrl=read_control(); ctrl["paused"]=False; write_control(ctrl)
    return "▶️ تم استئناف التداول"

def cmd_close(metal):
    ctrl=read_control()
    if metal == "all":
        ctrl["emergency_close_all"] = True
    elif metal in METALS:
        ctrl[f"close_{metal}"] = True
    else:
        return "❓ حدد: /close gold|silver|platinum|palladium|all"
    write_control(ctrl)
    return f"🔴 إغلاق {metal}..."

def cmd_toggle_metal(metal: str, enabled: bool):
    if metal not in METALS:
        return "❓ معدن غير معروف."
    ctrl = read_control()
    ctrl[f"{metal}_enabled"] = bool(enabled)
    write_control(ctrl)
    name = METALS[metal]["name"]
    state = "✅ enabled" if enabled else "⏸ disabled"
    note = ""
    if metal in ("gold", "platinum") and enabled:
        note = (
            "\n\n⚠️ ملاحظة: هذا يفعّل المعدن داخل control_state.json. "
            "لتشغيل البوت الآلي لهذا المعدن يجب أيضاً تفعيله في run_all_bots.py ثم إعادة تشغيل Always-on task."
        )
    return f"{name} is now {state}.{note}"


# ── Permissions ───────────────────────────────────────────────────
def _int_or_none(v):
    try:
        return int(v)
    except Exception:
        return None

def _default_auth():
    owner = _int_or_none(os.getenv("TG_OWNER_ID") or os.getenv("TG_CHAT_ID") or os.getenv("CHAT_ID"))
    data = {"owners": [], "admins": [], "viewers": []}
    if owner is not None:
        data["owners"].append(owner)
    return data

def ensure_auth_file():
    if AUTH_FILE.exists():
        return
    try:
        AUTH_FILE.write_text(json.dumps(_default_auth(), indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"auth file create failed: {e}")

def read_auth():
    ensure_auth_file()
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        return {
            "owners":  [int(x) for x in data.get("owners", [])],
            "admins":  [int(x) for x in data.get("admins", [])],
            "viewers": [int(x) for x in data.get("viewers", [])],
        }
    except Exception:
        return _default_auth()

def role_of(user_id: int) -> str:
    auth = read_auth()
    if user_id in auth.get("owners", []):  return "owner"
    if user_id in auth.get("admins", []):  return "admin"
    if user_id in auth.get("viewers", []): return "viewer"
    return "none"

def is_allowed(user_id: int, need: str = "viewer") -> bool:
    rank = {"none": 0, "viewer": 1, "admin": 2, "owner": 3}
    return rank.get(role_of(user_id), 0) >= rank.get(need, 1)

def permission_denied(user_id: int) -> str:
    return (
        "⛔ غير مصرح لك باستخدام Guardian Cockpit.\n"
        f"User ID: {user_id}\n\n"
        "أضف هذا الرقم إلى authorized_users.json داخل owners أو admins."
    )

# ── Inline Keyboards ───────────────────────────────────────────────
def kb(rows):
    return {"inline_keyboard": rows}

def _metal_enabled(metal: str) -> bool:
    return bool(read_control().get(f"{metal}_enabled", True))

def dashboard_keyboard():
    ctrl = read_control()
    metal_rows = []
    current = []
    for mk, mv in METALS.items():
        enabled = ctrl.get(f"{mk}_enabled", True)
        icon = "✅" if enabled else "⏸"
        current.append({"text": f"{mv.get('emoji','')} {mv['name']} {icon}", "callback_data": f"metal_{mk}"})
        if len(current) == 2:
            metal_rows.append(current)
            current = []
    if current:
        metal_rows.append(current)
    return kb([
        [{"text":"💰 Balance", "callback_data":"balance"}, {"text":"📈 Positions", "callback_data":"status"}],
        [{"text":"📡 Signals", "callback_data":"signal_all"}, {"text":"📊 Report", "callback_data":"report"}],
        *metal_rows,
        [{"text":"🟢 Resume", "callback_data":"resume"}, {"text":"⏸ Pause", "callback_data":"pause"}],
        [{"text":"🔴 Close All", "callback_data":"close_all"}],
    ])

def metal_keyboard(metal):
    name = METALS[metal]["name"]
    enabled = _metal_enabled(metal)
    toggle_text = f"⏸ Disable {name}" if enabled else f"▶ Enable {name}"
    toggle_cb = f"disable_{metal}" if enabled else f"enable_{metal}"
    return kb([
        [{"text":f"💰 {name} Price", "callback_data":f"price_{metal}"}, {"text":f"📡 {name} Signal", "callback_data":f"signal_{metal}"}],
        [{"text":f"🟢 Buy {name}", "callback_data":f"trade_buy_{metal}"}, {"text":f"🔴 Sell {name}", "callback_data":f"trade_sell_{metal}"}],
        [{"text":f"📊 {name} Levels", "callback_data":f"levels_{metal}"}],
        [{"text":toggle_text, "callback_data":toggle_cb}],
        [{"text":"⬅ Dashboard", "callback_data":"dashboard"}],
    ])

def qty_keyboard(side, metal):
    rows = []
    vals = DEFAULT_QTYS.get(metal, [0.001, 0.005, 0.01])
    for i in range(0, len(vals), 3):
        rows.append([
            {"text":f"{q:g} kg", "callback_data":f"qty_{side}_{metal}_{q:g}"}
            for q in vals[i:i+3]
        ])
    rows.append([{"text":"⬅ رجوع", "callback_data":f"metal_{metal}"}])
    return kb(rows)

def confirm_keyboard(order_id):
    return kb([
        [{"text":"✅ Confirm Execute", "callback_data":f"confirm_{order_id}"}],
        [{"text":"❌ Cancel", "callback_data":f"cancel_{order_id}"}],
    ])

# ── Dashboard ──────────────────────────────────────────────────────
def cmd_dashboard():
    ctrl = read_control()
    status = "⏸ PAUSED" if ctrl.get("paused") else "▶ ACTIVE"
    lines = ["🤖 Guardian Trading Cockpit v4", "━"*28, f"Status: {status}"]
    today = datetime.now(timezone.utc).date().isoformat()
    total_open = 0
    day_pnl = 0.0
    for mk, mv in METALS.items():
        st = read_state(mk)
        price = get_metal_price(mk)
        trades = st.get("trades", {})
        d = st.get("daily", {}).get(today, {})
        total_open += len(trades)
        day_pnl += float(d.get("pnl", 0.0) or 0.0)
        enabled = ctrl.get(f"{mk}_enabled", True)
        icon = "✅ ON" if enabled else "⏸ OFF"
        emoji = mv.get("emoji", "")
        lines.append(f"{emoji} {mv['name']}: {price:,.2f} | {icon}" if price else f"{emoji} {mv['name']}: N/A | {icon}")
    lines += ["━"*28, f"Open Positions: {total_open}", f"Today PnL: {day_pnl:+.2f}$", "اختر من الأزرار أدناه 👇"]
    return "\n".join(lines)

# ── Manual Trading ─────────────────────────────────────────────────
def _round_limit(metal, price):
    n = max(1, int(ROUND_TO.get(metal, 1)))
    return int(round(float(price) / n) * n)

def _read_pending():
    try:
        if PENDING_ORDER.exists():
            return json.loads(PENDING_ORDER.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _write_pending(data):
    PENDING_ORDER.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _clear_pending(order_id=None):
    if not PENDING_ORDER.exists():
        return
    if not order_id:
        PENDING_ORDER.unlink(missing_ok=True)
        return
    data = _read_pending()
    if data.get("order_id") == order_id:
        PENDING_ORDER.unlink(missing_ok=True)

def build_order_preview(side: str, metal: str, qty: float, user_id: int):
    if metal not in METALS:
        return None, "❓ معدن غير معروف. استخدم gold أو silver أو platinum أو palladium."
    if qty <= 0:
        return None, "❓ الكمية يجب أن تكون أكبر من صفر."
    if not _ensure_login():
        return None, "❌ فشل تسجيل الدخول إلى BullionVault."

    mv = METALS[metal]
    root = _api.view_market(currency=mv["currency"], security_id=mv["symbol"], quantity=max(qty, 0.001), market_width=5)
    if root is None:
        return None, "❌ لم يتم جلب السوق."
    md = parse_market(root)
    bid = best_bid(md, mv["symbol"], mv["currency"])
    ask = best_ask(md, mv["symbol"], mv["currency"])
    if not bid or not ask:
        return None, "❌ لا يوجد bid/ask صالح حالياً."

    price = ask if side == "buy" else bid
    limit = _round_limit(metal, price)
    spread_pct = (ask - bid) / bid if bid else 0.0
    value = qty * limit
    oid = f"M{int(time.time())}{user_id % 10000}"
    order = {
        "order_id": oid,
        "side": side,
        "action": "B" if side == "buy" else "S",
        "metal": metal,
        "symbol": mv["symbol"],
        "currency": mv["currency"],
        "qty": round(float(qty), 3),
        "limit": int(limit),
        "bid": bid,
        "ask": ask,
        "spread_pct": spread_pct,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_pending(order)
    txt = (
        "🧾 Manual Order Preview\n"
        + "━"*24 + "\n"
        + f"Metal: {mv['name']} ({mv['symbol']})\n"
        + f"Action: {'BUY 🟢' if side == 'buy' else 'SELL 🔴'}\n"
        + f"Qty: {qty:.3f} kg\n"
        + f"Bid: {bid:,.2f}\n"
        + f"Ask: {ask:,.2f}\n"
        + f"Limit: {limit:,.0f}\n"
        + f"Estimated Value: ${value:,.2f}\n"
        + f"Spread: {spread_pct:.3%}\n"
        + "━"*24 + "\n"
        + "⚠️ لن يتم التنفيذ إلا بعد الضغط على Confirm."
    )
    return order, txt

def execute_pending(order_id: str, user_id: int):
    order = _read_pending()
    if not order or order.get("order_id") != order_id:
        return "❌ لا يوجد أمر معلق مطابق أو انتهت صلاحيته."
    if int(order.get("user_id", 0)) != int(user_id) and not is_allowed(user_id, "owner"):
        return "⛔ هذا الأمر أنشأه مستخدم آخر."
    age = time.time() - datetime.fromisoformat(order["created_at"]).timestamp()
    if age > 180:
        _clear_pending(order_id)
        return "⏱ انتهت صلاحية الأمر المعلق. أنشئ Preview جديد."
    if not _ensure_login():
        return "❌ فشل تسجيل الدخول إلى BullionVault."
    root = _api.place_order(
        action=order["action"],
        security_id=order["symbol"],
        currency=order["currency"],
        quantity=float(order["qty"]),
        limit=int(order["limit"]),
        client_ref=f"TG_{order['order_id']}",
    )
    _clear_pending(order_id)
    if root is None:
        return "❌ فشل إرسال الأمر إلى BullionVault. راجع اللوج."
    return (
        "✅ تم إرسال الأمر إلى BullionVault\n"
        + "━"*24 + "\n"
        + f"Action: {order['action']}\n"
        + f"Symbol: {order['symbol']}\n"
        + f"Qty: {float(order['qty']):.3f} kg\n"
        + f"Limit: {int(order['limit']):,.0f}\n"
        + f"ClientRef: TG_{order['order_id']}"
    )

def cmd_manual_trade(parts, user_id: int):
    if len(parts) < 3:
        return "صيغة الأمر:\n/buy silver 0.01\n/sell palladium 0.01", None
    side = parts[0].replace("/", "")
    metal = parts[1]
    if metal in ("aux", "auxln", "xau", "gold"): metal = "gold"
    if metal in ("agx", "agxln", "xag", "silver"): metal = "silver"
    if metal in ("ptx", "ptxln", "xpt", "platinum"): metal = "platinum"
    if metal in ("pdx", "pdxln", "xpd", "palladium"): metal = "palladium"
    try:
        qty = float(parts[2])
    except Exception:
        return "❓ الكمية غير صحيحة.", None
    order, txt = build_order_preview(side, metal, qty, user_id)
    if not order:
        return txt, None
    return txt, confirm_keyboard(order["order_id"])

# ── Callback Router ────────────────────────────────────────────────
def handle_callback(data: str, user_id: int):
    if data == "dashboard":
        return cmd_dashboard(), dashboard_keyboard()
    if data == "status":
        return cmd_status(), dashboard_keyboard()
    if data == "balance":
        return cmd_balance(), dashboard_keyboard()
    if data == "report":
        return cmd_report(), dashboard_keyboard()
    if data == "pause":
        if not is_allowed(user_id, "admin"): return permission_denied(user_id), None
        return cmd_pause(), dashboard_keyboard()
    if data == "resume":
        if not is_allowed(user_id, "admin"): return permission_denied(user_id), None
        return cmd_resume(), dashboard_keyboard()
    if data == "close_all":
        if not is_allowed(user_id, "admin"): return permission_denied(user_id), None
        return cmd_close("all"), dashboard_keyboard()

    if data.startswith("enable_"):
        if not is_allowed(user_id, "admin"): return permission_denied(user_id), None
        metal = data.split("_", 1)[1]
        return cmd_toggle_metal(metal, True), metal_keyboard(metal) if metal in METALS else dashboard_keyboard()

    if data.startswith("disable_"):
        if not is_allowed(user_id, "admin"): return permission_denied(user_id), None
        metal = data.split("_", 1)[1]
        return cmd_toggle_metal(metal, False), metal_keyboard(metal) if metal in METALS else dashboard_keyboard()

    if data.startswith("metal_"):
        metal = data.split("_", 1)[1]
        if metal in METALS:
            enabled = "ON ✅" if _metal_enabled(metal) else "OFF ⏸"
            return f"{METALS[metal]['name']} Control Panel\nStatus: {enabled}", metal_keyboard(metal)

    if data.startswith("price_"):
        metal = data.split("_", 1)[1]
        m = METALS[metal]; p = get_metal_price(metal)
        return (f"💰 {m['name']} Live Price\n{m['symbol']} | {p:,.2f}" if p else "⚠️ N/A"), metal_keyboard(metal)

    if data.startswith("levels_"):
        metal = data.split("_", 1)[1]
        return technical_levels(get_metal_price(metal), METALS[metal]["name"]), metal_keyboard(metal)

    if data.startswith("signal_"):
        metal = data.split("_", 1)[1]
        if metal == "all":
            return handle_command("/signal", user_id)[0], dashboard_keyboard()
        return handle_command(f"/signal {metal}", user_id)[0], metal_keyboard(metal)

    if data.startswith("trade_"):
        if not is_allowed(user_id, "admin"): return permission_denied(user_id), None
        _, side, metal = data.split("_", 2)
        return f"اختر كمية {METALS[metal]['name']} للـ {side.upper()}", qty_keyboard(side, metal)

    if data.startswith("qty_"):
        if not is_allowed(user_id, "admin"): return permission_denied(user_id), None
        _, side, metal, qty_s = data.split("_", 3)
        order, txt = build_order_preview(side, metal, float(qty_s), user_id)
        return txt, confirm_keyboard(order["order_id"]) if order else None

    if data.startswith("confirm_"):
        if not is_allowed(user_id, "admin"): return permission_denied(user_id), None
        oid = data.split("_", 1)[1]
        return execute_pending(oid, user_id), dashboard_keyboard()

    if data.startswith("cancel_"):
        oid = data.split("_", 1)[1]
        _clear_pending(oid)
        return "❌ تم إلغاء الأمر المعلق.", dashboard_keyboard()

    return "❓ زر غير معروف", dashboard_keyboard()

# ── Help ───────────────────────────────────────────────────────────
HELP_TEXT = """🤖 Guardian Trading Cockpit v4
━━━━━━━━━━━━━━━━━━━━━━
/start أو /menu — لوحة الأزرار

📈 الأسعار والتحليل:
/price  [gold|silver|platinum|palladium|all]
/levels [gold|silver|platinum|palladium|all]
/signal [gold|silver|platinum|palladium|all]
/chart  [gold|silver|platinum|palladium|all]

📊 التقارير:
/status  — مراكز + تحليل تقني
/pnl     — أرباح يوم/أسبوع/كلي
/report  — إحصائيات أداء كاملة
/balance — رصيد المحفظة

⚙️ التحكم:
/pause   — إيقاف التداول
/resume  — استئناف التداول
/close   [gold|silver|platinum|palladium|all]

🧾 التداول اليدوي:
/buy  gold 0.001
/buy  silver 0.01
/sell platinum 0.005
/sell palladium 0.01
ثم Confirm من الزر.

🔐 الصلاحيات من authorized_users.json
━━━━━━━━━━━━━━━━━━━━━━"""

# ── Handler ────────────────────────────────────────────────────────
def handle_command(text, user_id: int = 0):
    parts = text.strip().lower().split()
    if not parts:
        return "", None
    cmd   = parts[0]
    metal = "all"
    if len(parts)>=2:
        if parts[1] in ("gold", "aux", "auxln", "xau"): metal = "gold"
        elif parts[1] in ("silver", "agx", "agxln", "xag"): metal = "silver"
        elif parts[1] in ("platinum", "ptx", "ptxln", "xpt"): metal = "platinum"
        elif parts[1] in ("palladium", "pdx", "pdxln", "xpd"): metal = "palladium"

    if cmd in ("/start", "/menu", "/dashboard"):
        return cmd_dashboard(), dashboard_keyboard()
    if cmd=="/help":    return HELP_TEXT, dashboard_keyboard()
    if cmd=="/status":  return cmd_status(), dashboard_keyboard()
    if cmd=="/pnl":     return cmd_pnl(), dashboard_keyboard()
    if cmd=="/balance": return cmd_balance(), dashboard_keyboard()
    if cmd=="/report":  return cmd_report(), dashboard_keyboard()
    if cmd=="/chart":   return cmd_chart(metal), dashboard_keyboard()

    if cmd in ("/pause", "/resume", "/close", "/buy", "/sell"):
        if not is_allowed(user_id, "admin"):
            return permission_denied(user_id), None

    if cmd=="/pause":   return cmd_pause(), dashboard_keyboard()
    if cmd=="/resume":  return cmd_resume(), dashboard_keyboard()
    if cmd=="/close":   return cmd_close(metal), dashboard_keyboard()
    if cmd in ("/buy", "/sell"):
        return cmd_manual_trade(parts, user_id)

    if cmd=="/price":
        if metal=="all":
            msg="💰 Live Prices\n"+"━"*16+"\n"
            for k,v in METALS.items():
                p=get_metal_price(k)
                msg+=f"{v['name']}: {p:,.2f}\n" if p else f"{v['name']}: N/A\n"
            return msg, dashboard_keyboard()
        m=METALS[metal]; p=get_metal_price(metal)
        return (f"💰 {m['name']} Live Price\n{m['symbol']} | {p:,.2f}" if p else f"⚠️ N/A"), metal_keyboard(metal)

    if cmd in ("/levels","/support","/resistance"):
        if metal=="all":
            return "\n\n".join(technical_levels(get_metal_price(k),v["name"]) for k,v in METALS.items()), dashboard_keyboard()
        return technical_levels(get_metal_price(metal),METALS[metal]["name"]), metal_keyboard(metal)

    if cmd=="/signal":
        lines=[]
        metals = METALS.items() if metal=="all" else [(metal,METALS[metal])]
        for mk,mv in metals:
            price  = get_metal_price(mk)
            prices = read_price_log(mk,50)
            if len(prices)>=20:
                rsi          = calc_rsi(prices)
                macd_val, mt = calc_macd(prices)
                trend        = calc_ma_trend(prices)
                sig,sig_pct  = signal_label(rsi,macd_val,trend)
                bar          = progress_bar(sig_pct,10)
                lines.append(
                    f"📡 {mv['name']} Signal\n"
                    f"   سعر={price:,.2f}\n"
                    f"   RSI={rsi} | MACD={macd_val}({mt})\n"
                    f"   اتجاه={trend}\n"
                    f"   إشارة={sig}\n"
                    f"   قوة={bar} {sig_pct}%\n\n"
                    +technical_levels(price,mv["name"])
                )
            else:
                lines.append(f"📡 {mv['name']}: يحتاج بيانات أكثر\n"+technical_levels(price,mv["name"]))
        return "\n\n".join(lines), dashboard_keyboard() if metal=="all" else metal_keyboard(metal)

    return "❓ أمر غير معروف — /help", dashboard_keyboard()

# ── Background Threads ─────────────────────────────────────────────
def _daily_report_thread():
    reported = None
    while True:
        now = datetime.now(timezone.utc)
        if now.hour==DAILY_REPORT_HOUR_UTC and now.date().isoformat()!=reported:
            try:
                report = f"📅 Daily Report — {now.date()}\n"+"━"*22+"\n"
                today  = now.date().isoformat()
                g_pnl,g_trades = 0.0,0
                for mk,mv in METALS.items():
                    st = read_state(mk)
                    d  = st.get("daily",{}).get(today,{})
                    p=d.get("pnl",0.0); t=d.get("trades",0)
                    report+=f"{mv['name']}: {p:+.2f}$ ({t} صفقات)\n"
                    g_pnl+=p; g_trades+=t
                logs  = read_trade_log()
                today_logs = [x for x in logs if x.get("timestamp","")[:10]==today]
                wins  = len([x for x in today_logs if x["pnl"]>0])
                wr    = round(wins/len(today_logs)*100,1) if today_logs else 0
                report+="━"*22+"\n"
                report+=f"المجموع: {g_pnl:+.2f}$ ({g_trades} صفقات)\n"
                report+=f"Win Rate: {progress_bar(wr,10)} {wr}%\n"
                try:
                    root=_api.view_balance(simple=True)
                    bal=parse_balance(root) if root else {}
                    usd=bal.get("USD",{})
                    usd_val=usd.get("available",0) if isinstance(usd,dict) else float(usd or 0)
                    report+=f"💵 رصيد: {usd_val:,.2f}$"
                except: pass
                tg_send(report)
                reported = today
            except Exception as e: print(f"Daily report error: {e}")
        time.sleep(60)

def _proximity_alert_thread():
    while True:
        try:
            for mk,mv in METALS.items():
                st = read_state(mk)
                for oid,t in st.get("trades",{}).items():
                    price = get_metal_price(mk)
                    entry = t.get("entry_price",0)
                    tp    = t.get("take_profit",0)
                    sl    = t.get("stop_loss",0)
                    if not price or not entry: continue
                    if tp>entry:
                        dist  = tp-entry
                        prog  = (price-entry)/dist if dist else 0
                        key   = f"tp_{oid}"
                        if prog>=0.80 and key not in _alerted_tp_sl:
                            tg_send(f"⚡ {mv['symbol']} اقترب من TP\nحالي={price:,.2f} | TP={tp:,.2f}\n{progress_bar(prog*100,10)} {prog:.0%}")
                            _alerted_tp_sl.add(key)
                        elif prog<0.60: _alerted_tp_sl.discard(key)
                    if sl>0 and sl<entry:
                        dist  = entry-sl
                        prog  = (entry-price)/dist if dist else 0
                        key   = f"sl_{oid}"
                        if prog>=0.80 and key not in _alerted_tp_sl:
                            tg_send(f"⚠️ {mv['symbol']} اقترب من SL\nحالي={price:,.2f} | SL={sl:,.2f}\n{progress_bar(prog*100,10)} {prog:.0%}")
                            _alerted_tp_sl.add(key)
                        elif prog<0.60: _alerted_tp_sl.discard(key)
        except Exception as e: print(f"Proximity error: {e}")
        time.sleep(60)

# ── Telegram Core ──────────────────────────────────────────────────
def tg_send(msg, reply_markup=None, chat_id=None):
    try:
        data = {"chat_id": chat_id or CHAT_ID, "text": msg}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, timeout=20)
    except Exception as e: print(f"tg_send: {e}")

def tg_edit(chat_id, message_id, msg, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "message_id": message_id, "text": msg}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", data=data, timeout=20)
        if r.status_code != 200 and "message is not modified" not in r.text.lower():
            print(f"tg_edit HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e: print(f"tg_edit: {e}")

def answer_callback(callback_id, text=""):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery", data={"callback_query_id": callback_id, "text": text}, timeout=10)
    except Exception:
        pass

def load_offset():
    if not OFFSET_FILE.exists(): return 0
    try: return int(OFFSET_FILE.read_text().strip())
    except: return 0

def save_offset(v): OFFSET_FILE.write_text(str(v))

def drop_pending_updates():
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", data={"drop_pending_updates":True},timeout=10)
    except: pass

def steal_session():
    print("Stealing Telegram session...")
    for attempt in range(60):
        try:
            r=requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", params={"timeout":0,"offset":-1},timeout=10)
            if r.status_code==200:
                print(f"✅ Session stolen after {attempt+1} attempts")
                return True
            if r.status_code==409: time.sleep(1); continue
        except: time.sleep(1)
    return False

def get_updates(offset):
    r=requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", params={"timeout":30,"offset":offset},timeout=40)
    if r.status_code==409: raise requests.HTTPError("409 Conflict")
    r.raise_for_status()
    return r.json()["result"]

# ── Main ───────────────────────────────────────────────────────────
def main():
    if not TOKEN: raise RuntimeError("Telegram token missing")
    ensure_auth_file()
    print("Logging in to BullionVault...")
    if not _ensure_login(): print("⚠️ BullionVault login failed")
    drop_pending_updates()
    steal_session()
    threading.Thread(target=_daily_report_thread,   daemon=True).start()
    threading.Thread(target=_proximity_alert_thread, daemon=True).start()
    tg_send("✅ Guardian Trading Cockpit v4 started\n/start لفتح لوحة الأزرار", dashboard_keyboard())
    offset=load_offset(); retry_delay=1
    while True:
        try:
            updates=get_updates(offset); retry_delay=1
            for u in updates:
                offset=u["update_id"]+1; save_offset(offset)

                cb = u.get("callback_query")
                if cb:
                    user_id = int(cb.get("from", {}).get("id", 0) or 0)
                    chat_id = cb.get("message", {}).get("chat", {}).get("id", CHAT_ID)
                    msg_id  = cb.get("message", {}).get("message_id")
                    data    = cb.get("data", "")
                    answer_callback(cb.get("id"))
                    if not is_allowed(user_id, "viewer"):
                        tg_send(permission_denied(user_id), chat_id=chat_id)
                        continue
                    txt, markup = handle_callback(data, user_id)
                    if msg_id:
                        tg_edit(chat_id, msg_id, txt, markup)
                    else:
                        tg_send(txt, markup, chat_id=chat_id)
                    continue

                msg=u.get("message")
                if not msg: continue
                text=msg.get("text","").strip()
                if not text.startswith("/"): continue
                user_id = int(msg.get("from", {}).get("id", 0) or 0)
                chat_id = msg.get("chat", {}).get("id", CHAT_ID)
                if not is_allowed(user_id, "viewer"):
                    tg_send(permission_denied(user_id), chat_id=chat_id)
                    continue
                reply, markup = handle_command(text, user_id)
                tg_send(reply, markup, chat_id=chat_id)
        except requests.HTTPError as e:
            if "409" in str(e):
                retry_delay=min(retry_delay*2,60)
                print(f"409 retry in {retry_delay}s")
                time.sleep(retry_delay); continue
            print(f"HTTP: {e}")
        except Exception as e: print(f"Error: {e}")
        time.sleep(1)

if __name__=="__main__":
    main()
