# Mafia Bot

ربات بازی مافیا با Python، aiogram 3 و معماری ماژولار، با هدف اجرای پایدار روی Railway.

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

<!-- sync-check: 2026-10-02 -->


Rich Message transport is globally enabled with an automatic Bot API fallback.

<!-- rich-transport-sync-2 -->

<!-- rich-menu-navigation-sync -->


<!-- sync marker: 2026-10-03 -->
