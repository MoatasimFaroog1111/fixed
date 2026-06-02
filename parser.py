"""
XML Response Parser for BullionVault API v2
التغييرات:
  - إضافة safe_float لتجنب ValueError عند تحويل القيم
"""
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

CASH_CLASSES = {"CASH", "CURRENCY"}
CURRENCY_IDS = {"USD", "EUR", "GBP", "CHF", "AUD", "JPY", "CAD", "SGD"}


def _safe_float(value, default: float = 0.0) -> float:
    """تحويل آمن لـ float — لا يرمي استثناءً."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_market(root: ET.Element) -> List[Dict]:
    results = []
    for pitch in root.iter("pitch"):
        security_id = pitch.attrib.get("securityId")
        currency    = pitch.attrib.get("considerationCurrency")
        buys = [
            {"action": "B",
             "quantity": _safe_float(p.attrib.get("quantity")),
             "limit":    _safe_float(p.attrib.get("limit"))}
            for p in (pitch.find("buyPrices") or [])
        ]
        sells = [
            {"action": "S",
             "quantity": _safe_float(p.attrib.get("quantity")),
             "limit":    _safe_float(p.attrib.get("limit"))}
            for p in (pitch.find("sellPrices") or [])
        ]
        results.append({
            "securityId": security_id,
            "currency":   currency,
            "bids":       buys,
            "asks":       sells,
        })
    return results


def parse_balance(root: ET.Element) -> Dict:
    positions = {}

    if root is None:
        return {"USD": {"available": 0.0, "total": 0.0, "class": "CASH", "valuation_usd": 0.0}}

    for pos in root.iter("clientPosition"):
        sid = pos.attrib.get("securityId", "")
        cls = pos.attrib.get("classNarrative", "").upper()
        sid_key = sid.upper()
        entry = {
            "available":     _safe_float(pos.attrib.get("available")),
            "total":         _safe_float(pos.attrib.get("total")),
            "class":         cls,
            "valuation_usd": _safe_float(pos.attrib.get("totalValuation")),
        }
        positions[sid] = entry

        # احتفظ بكل عملة بمفتاحها الحقيقي فقط. لا ننسخ EUR/GBP إلى USD.
        if cls in CASH_CLASSES or sid_key in CURRENCY_IDS:
            positions[sid_key] = entry

    positions.setdefault("USD", {
        "available": 0.0, "total": 0.0,
        "class": "CASH", "valuation_usd": 0.0,
    })

    return positions


def parse_orders(root: ET.Element) -> List[Dict]:
    orders = []
    for order in root.iter("order"):
        orders.append({
            "orderId":            order.attrib.get("orderId"),
            "clientTransRef":     order.attrib.get("clientTransRef"),
            "action":             order.attrib.get("actionIndicator"),
            "securityId":         order.attrib.get("securityId"),
            "currency":           order.attrib.get("considerationCurrency"),
            "quantity":           _safe_float(order.attrib.get("quantity")),
            "quantityMatched":    _safe_float(order.attrib.get("quantityMatched")),
            "limit":              _safe_float(order.attrib.get("limit")),
            "statusCode":         order.attrib.get("statusCode"),
            "typeCode":           order.attrib.get("typeCode"),
            "orderTime":          order.attrib.get("orderTime"),
            "totalConsideration": _safe_float(order.attrib.get("totalConsideration")),
            "totalCommission":    _safe_float(order.attrib.get("totalCommission")),
        })
    return orders


def best_bid(market_data: List[Dict], security_id: str, currency: str) -> Optional[float]:
    for m in market_data:
        if m["securityId"] == security_id and m["currency"] == currency:
            if m["bids"]:
                return max(b["limit"] for b in m["bids"])
    return None


def best_ask(market_data: List[Dict], security_id: str, currency: str) -> Optional[float]:
    for m in market_data:
        if m["securityId"] == security_id and m["currency"] == currency:
            if m["asks"]:
                return min(a["limit"] for a in m["asks"])
    return None


def mid_price(market_data: List[Dict], security_id: str, currency: str) -> Optional[float]:
    bid = best_bid(market_data, security_id, currency)
    ask = best_ask(market_data, security_id, currency)
    if bid and ask:
        return (bid + ask) / 2
    return bid or ask
