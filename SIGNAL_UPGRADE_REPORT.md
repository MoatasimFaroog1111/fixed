# Signal Quality Upgrade — v8

## Added
- EMA Trend using EMA 9 / EMA 21.
- ATR-like rolling volatility gate using mid-price movement and spread.
- Momentum signal using short and longer lookback.
- Volume / market-depth imbalance from BullionVault order-book quantities.
- Weighted news signal instead of equal simple voting.
- Session detection: London / New York / overlap boost.
- Weighted confidence engine instead of simple 4-signal count.

## Aggressive Mode Adjustments
- Silver confidence: 0.40.
- Palladium confidence: 0.50.
- Silver TP: 1.2%.
- Palladium TP: 4.5%.
- Silver max spread: 1.5%.
- Palladium max spread: 3.0%.
- Hourly scalp filter relaxed for more entries while keeping spread filtering.

## Notes
- The bot still blocks low-volatility dead markets unless weighted signals are strong.
- SELL signals are logged as bearish market warnings and do not open short positions.
- BullionVault physical trading costs are high; aggressive mode can increase trade frequency and risk.
