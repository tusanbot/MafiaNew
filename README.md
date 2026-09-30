# Mafia Bot

بازنویسی کامل ربات مافیا با Python، aiogram 3 و معماری ماژولار، با هدف اجرای پایدار روی Railway.

## اصول معماری
- Core بازی مستقل از Telegram و Runtime
- PostgreSQL برای داده‌های پایدار
- aiogram 3 برای Telegram Bot API
- FastAPI برای health check
- Profile به‌جای Subscription/Wallet
- سناریوها و نقش‌ها به‌صورت قابل توسعه
- هر گروه یک فضای بازی مستقل
- مدیریت بازی با state machine
- لاگ و audit برای رویدادهای مهم

## Railway
Start command: `python -m app`
متغیرهای اصلی در `.env.example` مشخص شده‌اند. توکن داخل Git ذخیره نشود.
