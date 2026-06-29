"""
ML Price Predictor v8 — ULTRA PRECISION
التحسينات (بالأولوية):
  P1: تحويل كامل إلى XGBClassifier (BUY/SELL/HOLD) — أعلى دقة قرار
  P2: توسيع الـ features من 20 إلى 60+ (Bollinger, CCI, Stochastic, Hurst, EMA multi, ROC)
  P3: Stacking مع LightGBM + XGB + RF + meta-learner Ridge
  P4: Multi-window LOOKBACK [12, 24, 48] — نوافذ زمنية متعددة
  P6: Walk-Forward split بدلاً من random shuffle
"""
import numpy as np
import logging
import threading
import pickle
import os
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

MODELS_DIR = "models"

try:
    from sklearn.ensemble import (
        RandomForestClassifier,
        GradientBoostingClassifier,
        StackingClassifier,
    )
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score, classification_report
    import xgboost as xgb
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("sklearn/xgboost غير مثبتة.")

try:
    import lightgbm as lgb
    LGBM_AVAILABLE = True
except ImportError:
    LGBM_AVAILABLE = False
    logger.warning("lightgbm غير مثبت — pip install lightgbm")


# ────────────────────────────────────────────────
# Kalman Filter 1D
# ────────────────────────────────────────────────
class KalmanFilter1D:
    def __init__(self, process_variance=1e-4, measurement_variance=0.1):
        self.process_variance     = process_variance
        self.measurement_variance = measurement_variance
        self.estimate             = None
        self.error_estimate       = 1.0

    def update(self, measurement: float) -> float:
        if self.estimate is None:
            self.estimate = measurement
            return measurement
        kg = self.error_estimate / (self.error_estimate + self.measurement_variance)
        self.estimate       = self.estimate + kg * (measurement - self.estimate)
        self.error_estimate = (1 - kg) * self.error_estimate + self.process_variance
        return self.estimate


