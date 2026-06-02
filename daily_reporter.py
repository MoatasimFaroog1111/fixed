"""
Daily Reporter — تقرير يومي تلقائي الساعة 6 مساءً بتوقيت الرياض
"""
import threading, time, logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
RIYADH = timezone(timedelta(hours=3))

class DailyReporter:
    REPORT_HOUR = 18
    REPORT_MIN  = 0

    def __init__(self, tg_controller, bot_ref):
        self.tg           = tg_controller
        self.bot          = bot_ref
        self._thread      = None
        self._running     = False
        self._last_report = None

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True, name="DailyReporter")
        self._thread.start()
        logger.info("DailyReporter: بدأ — تقرير يومي الساعة 18:00 الرياض")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                now   = datetime.now(RIYADH)
                today = now.date()
                if (now.hour == self.REPORT_HOUR and
                    now.minute == self.REPORT_MIN and
                    self._last_report != today):
                    self._last_report = today
                    self.tg.send_daily_report()
                    logger.info("DailyReporter: تقرير يومي أُرسل ✅")
            except Exception as e:
                logger.error(f"DailyReporter error: {e}")
            time.sleep(50)
