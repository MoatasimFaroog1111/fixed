"""Unit tests for parser.py — XML parsing utilities."""
import xml.etree.ElementTree as ET

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import (
    _safe_float,
    parse_market,
    parse_balance,
    parse_orders,
    best_bid,
    best_ask,
    mid_price,
)


# ─── _safe_float ───────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_valid_integer(self):
        assert _safe_float("42") == 42.0

    def test_valid_float(self):
        assert _safe_float("3.14") == 3.14

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_empty_string_returns_default(self):
        assert _safe_float("") == 0.0

    def test_invalid_string_returns_default(self):
        assert _safe_float("abc") == 0.0

    def test_custom_default(self):
        assert _safe_float("bad", default=-1.0) == -1.0

    def test_negative_value(self):
        assert _safe_float("-5.5") == -5.5

    def test_zero(self):
        assert _safe_float("0") == 0.0


# ─── parse_market ──────────────────────────────────────────────────────────────

class TestParseMarket:
    def test_empty_root(self):
        root = ET.fromstring("<marketData></marketData>")
        assert parse_market(root) == []

    def test_single_pitch_with_bids_and_asks(self):
        xml = """
        <marketData>
          <pitch securityId="AUXLN" considerationCurrency="USD">
            <buyPrices>
              <price quantity="0.5" limit="1950.00"/>
              <price quantity="1.0" limit="1948.50"/>
            </buyPrices>
            <sellPrices>
              <price quantity="0.3" limit="1955.00"/>
            </sellPrices>
          </pitch>
        </marketData>
        """
        root = ET.fromstring(xml)
        result = parse_market(root)
        assert len(result) == 1
        entry = result[0]
        assert entry["securityId"] == "AUXLN"
        assert entry["currency"] == "USD"
        assert len(entry["bids"]) == 2
        assert entry["bids"][0]["limit"] == 1950.00
        assert entry["bids"][0]["quantity"] == 0.5
        assert len(entry["asks"]) == 1
        assert entry["asks"][0]["limit"] == 1955.00

    def test_pitch_without_buy_or_sell(self):
        xml = """
        <marketData>
          <pitch securityId="AGXLN" considerationCurrency="EUR">
          </pitch>
        </marketData>
        """
        root = ET.fromstring(xml)
        result = parse_market(root)
        assert len(result) == 1
        assert result[0]["bids"] == []
        assert result[0]["asks"] == []

    def test_multiple_pitches(self):
        xml = """
        <marketData>
          <pitch securityId="AUXLN" considerationCurrency="USD">
            <buyPrices><price quantity="1" limit="1950"/></buyPrices>
            <sellPrices></sellPrices>
          </pitch>
          <pitch securityId="AGXLN" considerationCurrency="USD">
            <buyPrices></buyPrices>
            <sellPrices><price quantity="2" limit="25.5"/></sellPrices>
          </pitch>
        </marketData>
        """
        root = ET.fromstring(xml)
        result = parse_market(root)
        assert len(result) == 2
        assert result[0]["securityId"] == "AUXLN"
        assert result[1]["securityId"] == "AGXLN"


# ─── parse_balance ─────────────────────────────────────────────────────────────

class TestParseBalance:
    def test_none_root(self):
        result = parse_balance(None)
        assert "USD" in result
        assert result["USD"]["available"] == 0.0

    def test_empty_root(self):
        root = ET.fromstring("<balances></balances>")
        result = parse_balance(root)
        assert "USD" in result
        assert result["USD"]["available"] == 0.0

    def test_cash_position(self):
        xml = """
        <balances>
          <clientPosition securityId="USD" classNarrative="Cash"
            available="5000.50" total="5000.50" totalValuation="5000.50"/>
        </balances>
        """
        root = ET.fromstring(xml)
        result = parse_balance(root)
        assert result["USD"]["available"] == 5000.50
        assert result["USD"]["total"] == 5000.50
        assert result["USD"]["class"] == "CASH"

    def test_multiple_positions(self):
        xml = """
        <balances>
          <clientPosition securityId="USD" classNarrative="Cash"
            available="1000" total="1000" totalValuation="1000"/>
          <clientPosition securityId="AUXLN" classNarrative="Metal"
            available="0.1" total="0.1" totalValuation="195"/>
        </balances>
        """
        root = ET.fromstring(xml)
        result = parse_balance(root)
        assert "USD" in result
        assert "AUXLN" in result
        assert result["AUXLN"]["available"] == 0.1

    def test_currency_class_detection(self):
        xml = """
        <balances>
          <clientPosition securityId="EUR" classNarrative="Currency"
            available="200" total="200" totalValuation="220"/>
        </balances>
        """
        root = ET.fromstring(xml)
        result = parse_balance(root)
        assert "EUR" in result
        assert result["EUR"]["class"] == "CURRENCY"