# ────────────────────────────────────────────────
# Feature Engineer — 60+ features, Multi-Window
# ────────────────────────────────────────────────
class FeatureEngineer:
    """
    60+ feature عبر 3 نوافذ زمنية: 12, 24, 48.
    REQUIRED_PRICES = 49 (LOOKBACK=48 + 1)
    """
    LOOKBACKS       = [12, 24, 48]
    MAX_LOOKBACK    = 48
    REQUIRED_PRICES = 49  # MAX_LOOKBACK + 1

    @staticmethod
    def _ema(prices: np.ndarray, period: int) -> float:
        k, ema = 2 / (period + 1), float(prices[0])
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    @staticmethod
    def _rsi(returns: np.ndarray, period: int = 14) -> float:
        if len(returns) < period:
            return 0.5
        r     = returns[-period * 2:] if len(returns) >= period * 2 else returns
        gains = np.where(r > 0, r, 0.0)
        losses= np.where(r < 0, -r, 0.0)
        gain  = gains[:period].mean()
        loss  = losses[:period].mean()
        for g, l in zip(gains[period:], losses[period:]):
            gain = (gain * (period - 1) + g) / period
            loss = (loss * (period - 1) + l) / period
        rs = gain / (loss + 1e-10)
        return (100 - 100 / (1 + rs)) / 100

    @staticmethod
    def _hurst(prices: np.ndarray) -> float:
        """Hurst Exponent proxy — H>0.5 trending, H<0.5 mean-reverting."""
        try:
            log_p = np.log(prices + 1e-10)
            lags  = range(2, min(10, len(prices) // 2))
            tau   = [np.std(np.diff(log_p, n)) for n in lags]
            if len(tau) < 2 or any(t <= 0 for t in tau):
                return 0.5
            poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
            return float(np.clip(poly[0], 0.0, 1.0))
        except Exception:
            return 0.5

    @staticmethod
    def _window_features(p: np.ndarray, window: int) -> list:
        """20 features لنافذة واحدة."""
        if len(p) < window + 1:
            return [0.0] * 20
        pw = p[-(window + 1):]
        returns = np.diff(pw) / (pw[:-1] + 1e-10)

        def smean(n): return returns[-n:].mean() if len(returns) >= n else returns.mean()
        def sstd(n):  return returns[-n:].std()  if len(returns) >= n else returns.std()

        cur = pw[-1]
        feats = [
            returns[-1],
            smean(3), smean(6), smean(window),
            pw[-5:].mean()  / (cur + 1e-10) if len(pw) >= 5  else 1.0,
            pw[-10:].mean() / (cur + 1e-10) if len(pw) >= 10 else 1.0,
            pw[-window//2:].mean() / (cur + 1e-10),
            pw.mean() / (cur + 1e-10),
            (cur - pw[-5])  / (pw[-5]  + 1e-10) if len(pw) > 5  else 0.0,
            (cur - pw[-min(12, len(pw)-1)]) / (pw[-min(12, len(pw)-1)] + 1e-10),
            (cur - pw[-min(window, len(pw)-1)]) / (pw[-min(window, len(pw)-1)] + 1e-10),
            sstd(10), sstd(window),
            FeatureEngineer._rsi(returns, min(14, window)),
            (cur - pw[-min(20, len(pw)):].mean()) / (pw[-min(20, len(pw)):].std() + 1e-10),
            (pw[-min(12, len(pw)):].mean() - pw.mean()) / (cur + 1e-10),
            (cur - pw.min()) / (pw.max() - pw.min() + 1e-10),
            1.0 if len(pw) >= 20 and pw[-5:].mean() > pw[-20:].mean() else -1.0,
            (cur - pw[-min(window, len(pw)-1)]) / (pw[-min(window, len(pw)-1)] + 1e-10),
            returns[-1] * 100,
        ]
        return feats

    @staticmethod
    def compute(prices: np.ndarray) -> Optional[np.ndarray]:
        if len(prices) < FeatureEngineer.REQUIRED_PRICES:
            return None
        p = prices.astype(float)

        # ── P4: Multi-window (12, 24, 48) — 3×20 = 60 features ──
        all_feats = []
        for lb in FeatureEngineer.LOOKBACKS:
            all_feats.extend(FeatureEngineer._window_features(p, lb))

        # ── P2: Advanced features (20 إضافية) ──
        returns = np.diff(p) / (p[:-1] + 1e-10)
        cur = p[-1]

        # Bollinger Bands
        bb_win = p[-20:] if len(p) >= 20 else p
        bb_mid = bb_win.mean()
        bb_std = bb_win.std() + 1e-10
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        all_feats.append((cur - bb_lower) / (bb_upper - bb_lower + 1e-10))  # BB position
        all_feats.append((bb_upper - bb_lower) / (bb_mid + 1e-10))          # BB width

        # Stochastic
        hi14 = p[-14:].max() if len(p) >= 14 else p.max()
        lo14 = p[-14:].min() if len(p) >= 14 else p.min()
        all_feats.append((cur - lo14) / (hi14 - lo14 + 1e-10))  # Stoch %K

        # CCI
        cci_win = p[-20:] if len(p) >= 20 else p
        mad = np.mean(np.abs(cci_win - cci_win.mean())) + 1e-10
        all_feats.append((cur - cci_win.mean()) / (0.015 * mad))  # CCI

        # EMA ratios
        for period in [9, 21, 50]:
            ema = FeatureEngineer._ema(p[-min(period*2, len(p)):], period)
            all_feats.append((cur - ema) / (ema + 1e-10))

        # ROC (Rate of Change)
        for n in [3, 7, 14]:
            ref = p[-n] if len(p) > n else p[0]
            all_feats.append((cur - ref) / (ref + 1e-10) * 100)

        # Candle patterns
        all_feats.append(returns[-3:].sum() if len(returns) >= 3 else 0.0)
        all_feats.append(1.0 if (len(returns) >= 2 and returns[-1] > 0 and returns[-2] < 0) else -1.0)
        all_feats.append(abs(returns[-1]) / (returns[-10:].std() + 1e-10) if len(returns) >= 10 else 0.0)

        # Autocorrelation
        if len(returns) > 3:
            all_feats.append(float(np.corrcoef(returns[:-1], returns[1:])[0, 1]))
            all_feats.append(float(np.corrcoef(returns[:-2], returns[2:])[0, 1]))
        else:
            all_feats.extend([0.0, 0.0])

        # Hurst exponent
        all_feats.append(FeatureEngineer._hurst(p[-24:] if len(p) >= 24 else p))

        arr = np.array(all_feats, dtype=float)
        arr = np.where(np.isnan(arr) | np.isinf(arr), 0.0, arr)
        return arr


# ────────────────────────────────────────────────
# P3: Stacking Classifier
# ────────────────────────────────────────────────
def _build_classifier():
    if not SKLEARN_AVAILABLE:
        return None

    xgb_clf = xgb.XGBClassifier(
        n_estimators=500, learning_rate=0.03, max_depth=7,
        subsample=0.8, colsample_bytree=0.7,
        reg_alpha=0.1, reg_lambda=1.0,
        objective="multi:softprob", num_class=3,
        use_label_encoder=False, eval_metric="mlogloss",
        n_jobs=-1, verbosity=0,
    )

    rf_clf = RandomForestClassifier(
        n_estimators=300, max_depth=10, min_samples_leaf=2,
        n_jobs=-1, random_state=42,
    )

    gb_clf = GradientBoostingClassifier(
        n_estimators=300, learning_rate=0.03, max_depth=6,
        subsample=0.8, random_state=42,
    )

    estimators = [("xgb", xgb_clf), ("rf", rf_clf), ("gb", gb_clf)]

    if LGBM_AVAILABLE:
        lgbm_clf = lgb.LGBMClassifier(
            n_estimators=500, learning_rate=0.03, num_leaves=63,
            subsample=0.8, colsample_bytree=0.7,
            objective="multiclass", num_class=3,
            n_jobs=-1, verbose=-1,
        )
        estimators.insert(1, ("lgbm", lgbm_clf))

    # P3: Stacking مع meta-learner
    stacking = StackingClassifier(
        estimators=estimators,
        final_estimator=LogisticRegression(max_iter=500, C=1.0, multi_class="multinomial"),
        cv=5,
        stack_method="predict_proba",
        passthrough=False,
        n_jobs=-1,
    )
    return stacking


# ────────────────────────────────────────────────
# Label encoder: 0=HOLD, 1=BUY, 2=SELL
# ────────────────────────────────────────────────
LABEL_MAP   = {0: "HOLD", 1: "BUY", 2: "SELL"}
LABEL_RMAP  = {"HOLD": 0, "BUY": 1, "SELL": 2}
BUY_THRESHOLD_PCT  = 0.15  # 0.15% صعود → BUY
SELL_THRESHOLD_PCT = 0.15  # 0.15% هبوط → SELL
CONF_THRESHOLD     = 0.60  # احتمالية ≥ 60% للقرار


def _make_labels(prices: np.ndarray) -> np.ndarray:
    """P1: تحويل قيم الأسعار إلى labels: 1=BUY, 2=SELL, 0=HOLD."""
    labels = []
    for i in range(len(prices) - 1):
        chg = (prices[i + 1] - prices[i]) / (prices[i] + 1e-10) * 100
        if chg > BUY_THRESHOLD_PCT:
            labels.append(1)
        elif chg < -SELL_THRESHOLD_PCT:
            labels.append(2)
        else:
            labels.append(0)
    return np.array(labels, dtype=int)


# ────────────────────────────────────────────────
# Ensemble Predictor (P1 Classification)
# ────────────────────────────────────────────────
class EnsemblePredictor:
    LOOKBACK         = 48
    RETRAIN_EVERY    = 50
    MIN_SAMPLES      = 60  # رُفع من 30 لضمان جودة التدريب
    SIGNAL_THRESHOLD = 0.30

    def __init__(self, security_id: str = None):
        self.security_id   = security_id
        self.price_history = deque(maxlen=2000)  # رُفع من 1000
        self.scaler        = StandardScaler() if SKLEARN_AVAILABLE else None
        self.model         = None
        self.kalman        = KalmanFilter1D()
        self.tick_count    = 0
        self.is_trained    = False
        self._lock         = threading.RLock()
        self._training     = False
        self._load_pretrained()

    def _load_pretrained(self):
        if not self.security_id or not SKLEARN_AVAILABLE:
            return
        model_path  = os.path.join(MODELS_DIR, f"{self.security_id}_model.pkl")
        scaler_path = os.path.join(MODELS_DIR, f"{self.security_id}_scaler.pkl")
        if os.path.exists(model_path) and os.path.exists(scaler_path):
            try:
                with open(model_path,  "rb") as f:
                    self.model  = pickle.load(f)
                with open(scaler_path, "rb") as f:
                    self.scaler = pickle.load(f)
                self.is_trained = True
                logger.info(f"✅ {self.security_id}: نموذج v8 مُحمَّل")
            except Exception as e:
                logger.warning(f"فشل تحميل النموذج: {e}")

    def add_price(self, price: float):
        smoothed = self.kalman.update(price)
        with self._lock:
            self.price_history.append(smoothed)
        self.tick_count += 1

        need_retrain = (
            len(self.price_history) >= self.LOOKBACK + self.MIN_SAMPLES
            and self.tick_count % self.RETRAIN_EVERY == 0
        )
        if need_retrain and not self._training:
            threading.Thread(target=self._train_bg, daemon=True).start()
        elif not self.is_trained:
            remaining = max(0, self.LOOKBACK + self.MIN_SAMPLES - len(self.price_history))
            if self.tick_count % 10 == 0 and remaining > 0:
                logger.info(f"ML warmup: {remaining} ticks remaining")

    def _train_bg(self):
        self._training = True
        try:
            self._train()
        finally:
            self._training = False

    def _train(self):
        if not SKLEARN_AVAILABLE:
            return
        try:
            with self._lock:
                snapshot = list(self.price_history)
            prices = np.array(snapshot)

            X, y_raw = [], []
            for i in range(self.LOOKBACK, len(prices) - 1):
                feats = FeatureEngineer.compute(prices[i - self.LOOKBACK: i + 1])
                if feats is not None:
                    X.append(feats)
                    y_raw.append(prices[i + 1])

            if len(X) < self.MIN_SAMPLES:
                return

            X      = np.array(X)
            prices_seq = np.array([list(self.price_history)[i] for i in
                                    range(self.LOOKBACK, len(snapshot) - 1)])

            # P1: labels تصنيف بدلاً من قيم
            y_labels = _make_labels(np.array(y_raw + [y_raw[-1]]))[:-1]

            # P6: Walk-Forward split (75% train, 25% test)
            split_idx = int(len(X) * 0.75)
            X_train, X_test = X[:split_idx], X[split_idx:]
            y_train, y_test = y_labels[:split_idx], y_labels[split_idx:]

            # Scale features
            scaler = StandardScaler()
            X_train_s = scaler.fit_transform(X_train)
            X_test_s  = scaler.transform(X_test)

            model = _build_classifier()
            if model is None:
                return
            model.fit(X_train_s, y_train)

            acc_train = accuracy_score(y_train, model.predict(X_train_s))
            acc_test  = accuracy_score(y_test,  model.predict(X_test_s))
            logger.info(
                f"{self.security_id} ML v8 | "
                f"Train Acc: {acc_train:.1%} | Test Acc: {acc_test:.1%} | "
                f"Samples: {len(X)}"
            )

            with self._lock:
                self.model      = model
                self.scaler     = scaler
                self.is_trained = True

        except Exception as e:
            logger.error(f"Training error: {e}", exc_info=True)

    def predict_signal(self) -> str:
        with self._lock:
            if not self.price_history:
                return "HOLD"
            if not self.is_trained or self.model is None:
                return "HOLD"
            try:
                prices = np.array(self.price_history)
                feats  = FeatureEngineer.compute(prices[-(self.LOOKBACK + 1):])
                if feats is None:
                    return "HOLD"
                feats_s = self.scaler.transform(feats.reshape(1, -1))
                proba   = self.model.predict_proba(feats_s)[0]  # [HOLD, BUY, SELL]

                hold_p, buy_p, sell_p = proba[0], proba[1], proba[2]

                logger.debug(
                    f"ML proba | BUY={buy_p:.0%} SELL={sell_p:.0%} HOLD={hold_p:.0%}"
                )

                if buy_p >= CONF_THRESHOLD and buy_p > sell_p:
                    return "BUY"
                elif sell_p >= CONF_THRESHOLD and sell_p > buy_p:
                    return "SELL"
                return "HOLD"

            except Exception as e:
                logger.error(f"Prediction error: {e}")
                return "HOLD"

    def predict_proba(self) -> dict:
        """إرجاع الاحتماليات كاملةً للاستخدام في strategy.py."""
        with self._lock:
            if not self.is_trained or self.model is None or not self.price_history:
                return {"HOLD": 1.0, "BUY": 0.0, "SELL": 0.0}
            try:
                prices  = np.array(self.price_history)
                feats   = FeatureEngineer.compute(prices[-(self.LOOKBACK + 1):])
                if feats is None:
                    return {"HOLD": 1.0, "BUY": 0.0, "SELL": 0.0}
                feats_s = self.scaler.transform(feats.reshape(1, -1))
                proba   = self.model.predict_proba(feats_s)[0]
                return {"HOLD": float(proba[0]), "BUY": float(proba[1]), "SELL": float(proba[2])}
            except Exception:
                return {"HOLD": 1.0, "BUY": 0.0, "SELL": 0.0}

    # للتوافق مع الكود القديم
    def predict_next(self) -> Optional[float]:
        sig = self.predict_signal()
        with self._lock:
            if not self.price_history:
                return None
            cur = self.price_history[-1]
        if sig == "BUY":
            return cur * 1.002
        elif sig == "SELL":
            return cur * 0.998
        return float(cur)


# ────────────────────────────────────────────────
# Fallback
# ────────────────────────────────────────────────
class FallbackPredictor:
    def __init__(self):
        self.prices = deque(maxlen=50)
        self.kalman = KalmanFilter1D()

    def add_price(self, price: float):
        self.prices.append(self.kalman.update(price))

    def predict_next(self) -> Optional[float]:
        return float(self.prices[-1]) if self.prices else None

    def predict_signal(self) -> str:
        if len(self.prices) < 20:
            return "HOLD"
        p        = list(self.prices)
        ma_short = np.mean(p[-5:])
        ma_long  = np.mean(p[-20:])
        if ma_short > ma_long * 1.001:
            return "BUY"
        elif ma_short < ma_long * 0.999:
            return "SELL"
        return "HOLD"

    def predict_proba(self) -> dict:
        sig = self.predict_signal()
        if sig == "BUY":
            return {"HOLD": 0.2, "BUY": 0.7, "SELL": 0.1}
        elif sig == "SELL":
            return {"HOLD": 0.2, "BUY": 0.1, "SELL": 0.7}
        return {"HOLD": 0.8, "BUY": 0.1, "SELL": 0.1}


def get_predictor(use_ml: bool = True, security_id: str = None):
    if use_ml and SKLEARN_AVAILABLE:
        return EnsemblePredictor(security_id=security_id)
    return FallbackPredictor()
