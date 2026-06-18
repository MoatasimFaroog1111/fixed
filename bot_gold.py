"""BullionVault Bot — GOLD (AUXLN) v5"""
from base_bot import BaseMetalBot
from shared_utils import launch_bot

class GoldBot(BaseMetalBot):
    BOT_NAME      = "GoldBot"
    SECURITY_ID   = "AUXLN"
    CURRENCY      = "USD"
    POLL_INTERVAL = 15
    USE_ML        = True
    DRY_RUN       = False
    LOG_FILE      = "bot_gold.log"

    MAX_POSITION_KG             = 0.01
    MAX_POSITION_PCT_OF_BALANCE = 0.25
    TAKE_PROFIT_PCT             = 0.015
    CONFIDENCE_THRESHOLD        = 0.62
    PRICE_ROUND_TO              = 10
    MAX_ACCEPTABLE_SPREAD_PCT   = 0.004   # الذهب سبريد طبيعي 0.2-0.3%

    TRAILING_ACTIVATE_PCT = 0.005
    TRAILING_DISTANCE_PCT = 0.003
    DCA_TRIGGER_PCT       = 0.010
    DCA_MAX_TIMES         = 1
    TRADING_HOURS_ONLY    = True

    TG_TOKEN_ENV = "TG_TOKEN_GOLD"
    TG_CHAT_ENV  = "TG_CHAT_ID"

if __name__ == "__main__":
    launch_bot(GoldBot)
