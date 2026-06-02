Guardian Telegram Cockpit v4 Installation

1) انسخ telegram_control_v4.py إلى مجلد المشروع باسم telegram_control.py
2) انسخ authorized_users.json إلى نفس المجلد
3) ضع Telegram User ID الخاص بك داخل owners في authorized_users.json
4) تأكد أن .env يحتوي على:
   TG_TOKEN_SILVER أو TG_TOKEN
   TG_CHAT_ID
   BV_USERNAME
   BV_PASSWORD
5) شغل:
   python telegram_control.py
6) افتح تيليجرام وأرسل:
   /start

Manual Trading:
/buy silver 0.01
/sell palladium 0.01

مهم:
- لا تضغط Confirm إلا بعد مراجعة السعر والكمية.
- أوقف أي عملية أخرى تستخدم نفس Telegram Token لتجنب 409 Conflict.
