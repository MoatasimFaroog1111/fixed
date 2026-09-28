from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import xml.etree.ElementTree as ET

import requests


class LivePriceProvider(Protocol):
    def usd_per_kg(self, security_id: str) -> float: ...


@dataclass(frozen=True)
class BullionVaultMarketPriceProvider:
    """Read the public cached BullionVault London order board in USD/kg.

    BullionVault's market XML API expresses order limits per kilogram.  We use
    the midpoint between the best bid and best ask as the live reference price.
    No trading/login credentials are used by this adapter.
    """

    endpoint: str = "https://www.bullionvault.com/view_market_xml.do"
    timeout_seconds: float = 20.0

    SUPPORTED = frozenset(("AUXLN", "AGXLN", "PTXLN", "PDXLN"))

    def usd_per_kg(self, security_id: str) -> float:
        if security_id not in self.SUPPORTED:
            raise ValueError(f"Unsupported BullionVault security: {security_id}")

        response = requests.get(
            self.endpoint,
            params={
                "considerationCurrency": "USD",
                "securityId": security_id,
                "quantity": "0.001",
                "marketWidth": "1",
            },
            timeout=self.timeout_seconds,
            headers={"User-Agent": "fixed-metal-prediction/1.0"},
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        pitch = root.find(f".//pitch[@securityId='{security_id}'][@considerationCurrency='USD']")
        if pitch is None:
            raise RuntimeError(f"BullionVault returned no USD market for {security_id}")

        bids = [float(node.attrib["limit"]) for node in pitch.findall("./buyPrices/price") if "limit" in node.attrib]
        asks = [float(node.attrib["limit"]) for node in pitch.findall("./sellPrices/price") if "limit" in node.attrib]
        if not bids or not asks:
            raise RuntimeError(f"BullionVault market depth incomplete for {security_id}")

        best_bid = max(bids)
        best_ask = min(asks)
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            raise RuntimeError(f"Invalid BullionVault market for {security_id}: bid={best_bid}, ask={best_ask}")
        return (best_bid + best_ask) / 2.0
