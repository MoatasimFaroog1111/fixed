"""
Guardian Telegram Command Center v3 — Advanced
أوامر: /help /price /levels /signal /status /pnl /balance /report /chart /pause /resume /close
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
    "silver":    Path("/home/moatasim/fixed/state_AGXLN.json"),
    "palladium": Path("/home/moatasim/fixed/state_PDXLN.json"),
}
PRICE_LOG_FILES = {
    "silver":    Path("/home/moatasim/fixed/price_log_AGXLN.json"),
    "palladium": Path("/home/moatasim/fixed/price_log_PDXLN.json"),
}
METALS = {
    "silver":    {"name":"Silver",    "symbol":"AGXLN","currency":"USD"},
    "palladium": {"name":"Palladium", "symbol":"PDXLN","currency":"USD"},
}
DAILY_REPORT_HOUR_UTC = 21

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
    return {"paused":False,"allow_buy":True,"allow_sell":True,
            "silver_enabled":True,"palladium_enabled":True}

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

def cmd_report():
    logs    = read_trade_log()
    today   = datetime.now(timezone.utc).date().isoformat()
    week_ago= (datetime.now(timezone.utc)-timedelta(days=7)).date().isoformat()
    month_ago=(datetime.now(timezone.utc)-timedelta(days=30)).date().isoformat()

    def stats(trades):
        if not trades: return None
        wins   = [t for t in trades if t["pnl"]>0]
        losses = [t for t in trades if t["pnl"]<=0]
        total  = sum(t["pnl"] for t in trades)
        best   = max(trades,key=lambda x:x["pnl"])
        worst  = min(trades,key=lambda x:x["pnl"])
        wr     = round(len(wins)/len(trades)*100,1) if trades else 0
        avg_w  = round(sum(t["pnl"] for t in wins)/len(wins),2) if wins else 0
        avg_l  = round(sum(t["pnl"] for t in losses)/len(losses),2) if losses else 0
        return {"n":len(trades),"wins":len(wins),"losses":len(losses),
                "wr":wr,"total":round(total,2),"best":best,"worst":worst,
                "avg_w":avg_w,"avg_l":avg_l}

    today_trades = [t for t in logs if t.get("timestamp","")[:10]==today]
    week_trades  = [t for t in logs if t.get("timestamp","")[:10]>=week_ago]
    month_trades = [t for t in logs if t.get("timestamp","")[:10]>=month_ago]
    all_trades   = logs

    def fmt(s, label):
        if not s: return f"{label}: لا بيانات"
        bar = progress_bar(s["wr"],10)
        return (
            f"{label}: {s['total']:+.2f}$ | {s['n']} صفقة\n"
            f"   Win Rate: {bar} {s['wr']}% ({s['wins']}W/{s['losses']}L)\n"
            f"   متوسط ربح={s['avg_w']:+.2f}$ | متوسط خسارة={s['avg_l']:+.2f}$\n"
            f"   أفضل={s['best']['pnl']:+.2f}$ ({s['best']['symbol']})\n"
            f"   أسوأ={s['worst']['pnl']:+.2f}$ ({s['worst']['symbol']})"
        )

    lines = ["📊 Performance Report","━"*22,
             fmt(stats(today_trades),  "📅 اليوم"),
             fmt(stats(week_trades),   "📆 الأسبوع"),
             fmt(stats(month_trades),  "🗓 الشهر"),
             fmt(stats(all_trades),    "📈 الإجمالي")]
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
    if metal=="all":   ctrl["emergency_close_all"]=True
    elif metal=="silver":    ctrl["close_silver"]=True
    elif metal=="palladium": ctrl["close_palladium"]=True
    else: return "❓ حدد: /close silver|palladium|all"
    write_control(ctrl)
    return f"🔴 إغلاق {metal}..."

# ── Help ───────────────────────────────────────────────────────────
HELP_TEXT = """🤖 Guardian v3 — Command Center
━━━━━━━━━━━━━━━━━━━━━━

📈 الأسعار والتحليل:
/price  [silver|palladium|all]
/levels [silver|palladium|all]
/signal [silver|palladium|all]
/chart  [silver|palladium|all]

