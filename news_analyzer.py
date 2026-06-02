"""
news_analyzer.py v3
التغييرات:
- T-01: استبدال اسم النموذج بـ claude-3-haiku-20240307 مع تحقق في __init__
- T-02: إضافة max_age_hours=24 لتصفية المقالات القديمة
- T-03: زيادة ARTICLES_PER_FEED إلى 5 وإضافة مصادر جديدة للمعادن
- T-04: إضافة Retry (3 محاولات) عند anthropic.APIConnectionError
- T-05: soft threshold — إرجاع None بدل 0.0 عند غياب أخبار relevant
"""
import os
import re
import time
import socket
import logging
import json
import calendar
import feedparser
import anthropic
from typing import Dict, Optional

logger = logging.getLogger(__name__)

NEWS_FEEDS = [
    # مصادر أصلية
    "https://www.kitco.com/rss/",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.mining.com/feed/",
    "https://www.investing.com/rss/news_301.rss",
    "https://www.investing.com/rss/news_8.rss",
    # T-03: مصادر إضافية متخصصة بالمعادن الثمينة
    "https://goldprice.org/rss.xml",
    "https://www.bullionvault.com/gold-news/rss.xml",
    "https://www.marketwatch.com/rss/topstories",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SI=F&region=US&lang=en-US",
]

KEYWORDS = {
    "AUXLN": ["gold", "xau", "bullion", "precious metal", "fed", "inflation",
              "dollar", "treasury", "safe haven", "rate", "gdp", "central bank"],
    "AGXLN": ["silver", "xag", "precious metal", "industrial metal", "solar",
              "photovoltaic", "manufacturing"],
    "PTXLN": ["platinum", "xpt", "auto", "hydrogen", "fuel cell", "ev", "electric vehicle"],
    "PDXLN": ["palladium", "xpd", "auto", "catalytic", "russia", "converter"],
}

# T-01: النموذج الافتراضي المُصحَّح
DEFAULT_MODEL    = "claude-3-haiku-20240307"
CACHE_TTL        = 1800          # 30 دقيقة
FETCH_TIMEOUT_S  = 8
FEED_LIMIT       = int(os.environ.get("NEWS_FEED_LIMIT", "10"))
ARTICLES_PER_FEED = 5            # T-03: زيادة من 3 إلى 5
MAX_AGE_HOURS    = 24            # T-02: تجاهل مقالات أقدم من 24 ساعة
CLAUDE_RETRIES   = 3             # T-04: عدد المحاولات
CLAUDE_RETRY_DELAY = 1.0         # T-04: ثانية بين المحاولات


