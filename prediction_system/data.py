from pathlib import Path
from typing import Protocol
import pandas as pd


class PriceRepository(Protocol):
    def hourly(self, security_id: str) -> pd.DataFrame: ...
    def daily(self, security_id: str) -> pd.DataFrame: ...


class PicklePriceRepository:
    """Read-only adapter over the project's existing datasets."""
    def __init__(self, root: str = "data"):
        self.root = Path(root)

    def _load(self, security_id: str, frequency: str) -> pd.DataFrame:
        path = self.root / f"{security_id}_{frequency}.pkl"
        frame = pd.read_pickle(path)
        if isinstance(frame, pd.Series):
            frame = frame.to_frame("price")
        frame = frame.copy()
        frame.columns = [str(c).lower() for c in frame.columns]
        price_col = next((c for c in ("price", "close", "usd_per_kg", "value") if c in frame.columns), None)
        if price_col is None:
            numeric = frame.select_dtypes(include="number").columns.tolist()
            if not numeric:
                raise ValueError(f"No numeric price column in {path}")
            price_col = numeric[0]
        return frame.rename(columns={price_col: "price"}).dropna(subset=["price"])

    def hourly(self, security_id: str) -> pd.DataFrame:
        return self._load(security_id, "hourly")

    def daily(self, security_id: str) -> pd.DataFrame:
        return self._load(security_id, "daily")