📊 التقارير:
/status  — مراكز + تحليل تقني
/pnl     — أرباح يوم/أسبوع/كلي
/report  — إحصائيات أداء كاملة
/balance — رصيد المحفظة

⚙️ التحكم:
/pause   — إيقاف التداول
/resume  — استئناف التداول
/close   [silver|palladium|all]

━━━━━━━━━━━━━━━━━━━━━━
💡 بدون تحديد = all
📬 تقرير يومي تلقائي 21:00 UTC
⚡ تنبيه TP/SL عند 80%"""

# ── Handler ────────────────────────────────────────────────────────
def handle_command(text):
    parts = text.strip().lower().split()
    cmd   = parts[0]
    metal = "all"
    if len(parts)>=2:
        if parts[1] in ("silver","agx","agxln"):      metal="silver"
        elif parts[1] in ("palladium","pdx","pdxln"): metal="palladium"

    if cmd=="/help":    return HELP_TEXT
    if cmd=="/status":  return cmd_status()
    if cmd=="/pnl":     return cmd_pnl()
    if cmd=="/balance": return cmd_balance()
    if cmd=="/report":  return cmd_report()
    if cmd=="/chart":   return cmd_chart(metal)
    if cmd=="/pause":   return cmd_pause()
    if cmd=="/resume":  return cmd_resume()
    if cmd=="/close":   return cmd_close(metal)

    if cmd=="/price":
        if metal=="all":
            msg="💰 Live Prices\n"+"━"*16+"\n"
            for k,v in METALS.items():
                p=get_metal_price(k)
                msg+=f"{v['name']}: {p:,.2f}\n" if p else f"{v['name']}: N/A\n"
            return msg
        m=METALS[metal]; p=get_metal_price(metal)
        return f"💰 {m['name']} Live Price\n{m['symbol']} | {p:,.2f}" if p else f"⚠️ N/A"

    if cmd in ("/levels","/support","/resistance"):
        if metal=="all":
            return "\n\n".join(technical_levels(get_metal_price(k),v["name"]) for k,v in METALS.items())
        return technical_levels(get_metal_price(metal),METALS[metal]["name"])

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
        return "\n\n".join(lines)

    return "❓ أمر غير معروف — /help"

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
def tg_send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id":CHAT_ID,"text":msg},timeout=20)
    except Exception as e: print(f"tg_send: {e}")

def load_offset():
    if not OFFSET_FILE.exists(): return 0
    try: return int(OFFSET_FILE.read_text().strip())
    except: return 0

def save_offset(v): OFFSET_FILE.write_text(str(v))

def drop_pending_updates():
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
                      data={"drop_pending_updates":True},timeout=10)
    except: pass

def steal_session():
    print("Stealing Telegram session...")
    for attempt in range(60):
        try:
            r=requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                           params={"timeout":0,"offset":-1},timeout=10)
            if r.status_code==200:
                print(f"✅ Session stolen after {attempt+1} attempts")
                return True
            if r.status_code==409: time.sleep(1); continue
        except: time.sleep(1)
    return False

def get_updates(offset):
    r=requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                   params={"timeout":30,"offset":offset},timeout=40)
    if r.status_code==409: raise requests.HTTPError("409 Conflict")
    r.raise_for_status()
    return r.json()["result"]

# ── Main ───────────────────────────────────────────────────────────
def main():
    if not TOKEN: raise RuntimeError("Telegram token missing")
    print("Logging in to BullionVault...")
    if not _ensure_login(): print("⚠️ BullionVault login failed")
    drop_pending_updates()
    steal_session()
    threading.Thread(target=_daily_report_thread,   daemon=True).start()
    threading.Thread(target=_proximity_alert_thread, daemon=True).start()
    tg_send("✅ Guardian v3 started\n/help للأوامر")
    offset=load_offset(); retry_delay=1
    while True:
        try:
            updates=get_updates(offset); retry_delay=1
            for u in updates:
                offset=u["update_id"]+1; save_offset(offset)
                msg=u.get("message")
                if not msg: continue
                text=msg.get("text","").strip()
                if not text.startswith("/"): continue
                tg_send(handle_command(text))
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