class NewsAnalyzer:

    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._articles_cache = {"articles": [], "fetched_at": 0.0}

        # T-01: تحقق من اسم النموذج
        model = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)
        valid_prefixes = ("claude-3", "claude-2", "claude-instant")
        if not any(model.startswith(p) for p in valid_prefixes):
            logger.warning(
                f"CLAUDE_MODEL='{model}' يبدو غير صحيح — "
                f"استخدام الافتراضي: {DEFAULT_MODEL}"
            )
            model = DEFAULT_MODEL
        self._model = model

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY غير موجود — سيفشل تحليل الأخبار")
        self._client = anthropic.Anthropic(api_key=api_key)

    # ── جلب الأخبار ──────────────────────────────────────────────

    def _fetch_news(self) -> list:
        """جلب الأخبار مع timeout صريح وتصفية العمر — T-02 + C-05."""
        now = time.time()
        if now - self._articles_cache["fetched_at"] < CACHE_TTL:
            return self._articles_cache["articles"]

        articles = []
        cutoff = now - MAX_AGE_HOURS * 3600  # T-02: الحد الزمني

        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(FETCH_TIMEOUT_S)
        try:
            for feed_url in NEWS_FEEDS[:FEED_LIMIT]:
                try:
                    feed = feedparser.parse(
                        feed_url,
                        request_headers={"User-Agent": "Mozilla/5.0"},
                    )
                    count = 0
                    for entry in feed.entries:
                        if count >= ARTICLES_PER_FEED:
                            break

                        # T-02: تصفية المقالات القديمة
                        pub = entry.get("published_parsed")
                        if pub:
                            pub_ts = calendar.timegm(pub)
                            if pub_ts < cutoff:
                                continue  # مقال قديم — تجاهل

                        articles.append({
                            "title":   entry.get("title", ""),
                            "summary": entry.get("summary", "")[:300],
                        })
                        count += 1

                except Exception as e:
                    logger.debug(f"خطأ في جلب {feed_url}: {e}")
        finally:
            socket.setdefaulttimeout(old_timeout)

        self._articles_cache = {"articles": articles, "fetched_at": now}
        logger.info(f"جُلب {len(articles)} مقال للتحليل (آخر {MAX_AGE_HOURS}س)")
        return articles

    def _filter_articles(self, security_id: str, articles: list) -> list:
        keywords = KEYWORDS.get(security_id, [])
        relevant = []
        for art in articles:
            text = (art["title"] + " " + art["summary"]).lower()
            if any(kw in text for kw in keywords):
                relevant.append(art)
        return relevant[:6]

    # ── تحليل Sentiment ──────────────────────────────────────────

    def _analyze_with_claude(self, security_id: str, articles: list) -> Optional[float]:
        """
        T-05: ترجع None إذا لم توجد أخبار relevant.
        T-04: Retry 3 مرات عند APIConnectionError.
        """
        if not articles:
            return None  # T-05: soft threshold — لا أخبار

        metal_names = {
            "AUXLN": "الذهب",
            "AGXLN": "الفضة",
            "PTXLN": "البلاتين",
            "PDXLN": "البلاديوم",
        }
        metal = metal_names.get(security_id, security_id)

        news_text = "\n\n".join([
            f"العنوان: {a['title']}\nالملخص: {a['summary']}"
            for a in articles
        ])

        prompt = f"""أنت محلل مالي متخصص في المعادن الثمينة.

حلّل الأخبار التالية وأعطني تأثيرها على سعر {metal}:

{news_text}

أجب بـ JSON فقط بهذا الشكل بدون أي نص آخر:
{{"score": 0.0, "reason": "سبب قصير"}}

حيث score:
+1.0 = صعودي قوي جداً
+0.5 = صعودي معتدل
0.0 = محايد
-0.5 = هبوطي معتدل
-1.0 = هبوطي قوي جداً"""

        last_error = None
        for attempt in range(1, CLAUDE_RETRIES + 1):  # T-04: Retry loop
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=150,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw = response.content[0].text.strip()
                raw = re.sub(r"```(?:json)?|```", "", raw).strip()  # M-03
                data = json.loads(raw)
                score = float(data.get("score", 0.0))
                score = max(-1.0, min(1.0, score))
                logger.info(
                    f"Sentiment {security_id}: {score:+.2f} | {data.get('reason', '')}"
                )
                return score

            except anthropic.APIConnectionError as e:
                last_error = e
                logger.warning(
                    f"Claude connection error (محاولة {attempt}/{CLAUDE_RETRIES}): {e}"
                )
                if attempt < CLAUDE_RETRIES:
                    time.sleep(CLAUDE_RETRY_DELAY)

            except json.JSONDecodeError as e:
                logger.error(f"خطأ في تحليل JSON من Claude: {e}")
                return 0.0

            except Exception as e:
                logger.error(f"خطأ في تحليل Claude: {e}")
                return 0.0

        logger.error(f"فشل Claude بعد {CLAUDE_RETRIES} محاولات: {last_error}")
        return None  # T-05: فشل اتصال → None لا 0.0

    # ── الواجهة الرئيسية ─────────────────────────────────────────

    def get_sentiment(self, security_id: str) -> Optional[float]:
        """
        Sentiment score مُخزَّن لـ CACHE_TTL ثانية.
        T-05: يرجع None إذا لم تُوجد أخبار relevant أو فشل الاتصال.
        """
        now = time.time()
        cached = self._cache.get(security_id)
        if cached and (now - cached["time"]) < CACHE_TTL:
            return cached["score"]

        articles = self._fetch_news()
        relevant = self._filter_articles(security_id, articles)
        score = self._analyze_with_claude(security_id, relevant)

        # T-05: نخزن None في الكاش أيضاً لتجنب استدعاء Claude مراراً
        self._cache[security_id] = {"score": score, "time": now}
        return score

    def get_signal(self, security_id: str) -> str:
        """
        T-05: إذا كان score=None → يُرجع 'NO_DATA' بدل HOLD
        حتى تفهم strategy.py الفرق بين 'لا أخبار' و 'أخبار محايدة'.
        """
        score = self.get_sentiment(security_id)
        if score is None:
            return "NO_DATA"
        if score >= 0.35:
            return "BUY"
        elif score <= -0.35:
            return "SELL"
        return "HOLD"
