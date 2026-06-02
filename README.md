# BullionVault Trading Bot 🤖

نظام تداول آلي للمعادن الثمينة عبر BullionVault XML API.

## هيكل المشروع

```
bullionvault_bot/
├── base_bot.py        ← Base class مشتركة لجميع البوتات (جديد)
├── bot_gold.py        ← بوت الذهب   (AUXLN)
├── bot_silver.py      ← بوت الفضة   (AGXLN)
├── bot_platinum.py    ← بوت البلاتين (PTXLN)
├── bot_palladium.py   ← بوت البلاديوم (PDXLN)
├── run_all_bots.py    ← تشغيل جميع البوتات معاً
├── api_client.py      ← BullionVault XML API wrapper
├── parser.py          ← XML parser (مُصلح)
├── ml_predictor.py    ← Ensemble ML + Kalman (مُصلح)
├── risk_manager.py    ← إدارة المخاطر (مُصلح)
├── strategy.py        ← محرك الإشارات (مُصلح)
├── backtest.py        ← محاكاة تاريخية
├── .env.example       ← نموذج متغيرات البيئة (جديد)
└── requirements.txt
```

## تشغيل سريع

### 1. تثبيت المتطلبات
```bash
pip install -r requirements.txt
```

### 2. إعداد بيانات الاعتماد
```bash
cp .env.example .env
# ثم عدّل .env بقيمك الحقيقية
```

أو يدوياً:
```bash
export BV_USERNAME="your_username"
export BV_PASSWORD="your_password"
export TG_CHAT_ID="your_telegram_id"
export TG_TOKEN_GOLD="token_from_botfather"
export TG_TOKEN_SILVER="token_from_botfather"
export TG_TOKEN_PLATINUM="token_from_botfather"
export TG_TOKEN_PALLADIUM="token_from_botfather"
```

### 3. تشغيل بوت واحد
```bash
python bot_gold.py
```

### 4. تشغيل جميع البوتات
```bash
python run_all_bots.py
```
> يُعيد تشغيل أي بوت يتوقف تلقائياً.

### 5. Backtest
```bash
python backtest.py
```

---

## الإصلاحات في هذا الإصدار

| المشكلة | الإصلاح |
|---|---|
| رصيد USD لا يُقرأ → لا صفقات | `parse_balance` محسّن يكتشف الكاش بأي شكل |
| لا سبب مرئي لـ "No signal" | اللوج يعرض ML/RSI/Trend/Confidence/USD |
| ML يجمّد حلقة التداول | التدريب في background thread |
| `price_history` تتضخم بلا حد | `deque(maxlen=500)` |
| بيانات الدخول في الكود | env vars فقط — بدون قيم افتراضية |
| Telegram token مشترك | token منفصل لكل معدن عبر env var |
| تقريب السعر غير متسق | `_round_price()` موحدة في base class |
| كود مكرر في 4 ملفات | `base_bot.py` مشترك |
| `daily_trades` تنمو للأبد | تُحذف السجلات الأقدم من 7 أيام |
| ML يحتاج 80+ دورة للتدريب | lookback مُخفَّض من 60 → 30 |

---

## إعدادات المعادن

| المعدن | SECURITY_ID | Stop Loss | Take Profit | Confidence |
|---|---|---|---|---|
| Gold   | AUXLN | 0.25% | 0.5% | 62% |
| Silver | AGXLN | 0.30% | 0.6% | 60% |
| Platinum  | PTXLN | 0.30% | 0.6% | 63% |
| Palladium | PDXLN | 0.40% | 0.8% | 65% |

---

## تعطيل/تفعيل معدن معين

في `run_all_bots.py`:
```python
BOTS = {
    "GOLD":     "bot_gold.py",
    # "SILVER": "bot_silver.py",   # علّق لإيقافه
    "PLATINUM": "bot_platinum.py",
    "PALLADIUM":"bot_palladium.py",
}
```

---

⚠️ **تحذير**: التداول ينطوي على مخاطر خسارة مالية. اختبر دائماً بوضع `DRY_RUN = True` قبل التداول الحقيقي.
