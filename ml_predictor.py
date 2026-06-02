"""
ML Price Predictor v7
التغييرات:
  - FeatureEngineer هو المرجع الوحيد للـ features (يستخدمه historical_trainer أيضاً)
  - إصلاح off-by-one: predict_next يمرر LOOKBACK+1 سعراً كما يفعل _train
  - إصلاح thread safety: current و predicted يُقرآن تحت نفس الـ lock
  - LOOKBACK = 48 موحَّد
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
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor, VotingRegressor
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.metrics import mean_squared_error
    import xgboost as xgb
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("sklearn/xgboost غير مثبتة.")


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


class FeatureEngineer:
    """
    المرجع الوحيد لحساب الـ features — 20 feature، LOOKBACK=48.
    يُستخدم في كلٍّ من ml_predictor.py و historical_trainer.py.
    المدخل: مصفوفة من LOOKBACK+1 سعراً (49 سعراً)
    الناتج: مصفوفة 20 feature أو None
    """
    REQUIRED_PRICES = 49   # LOOKBACK + 1

    @staticmethod
    def compute(prices: np.ndarray) -> Optional[np.ndarray]:
        if len(prices) < FeatureEngineer.REQUIRED_PRICES:
            return None
        p       = prices.astype(float)
        returns = np.diff(p) / (p[:-1] + 1e-10)   # 48 عنصراً

        def safe_ret_mean(n):
            return returns[-n:].mean() if len(returns) >= n else returns.mean()

        def safe_ret_std(n):
            return returns[-n:].std() if len(returns) >= n else returns.std()

        features = [
            # ── عوائد قصيرة المدى ──────────────────────────────
            returns[-1],                             # F[0]  عائد آخر دورة
            safe_ret_mean(3),                        # F[1]  متوسط 3 دورات
            safe_ret_mean(6),                        # F[2]  متوسط 6 دورات
            safe_ret_mean(24),                       # F[3]  متوسط 24 دورة

            # ── نسب المتوسطات للسعر الحالي ──────────────────────
            p[-5:].mean()  / (p[-1] + 1e-10),       # F[4]
            p[-10:].mean() / (p[-1] + 1e-10),       # F[5]
            p[-24:].mean() / (p[-1] + 1e-10),       # F[6]
            p[-48:].mean() / (p[-1] + 1e-10),       # F[7]

            # ── زخم السعر ──────────────────────────────────────
            (p[-1] - p[-5])  / (p[-5]  + 1e-10),   # F[8]
            (p[-1] - p[-12]) / (p[-12] + 1e-10),   # F[9]
            (p[-1] - p[-24]) / (p[-24] + 1e-10),   # F[10]

            # ── تقلب السعر ─────────────────────────────────────
            safe_ret_std(10),                        # F[11]
            safe_ret_std(24),                        # F[12]

            # ── RSI (Wilder) ────────────────────────────────────
            FeatureEngineer._rsi(returns, 14),       # F[13]  مُعيَّر 0-1

            # ── Z-Score سعري ───────────────────────────────────
            (p[-1] - p[-20:].mean()) / (p[-20:].std() + 1e-10)
            if len(p) >= 20 else 0.0,               # F[14]

            # ── MACD-like ───────────────────────────────────────
            (p[-12:].mean() - p[-26:].mean()) / (p[-1] + 1e-10)
            if len(p) >= 26 else 0.0,               # F[15]

            # ── موضع السعر في النطاق (0=قاع، 1=قمة) ──────────
            (p[-1] - p[-24:].min()) / (p[-24:].max() - p[-24:].min() + 1e-10)
            if len(p) >= 24 else 0.5,               # F[16]

            # ── إشارة تقاطع المتوسطات ─────────────────────────
            1.0 if len(p) >= 20 and p[-5:].mean() > p[-20:].mean() else -1.0,  # F[17]

            # ── عائد 24 دورة (momentum طويل) ──────────────────
            (p[-1] - p[-24]) / (p[-24] + 1e-10)
            if len(p) >= 24 else 0.0,               # F[18]

            # ── عائد آخر دورة مُضخَّم ─────────────────────────
            returns[-1] * 100,                       # F[19]
        ]
        arr = np.array(features, dtype=float)
        if np.any(np.isnan(arr)) or np.any(np.isinf(arr)):
            return None
        return arr

    @staticmethod
    def _rsi(returns: np.ndarray, period: int = 14) -> float:
        """RSI بـ Wilder's smoothing — مُعيَّر بين 0 و1."""
        if len(returns) < period:
            return 0.5
        r      = returns[-period * 2:] if len(returns) >= period * 2 else returns
        gains  = np.where(r > 0, r, 0.0)
        losses = np.where(r < 0, -r, 0.0)
        gain   = gains[:period].mean()
        loss   = losses[:period].mean()
        for g, l in zip(gains[period:], losses[period:]):
            gain  = (gain  * (period - 1) + g) / period
            loss  = (loss  * (period - 1) + l) / period
        rs = gain / (loss + 1e-10)
        return (100 - 100 / (1 + rs)) / 100


