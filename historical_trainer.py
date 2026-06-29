"""
historical_trainer.py v3 — ULTRA PRECISION
التحسينات:
  P1: تدريب تصنيف (BUY/SELL/HOLD) بدلاً من regression
  P3: Stacking: XGB + LGBM + RF + GB مع LogisticRegression meta-learner
  P6: Walk-Forward تحقق بدلاً من random shuffle
  P2: 60+ features من FeatureEngineer v8
شغّله بعد data_fetcher.py: python historical_trainer.py
"""
import os
import pickle
import numpy as np
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s"
)
logger = logging.getLogger("Trainer-v3")

DATA_DIR   = "data"
MODELS_DIR = "models"
os.makedirs(MODELS_DIR, exist_ok=True)

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score, classification_report
    SKLEARN_OK = True
except ImportError:
    logger.error("شغّل: pip install scikit-learn xgboost lightgbm")
    SKLEARN_OK = False

from ml_predictor import (
    FeatureEngineer,
    EnsemblePredictor,
    _build_classifier,
    _make_labels,
)
from data_fetcher import load_prices

LOOKBACK = EnsemblePredictor.LOOKBACK  # 48


def build_dataset(prices: np.ndarray):
    """
    بناء dataset تصنيف.
    X: 60+ features لكل سعر
    y: label للسعر التالي (0=HOLD, 1=BUY, 2=SELL)
    """
    X, raw_prices = [], []
    for i in range(LOOKBACK, len(prices) - 1):
        feats = FeatureEngineer.compute(prices[i - LOOKBACK: i + 1])
        if feats is not None:
            X.append(feats)
            raw_prices.append(prices[i + 1])

    if not X:
        return np.array([]), np.array([])

    X = np.array(X)
    raw_arr = np.array(raw_prices + [raw_prices[-1]])
    # خذ labels للسعر i+1 (اتجاه الحركة التالية)
    y = _make_labels(raw_arr)[:-1]
    return X, y


def train_metal(security_id: str):
    logger.info(f"{'='*55}")
    logger.info(f"  تدريب: {security_id}")

    # أولوية: ساعية → يومية
    prices = load_prices(security_id, "hourly")
    source = "ساعية"
    if prices is None or len(prices) < LOOKBACK + 100:
        prices = load_prices(security_id, "daily")
        source = "يومية"

    if prices is None or len(prices) < LOOKBACK + 100:
        logger.warning(f"  لا بيانات كافية لـ {security_id}")
        return

    logger.info(f"  مصدر: {source} | {len(prices):,} نقطة")

    X, y = build_dataset(prices)
    if len(X) < 100:
        logger.warning(f"  عينات غير كافية: {len(X)}")
        return

    logger.info(f"  عينات: {len(X):,} | features: {X.shape[1]}")
    unique, counts = np.unique(y, return_counts=True)
    label_names = {0: "HOLD", 1: "BUY", 2: "SELL"}
    for lbl, cnt in zip(unique, counts):
        logger.info(f"    {label_names.get(lbl, lbl)}: {cnt} ({cnt/len(y):.1%})")

    # P6: Walk-Forward (75/25, بدون shuffle)
    split_idx = int(len(X) * 0.75)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    # StandardScaler
    scaler    = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    logger.info("  جاري بناء Stacking Classifier (XGB+LGBM+RF+GB)...")
    model = _build_classifier()
    model.fit(X_train_s, y_train)

    y_pred_train = model.predict(X_train_s)
    y_pred_test  = model.predict(X_test_s)

    acc_train = accuracy_score(y_train, y_pred_train)
    acc_test  = accuracy_score(y_test,  y_pred_test)

    logger.info(f"  ✅ Train Accuracy : {acc_train:.1%}")
    logger.info(f"  ✅ Test  Accuracy : {acc_test:.1%}")
    logger.info("```")
    logger.info(classification_report(
        y_test, y_pred_test,
        target_names=["HOLD", "BUY", "SELL"],
        zero_division=0
    ))
    logger.info("```")

    # حفظ
    model_path  = os.path.join(MODELS_DIR, f"{security_id}_model.pkl")
    scaler_path = os.path.join(MODELS_DIR, f"{security_id}_scaler.pkl")
    with open(model_path,  "wb") as f: pickle.dump(model,  f)
    with open(scaler_path, "wb") as f: pickle.dump(scaler, f)

    logger.info(f"  ✅ محفوظ في models/{security_id}_model.pkl")


if __name__ == "__main__":
    if not SKLEARN_OK:
        exit(1)

    metals  = ["AUXLN", "AGXLN", "PTXLN", "PDXLN")
    trained = 0
    for sid in metals:
        daily  = os.path.exists(os.path.join(DATA_DIR, f"{sid}_daily.pkl"))
        hourly = os.path.exists(os.path.join(DATA_DIR, f"{sid}_hourly.pkl"))
        if daily or hourly:
            try:
                train_metal(sid)
                trained += 1
            except Exception as e:
                logger.error(f"خطأ في تدريب {sid}: {e}", exc_info=True)
        else:
            logger.warning(f"لا توجد بيانات لـ {sid} — شغّل data_fetcher.py أولاً")

    logger.info("=" * 55)
    if trained > 0:
        logger.info(f"  ✅ اكتمل تدريب {trained} نموذج")
        logger.info("  الخطوة التالية: python run_all_bots.py")
    else:
        logger.info("  ❌ لم يُدرَّب أي نموذج — شغّل data_fetcher.py أولاً")
    logger.info("=" * 55)
