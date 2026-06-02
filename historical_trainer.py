"""
historical_trainer.py v2
التغييرات:
  - يستورد FeatureEngineer من ml_predictor.py بدلاً من تعريف features خاصة به
  - LOOKBACK=48 موحَّد مع EnsemblePredictor — يُنهي مشكلة C-01
  - نفس build_dataset الدقيقة المستخدمة في _train الحي
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
logger = logging.getLogger("Trainer")

DATA_DIR   = "data"
MODELS_DIR = "models"
os.makedirs(MODELS_DIR, exist_ok=True)

try:
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor, VotingRegressor
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.metrics import mean_squared_error
    from sklearn.model_selection import train_test_split
    import xgboost as xgb
    SKLEARN_OK = True
except ImportError:
    logger.error("شغّل: pip install scikit-learn xgboost")
    SKLEARN_OK = False

# ← استيراد FeatureEngineer الموحَّد بدلاً من تعريف build_features محلياً
from ml_predictor import FeatureEngineer, EnsemblePredictor
from data_fetcher import load_prices

LOOKBACK = EnsemblePredictor.LOOKBACK   # 48 — مُزامَن تلقائياً


def build_dataset(prices: np.ndarray):
    """نفس الخوارزمية المستخدمة في EnsemblePredictor._train."""
    X, y = [], []
    for i in range(LOOKBACK, len(prices) - 1):
        # LOOKBACK+1 سعراً = 49 = نفس ما يُمرَّر في predict_signal
        feats = FeatureEngineer.compute(prices[i - LOOKBACK: i + 1])
        if feats is not None:
            X.append(feats)
            y.append(prices[i + 1])
    return np.array(X), np.array(y)


def build_model():
    # نفس بنية EnsemblePredictor._build_model تماماً حتى لا يختلف التدريب التاريخي عن الحي.
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


def train_metal(security_id: str):
    logger.info(f"{'='*50}")
    logger.info(f"  {security_id}")

    # أولوية: ساعية ← يومية
    prices = load_prices(security_id, "hourly")
    source = "ساعية"
    if prices is None or len(prices) < LOOKBACK + 50:
        prices = load_prices(security_id, "daily")
        source = "يومية"

    if prices is None or len(prices) < LOOKBACK + 50:
        logger.warning(f"  لا بيانات كافية لـ {security_id}")
        return

    logger.info(f"  مصدر: {source} | {len(prices):,} عينة")

    X, y = build_dataset(prices)
    if len(X) < 50:
        logger.warning(f"  عينات غير كافية: {len(X)}")
        return

    logger.info(f"  عينات التدريب: {len(X):,}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, shuffle=False
    )

    scaler   = MinMaxScaler()
    y_scaled = scaler.fit_transform(y_train.reshape(-1, 1)).ravel()

    logger.info("  جاري التدريب...")
    model = build_model()
    model.fit(X_train, y_scaled)

    # تقييم
    p_train = scaler.inverse_transform(model.predict(X_train).reshape(-1, 1)).ravel()
    p_test  = scaler.inverse_transform(model.predict(X_test).reshape(-1, 1)).ravel()

    rmse_train = np.sqrt(mean_squared_error(y_train, p_train))
    rmse_test  = np.sqrt(mean_squared_error(y_test,  p_test))
    mae_pct    = np.mean(np.abs(y_test - p_test)) / np.mean(y_test) * 100

    logger.info(f"  RMSE تدريب:  {rmse_train:.4f}")
    logger.info(f"  RMSE اختبار: {rmse_test:.4f}")
    logger.info(f"  خطأ نسبي:   {mae_pct:.3f}%")

    # حفظ
    with open(os.path.join(MODELS_DIR, f"{security_id}_model.pkl"),  "wb") as f:
        pickle.dump(model,  f)
    with open(os.path.join(MODELS_DIR, f"{security_id}_scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)

    logger.info(f"  ✅ محفوظ في models/{security_id}_model.pkl")


if __name__ == "__main__":
    if not SKLEARN_OK:
        exit(1)

    metals  = ["AUXLN", "AGXLN", "PTXLN", "PDXLN"]
    trained = 0
    for sid in metals:
        daily  = os.path.exists(os.path.join(DATA_DIR, f"{sid}_daily.pkl"))
        hourly = os.path.exists(os.path.join(DATA_DIR, f"{sid}_hourly.pkl"))
        if daily or hourly:
            train_metal(sid)
            trained += 1
        else:
            logger.warning(f"لا توجد بيانات لـ {sid} — شغّل data_fetcher.py أولاً")

    logger.info("=" * 50)
    if trained > 0:
        logger.info(f"  ✅ اكتمل تدريب {trained} نموذج")
        logger.info("  الخطوة التالية: python run_all_bots.py")
    else:
        logger.info("  ❌ لم يُدرَّب أي نموذج — شغّل data_fetcher.py أولاً")
    logger.info("=" * 50)