class EnsemblePredictor:
    LOOKBACK         = 48     # ساعتان من البيانات الساعية
    RETRAIN_EVERY    = 50
    MIN_SAMPLES      = 30
    SIGNAL_THRESHOLD = 0.30   # 0.30% — مخفَّضة لاستجابة أسرع في المعادن الثمينة

    def __init__(self, security_id: str = None):
        self.security_id   = security_id
        self.price_history = deque(maxlen=1000)
        self.scaler        = MinMaxScaler() if SKLEARN_AVAILABLE else None
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
                logger.info(f"✅ {self.security_id}: نموذج تاريخي مُحمَّل")
            except Exception as e:
                logger.warning(f"فشل تحميل النموذج التاريخي: {e}")

    def _build_model(self):
        if not SKLEARN_AVAILABLE:
            return None
        return VotingRegressor([
            ("xgb", xgb.XGBRegressor(
                n_estimators=300, learning_rate=0.04, max_depth=6,
                subsample=0.8, colsample_bytree=0.8,
                objective="reg:squarederror", n_jobs=-1, verbosity=0,
            )),
            ("rf", RandomForestRegressor(
                n_estimators=200, max_depth=9, min_samples_leaf=3,
                n_jobs=-1, random_state=42,
            )),
            ("gb", GradientBoostingRegressor(
                n_estimators=200, learning_rate=0.04, max_depth=5,
                subsample=0.8, random_state=42,
            )),
        ])

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
            X, y   = [], []
            # مُتسق مع predict_signal: يمرر LOOKBACK+1 سعراً
            for i in range(self.LOOKBACK, len(prices) - 1):
                feats = FeatureEngineer.compute(prices[i - self.LOOKBACK: i + 1])
                if feats is not None:
                    X.append(feats)
                    y.append(prices[i + 1])

            X, y = np.array(X), np.array(y)
            if len(X) < self.MIN_SAMPLES:
                return

            scaler   = MinMaxScaler()
            y_scaled = scaler.fit_transform(y.reshape(-1, 1)).ravel()

            model = self._build_model()
            model.fit(X, y_scaled)

            preds = scaler.inverse_transform(model.predict(X).reshape(-1, 1)).ravel()
            rmse  = np.sqrt(mean_squared_error(y, preds))
            logger.info(f"ML retrained (live) | RMSE: {rmse:.4f} | Samples: {len(X)}")

            with self._lock:
                self.model      = model
                self.scaler     = scaler
                self.is_trained = True

        except Exception as e:
            logger.error(f"Training error: {e}")

    def predict_signal(self) -> str:
        """
        يقرأ current و predicted تحت نفس الـ lock — إصلاح M-08.
        يمرر LOOKBACK+1 سعراً مُتسقاً مع _train — إصلاح M-02.
        """
        with self._lock:
            if not self.price_history:
                return "HOLD"
            current = self.price_history[-1]
            if not self.is_trained or self.model is None:
                return "HOLD"
            try:
                prices = np.array(self.price_history)
                # LOOKBACK+1 سعراً = 49 سعراً = 48 عائداً (مُتسق مع _train)
                feats = FeatureEngineer.compute(prices[-(self.LOOKBACK + 1):])
                if feats is None:
                    return "HOLD"
                pred_scaled = self.model.predict(feats.reshape(1, -1))
                predicted   = float(self.scaler.inverse_transform(
                    pred_scaled.reshape(-1, 1)
                ).ravel()[0])
            except Exception as e:
                logger.error(f"Prediction error: {e}")
                return "HOLD"

        change_pct = (predicted - current) / (current + 1e-10) * 100
        logger.debug(f"ML: {current:.2f}→{predicted:.2f} ({change_pct:+.4f}%)")
        if change_pct > self.SIGNAL_THRESHOLD:
            return "BUY"
        elif change_pct < -self.SIGNAL_THRESHOLD:
            return "SELL"
        return "HOLD"

    # للتوافق مع الكود القديم إذا استُدعي مباشرةً
    def predict_next(self) -> Optional[float]:
        with self._lock:
            if not self.is_trained or self.model is None or not self.price_history:
                return None
            try:
                prices = np.array(self.price_history)
                feats  = FeatureEngineer.compute(prices[-(self.LOOKBACK + 1):])
                if feats is None:
                    return None
                pred_scaled = self.model.predict(feats.reshape(1, -1))
                return float(self.scaler.inverse_transform(
                    pred_scaled.reshape(-1, 1)
                ).ravel()[0])
            except Exception as e:
                logger.error(f"Prediction error: {e}")
                return None


class FallbackPredictor:
    def __init__(self):
        self.prices = deque(maxlen=50)
        self.kalman = KalmanFilter1D()

    def add_price(self, price: float):
        self.prices.append(self.kalman.update(price))

    def predict_next(self) -> Optional[float]:
        if not self.prices:
            return None
        return float(self.prices[-1])

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


def get_predictor(use_ml: bool = True, security_id: str = None):
    if use_ml and SKLEARN_AVAILABLE:
        return EnsemblePredictor(security_id=security_id)
    return FallbackPredictor()
