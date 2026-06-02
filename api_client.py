"""
BullionVault XML API Client v2
التغييرات:
  - إضافة retry تلقائي واحد بعد انتهاء الجلسة في _get_xml / _post_xml
  - إضافة timeout لطلبات login
"""
import time
import requests
import xml.etree.ElementTree as ET
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class BullionVaultAPI:
    BASE_URL    = "https://www.bullionvault.com"
    LOGIN_CHECK = "/secure/j_security_check"
    LOGIN_PAGE  = "/secure/login.do"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session  = requests.Session()
        self.session.headers.update({
            "User-Agent":   "BullionVault-TradingBot/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        self._logged_in = False

    def login(self) -> bool:
        try:
            self.session.get(self.BASE_URL + self.LOGIN_PAGE, timeout=15)
            response = self.session.post(
                self.BASE_URL + self.LOGIN_CHECK,
                data={"j_username": self.username, "j_password": self.password},
                allow_redirects=True,
                timeout=15,
            )
            final_url = getattr(response, "url", "") or ""
            body = (response.text or "")[:500].lower()
            logged_in = (
                response.status_code == 200
                and "JSESSIONID" in self.session.cookies
                and "login" not in final_url.lower()
                and "j_security_check" not in final_url.lower()
                and "password" not in body
            )
            if logged_in:
                self._logged_in = True
                logger.info("Login successful.")
                return True
            self._logged_in = False
            logger.error(f"Login failed. Status: {response.status_code} URL={final_url}")
            return False
        except Exception as e:
            logger.exception(f"Login error: {e}")
            return False

    def _get_xml(self, endpoint: str, params: dict = None) -> Optional[ET.Element]:
        if not self._logged_in:
            if not self.login():
                return None
        url = self.BASE_URL + endpoint
        for attempt in range(2):   # محاولتان: الأولى عادية، الثانية بعد إعادة تسجيل الدخول
            try:
                response = self.session.get(url, params=params, timeout=15)
                response.raise_for_status()
                return ET.fromstring(response.text)
            except ET.ParseError:
                # BullionVault أرجع HTML بدل XML → الجلسة منتهية
                if attempt == 0:
                    logger.warning(f"XML parse error [{endpoint}] — إعادة تسجيل الدخول...")
                    self._logged_in = False
                    if not self.login():
                        return None
                    # تكرار الحلقة بجلسة جديدة
                else:
                    logger.error(f"XML parse error [{endpoint}] بعد إعادة التسجيل — التخلي.")
                    return None
            except Exception as e:
                logger.exception(f"GET request failed [{endpoint}]: {e}")
                return None
        return None

    def _post_xml(self, endpoint: str, data: dict = None) -> Optional[ET.Element]:
        if not self._logged_in:
            if not self.login():
                return None
        url = self.BASE_URL + endpoint
        for attempt in range(2):
            try:
                response = self.session.post(url, data=data, timeout=15)
                response.raise_for_status()
                return ET.fromstring(response.text)
            except ET.ParseError:
                if attempt == 0:
                    logger.warning(f"XML parse error [{endpoint}] — إعادة تسجيل الدخول...")
                    self._logged_in = False
                    if not self.login():
                        return None
                else:
                    logger.error(f"XML parse error [{endpoint}] بعد إعادة التسجيل — التخلي.")
                    return None
            except Exception as e:
                logger.exception(f"POST request failed [{endpoint}]: {e}")
                return None
        return None

    def view_market(self, currency: str = "", security_id: str = "",
                    quantity: float = 0.001, market_width: int = 5) -> Optional[ET.Element]:
        return self._get_xml("/secure/api/v2/view_market_xml.do", {
            "considerationCurrency": currency,
            "securityId":            security_id,
            "quantity":              quantity,
            "marketWidth":           market_width,
        })

    def view_balance(self, simple: bool = True) -> Optional[ET.Element]:
        return self._get_xml("/secure/api/v2/view_balance_xml.do",
                             {"simple": str(simple).lower()})

    def view_orders(self, status: str = "OPEN", security_id: str = "",
                    currency: str = "") -> Optional[ET.Element]:
        return self._get_xml("/secure/api/v2/view_orders_xml.do", {
            "status":                status,
            "securityId":            security_id,
            "considerationCurrency": currency,
        })

    def view_single_order(self, order_id: str) -> Optional[ET.Element]:
        return self._get_xml("/secure/api/v2/view_single_order_xml.do",
                             {"orderId": order_id})

    def place_order(self, action: str, security_id: str, currency: str,
                    quantity: float, limit: int, type_code: str = "TIL_CANCEL",
                    client_ref: str = None, good_until: str = "") -> Optional[ET.Element]:
        if client_ref is None:
            client_ref = f"BOT{int(time.time() * 1000)}"
        return self._post_xml("/secure/api/v2/place_order_xml.do", {
            "actionIndicator":       action,
            "considerationCurrency": currency,
            "securityId":            security_id,
            "quantity":              round(quantity, 3),
            "limit":                 int(limit),
            "typeCode":              type_code,
            "clientTransRef":        client_ref,
            "confirmed":             "true",
            "goodUntil":             good_until,
        })

    def cancel_order(self, order_id: str) -> Optional[ET.Element]:
        return self._post_xml("/secure/api/v2/cancel_order_xml.do", {
            "orderId":   order_id,
            "confirmed": "true",
        })

    def view_weight_unit(self) -> Optional[ET.Element]:
        return self._get_xml("/secure/api/v2/view_weight_unit_xml.do")

    def update_weight_unit(self, unit: str = "KG") -> Optional[ET.Element]:
        return self._post_xml("/secure/api/v2/update_weight_unit_xml.do",
                              {"newUnitOfWeight": unit})
