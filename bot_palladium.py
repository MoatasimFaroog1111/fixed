"""
Palladium Trading Bot — Guardian v7
DRY_RUN = False  ✅  (PRODUCTION MODE)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from base_bot import BaseMetalBot


class PalladiumBot(BaseMetalBot):
    BOT_NAME      = "PalladiumBot"
    SECURITY_ID   = "PDXLN"
    CURRENCY      = "USD"
    POLL_INTERVAL = 15
    USE_ML        = True
    DRY_RUN       = False          # ✅ PRODUCTION — أوامر حقيقية
    LOG_FILE      = "bot_palladium.log"
    USE_NEWS      = True

    MAX_POSITION_KG             = 0.05
    MAX_DAILY_TRADES            = 50
    MAX_DAILY_LOSS_USD          = 35.0
    TAKE_PROFIT_PCT             = 0.010
    MIN_SPREAD_PCT              = 0.003
    MAX_OPEN_ORDERS             = 1
    CONFIDENCE_THRESHOLD        = 0.65
    PRICE_ROUND_TO              = 10
    MAX_POSITION_PCT_OF_BALANCE = 0.20
    MAX_ACCEPTABLE_SPREAD_PCT   = 0.007
    POSITION_RISK_PCT           = 0.02
    STOP_LOSS_PCT               = 0.050

    SCALP_ENABLED                    = True
    SCALP_MIN_HOURLY_VOLATILITY_PCT  = 0.005
    SCALP_ENTRY_DROP_PCT             = 0.008
    SCALP_TAKE_PROFIT_PCT            = 0.014
    SCALP_STOP_LOSS_PCT              = 0.050
    SCALP_TRAILING_STOP_PCT          = 0.006
    SCALP_MAX_SPREAD_TO_TP_RATIO     = 0.75
    SCALP_MAX_TRADES_PER_DAY         = 2
    SCALP_RSI_BUY_LEVEL              = 42.0
    SCALP_RSI_SELL_LEVEL             = 60.0

    TRAILING_ACTIVATE_PCT = 0.006
    TRAILING_DISTANCE_PCT = 0.004
    DCA_ENABLED           = True
    DCA_TRIGGER_PCT       = 0.012
    DCA_MAX_TIMES         = 1
    DCA_SIZE_RATIO        = 0.50
    TRADING_HOURS_ONLY    = False

    TG_TOKEN_ENV = "TG_TOKEN_PALLADIUM"
    TG_CHAT_ENV  = "TG_CHAT_ID"


if __name__ == "__main__":
    username = os.environ.get("BV_USERNAME", "")
    password = os.environ.get("BV_PASSWORD", "")
    if not username or not password:
        print("ERROR: BV_USERNAME / BV_PASSWORD not set.")
        sys.exit(1)
    PalladiumBot(username, password).run()
