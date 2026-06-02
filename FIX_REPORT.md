# BullionVault Bot — Corrected Build Report

## Verification performed
- `python -m py_compile *.py` completed successfully.
- Smoke tests passed for spread filtering and currency parsing.
- `python backtest.py` executed successfully.

## Main fixes applied
- Fixed spread filtering by using `max_acceptable_spread_pct` from each metal bot instead of the misleading `min_spread_pct`.
- Added protective stop-loss support to `RiskConfig`, `TradeRecord`, live monitoring, and backtest exits.
- Fixed `PARTIALLY_MATCHED` handling so only the actual matched quantity is registered.
- Prevented `OPEN` buy/DCA orders from being recorded as owned positions before execution.
- Prevented failed/OPEN sell orders from deleting positions from memory.
- Fixed DCA so it updates quantity, average price, TP, and SL only after real matching.
- Fixed `parse_balance()` so EUR/GBP/etc. are not incorrectly copied into `USD`.
- Fixed Telegram notifications to log non-200 responses.
- Improved BullionVault login validation beyond merely checking `JSESSIONID`.
- Updated ML signal threshold to reduce noise-driven trades.
- Added `predict_next()` to `FallbackPredictor`.
- Unified historical model architecture with live model architecture.
- Updated Claude model selection to use `CLAUDE_MODEL` env var with a safer default.
- Increased news feed coverage from 3 to 5 feeds.
- Fixed backtest commission calculation to use entry + exit prices.
- Added restart backoff in `run_all_bots.py`.
- Adjusted gold bot defaults: 0.01 kg max position and 1.5% take-profit.

## Important note
This is a code-quality and safety correction pass. It does not guarantee profitability. Run in `DRY_RUN=True` first before any live use.