# ─── parse_orders ──────────────────────────────────────────────────────────────

class TestParseOrders:
    def test_empty_orders(self):
        root = ET.fromstring("<orders></orders>")
        assert parse_orders(root) == []

    def test_single_order(self):
        xml = """
        <orders>
          <order orderId="123" clientTransRef="ref1" actionIndicator="B"
            securityId="AUXLN" considerationCurrency="USD"
            quantity="0.5" quantityMatched="0.0" limit="1950.00"
            statusCode="O" typeCode="L" orderTime="2024-01-01T12:00:00"
            totalConsideration="975.00" totalCommission="1.50"/>
        </orders>
        """
        root = ET.fromstring(xml)
        result = parse_orders(root)
        assert len(result) == 1
        order = result[0]
        assert order["orderId"] == "123"
        assert order["action"] == "B"
        assert order["securityId"] == "AUXLN"
        assert order["quantity"] == 0.5
        assert order["limit"] == 1950.00
        assert order["totalCommission"] == 1.50

    def test_multiple_orders(self):
        xml = """
        <orders>
          <order orderId="1" actionIndicator="B" securityId="AUXLN"
            considerationCurrency="USD" quantity="1" quantityMatched="0"
            limit="1950" statusCode="O" typeCode="L" orderTime="t1"
            totalConsideration="1950" totalCommission="2" clientTransRef="r1"/>
          <order orderId="2" actionIndicator="S" securityId="AGXLN"
            considerationCurrency="USD" quantity="5" quantityMatched="5"
            limit="25" statusCode="F" typeCode="L" orderTime="t2"
            totalConsideration="125" totalCommission="0.5" clientTransRef="r2"/>
        </orders>
        """
        root = ET.fromstring(xml)
        result = parse_orders(root)
        assert len(result) == 2
        assert result[1]["action"] == "S"
        assert result[1]["statusCode"] == "F"


# ─── best_bid / best_ask / mid_price ──────────────────────────────────────────

class TestBestBidAskMid:
    @pytest.fixture
    def market_data(self):
        return [
            {
                "securityId": "AUXLN",
                "currency": "USD",
                "bids": [
                    {"action": "B", "quantity": 1.0, "limit": 1950.0},
                    {"action": "B", "quantity": 0.5, "limit": 1948.0},
                ],
                "asks": [
                    {"action": "S", "quantity": 0.3, "limit": 1955.0},
                    {"action": "S", "quantity": 1.0, "limit": 1960.0},
                ],
            },
            {
                "securityId": "AGXLN",
                "currency": "USD",
                "bids": [],
                "asks": [{"action": "S", "quantity": 5.0, "limit": 25.0}],
            },
        ]

    def test_best_bid(self, market_data):
        assert best_bid(market_data, "AUXLN", "USD") == 1950.0

    def test_best_ask(self, market_data):
        assert best_ask(market_data, "AUXLN", "USD") == 1955.0

    def test_mid_price(self, market_data):
        assert mid_price(market_data, "AUXLN", "USD") == (1950.0 + 1955.0) / 2

    def test_best_bid_no_bids(self, market_data):
        assert best_bid(market_data, "AGXLN", "USD") is None

    def test_best_ask_no_asks_returns_none(self):
        data = [{"securityId": "X", "currency": "USD", "bids": [{"limit": 10}], "asks": []}]
        assert best_ask(data, "X", "USD") is None

    def test_mid_price_only_bid(self):
        data = [{"securityId": "X", "currency": "USD", "bids": [{"limit": 100}], "asks": []}]
        assert mid_price(data, "X", "USD") == 100

    def test_mid_price_only_ask(self, market_data):
        assert mid_price(market_data, "AGXLN", "USD") == 25.0

    def test_nonexistent_security(self, market_data):
        assert best_bid(market_data, "PTXLN", "USD") is None
        assert best_ask(market_data, "PTXLN", "USD") is None
        assert mid_price(market_data, "PTXLN", "USD") is None
