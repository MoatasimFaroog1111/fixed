"""BullionVault Bot — PLATINUM (PTXLN) v5"""
import os, sys
from base_bot import BaseMetalBot

class PlatinumBot(BaseMetalBot):
    BOT_NAME      = "PlatinumBot"
    SECURITY_ID   = "PTXLN"
    CURRENCY      = "USD"
    POLL_INTERVAL = 15
    USE_ML        = True
    DRY_RUN       = False
    LOG_FILE      = "bot_platinum.log"

    MAX_POSITION_KG             = 0.03
    MAX_POSITION_PCT_OF_BALANCE = 0.25
    TAKE_PROFIT_PCT             = 0.010   # بلاتين يحتاج TP أعلى قليلاً
    CONFIDENCE_THRESHOLD        = 0.63
    PRICE_ROUND_TO              = 10
    MAX_ACCEPTABLE_SPREAD_PCT   = 0.015   # البلاتين سبريد 1-1.5%

    TRAILING_ACTIVATE_PCT = 0.006
    TRAILING_DISTANCE_PCT = 0.003
    DCA_TRIGGER_PCT       = 0.015
    DCA_MAX_TIMES         = 1
    TRADING_HOURS_ONLY    = True

    TG_TOKEN_ENV = "TG_TOKEN_PLATINUM"
    TG_CHAT_ENV  = "TG_CHAT_ID"

if __name__ == "__main__":
    u = os.environ.get("BV_USERNAME")
    p = os.environ.get("BV_PASSWORD")
    if not u or not p:
        print("ERROR: Set BV_USERNAME and BV_PASSWORD")
        sys.exit(1)
    PlatinumBot(u, p).run()
