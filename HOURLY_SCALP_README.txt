Hourly Scalp Full Integration
=============================

Added:
- hourly_scalp_strategy.py

Changed:
- base_bot.py now creates HourlyScalpStrategy in __init__.
- BaseMetalBot now has SCALP_* configuration constants.
- BUY execution is blocked unless BOTH conditions agree:
  1) Original TradingStrategy returns BUY.
  2) HourlyScalpStrategy returns BUY using rolling intraday volatility,
     support/resistance, RSI, trend, spread-to-target ratio, and daily trade limit.

Important:
- The bot still does not short-sell. A scalp SELL signal means "do not open a new BUY".
- The rolling hourly window is approximated from POLL_INTERVAL samples.
- Keep DRY_RUN=True until you verify behavior in logs.
