import collections

def calculate_atr(price_history: collections.deque, period: int = 14) -> float:
    """
    حساب ATR من price_history (deque of dicts with 'high', 'low', 'close').
    إذا كان السجل يحتوي على سعر واحد فقط (close)، نستخدم تقريب بسيط.
    """
    prices = list(price_history)
    if len(prices) < period + 1:
        return None  # بيانات غير كافية

    true_ranges = []
    for i in range(1, len(prices)):
        try:
            high = prices[i]['high'] if isinstance(prices[i], dict) else float(prices[i])
            low = prices[i]['low'] if isinstance(prices[i], dict) else float(prices[i])
            prev_close = prices[i]['close'] if isinstance(prices[i], dict) else float(prices[i])
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low  - prev_close)
            )
        except (KeyError, TypeError):
            continue
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[-period:]) / period
    return atr


def dynamic_stop_loss(current_price: float,
                      price_history: collections.deque,
                      multiplier: float = 2.0,
                      period: int = 14,
                      fallback_pct: float = 0.003) -> float:
    """
    يحسب Stop Loss ديناميكي بناءً على ATR.
    - multiplier: كلما زاد، كان الستوب أبعد (أقل صرامة)
    - fallback_pct: نسبة ثابتة تُستخدم إذا لم يتوفر ATR بعد
    """
    atr = calculate_atr(price_history, period)
    if atr is None or atr == 0:
        # رجوع للنسبة الثابتة إذا لم تتوفر بيانات كافية
        return current_price * (1 - fallback_pct)

    stop = current_price - (atr * multiplier)
    return round(stop, 4)
