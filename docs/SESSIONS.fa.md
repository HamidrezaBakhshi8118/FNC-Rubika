# راهنمای سشن و چندسشنی fnc-rubika

## اصل طراحی

هر `Client("نام")` یک حساب محلی مستقل است. نام سشن یک نام انسانی است، نه
توکن، شماره تلفن یا شناسهٔ روبیکا. برای هر نام، این موارد جدا نگهداری می‌شوند:

| مورد | محل / رفتار |
| --- | --- |
| سشن احراز هویت | در جدول رمزگذاری‌شدهٔ همان سشن |
| inbox و cursor دریافت | مستقل؛ تأیید یک حساب روی حساب دیگر اثر ندارد |
| outbox و کلید idempotency | مستقل؛ ارسال‌های دو حساب هرگز با هم مخلوط نمی‌شوند |
| اتصال HTTP و WebSocket | یک transport مستقل پس از باز شدن کلاینت |
| کلید رمزگذاری | برای هر فایل از OS keyring گرفته می‌شود؛ نام حساب keyring از مسیر فایل hash می‌شود |

در ویندوز، محل پیش‌فرض داده‌ها این است:

```text
%LOCALAPPDATA%\fnc-rubika\<session-name>.sqlite3
```

فایل SQLite شامل دادهٔ برنامه است، اما هر رکورد حساس با AES-256-GCM رمزگذاری
و احراز اصالت می‌شود. کلید در خود فایل SQLite یا repository قرار نمی‌گیرد.

## ساخت و ورود چند سشن از ترمینال

برای هر حساب فقط یک‌بار ورود کنید. در هر اجرا شماره را دقیقاً به شکل `+989…`
و سپس OTP همان حساب وارد کنید:

```powershell
fnc-rubika login personal
fnc-rubika login business
fnc-rubika login test
```

هیچ شماره، OTP، cookie یا token را در source code، `README`، issue یا commit
قرار ندهید. اگر سشنی منقضی شد، دقیقاً همان دستور را با همان نام اجرا کنید تا
فایل همان سشن به‌روزرسانی شود.

## شکل پیشنهادی برای یک حساب

`async_client()` برای بیشتر کاربران لازم نیست. خود `Client` یک context manager
async است و سرویس‌ها را مستقیم ارائه می‌کند:

```python
from fnc_rubika import Client


async def main() -> None:
    async with Client("personal") as client:
        message = await client.messages.send("chat-id", "سلام")
        print(message.message_id)
```

ورود اول را با CLI انجام دهید. اگر برنامهٔ خط فرمان خودتان دارید و می‌خواهید
ورود را در همان برنامه انجام دهید، هیچ مقدار حساسی را hard-code نکنید:

```python
from fnc_rubika import Client


async def first_login() -> None:
    client = Client("personal")
    try:
        await client.login_interactive()  # شماره و OTP را از ترمینال می‌پرسد
    finally:
        await client.aclose()
```

### `async_client()` دقیقاً چیست؟

این متد شیء پایین‌سطح `AsyncClient` را برمی‌گرداند؛ همان شیئی که `Client` درون
خود استفاده می‌کند. تنها برای سازگاری با integrationهای پیشرفته یا زمانی که
کدی پیشاپیش `AsyncClient` می‌خواهد به آن نیاز دارید. در کد عادی از آن استفاده
نکنید:

```python
# لازم نیست
app = Client("personal").async_client()

# صحیح و ساده
async with Client("personal") as client:
    await client.messages.send("chat-id", "سلام")
```

## باز کردن هم‌زمان چند حساب

برای اجرای چند سشن در یک process از `SessionPool` استفاده کنید. pool فقط
چرخهٔ عمر را مشترک می‌کند؛ داده و اتصال هیچ عضوی را با دیگری به اشتراک
نمی‌گذارد.

```python
from fnc_rubika import SessionPool


async def main() -> None:
    async with SessionPool("personal", "business") as sessions:
        personal = sessions["personal"]
        business = sessions.get("business")

        await personal.messages.send("personal-chat", "پیام حساب شخصی")
        await business.messages.send("business-chat", "پیام حساب کاری")
```

`SessionPool` تنها سشن‌هایی را باز می‌کند که از قبل login شده‌اند. اگر یکی
وجود نداشته باشد، ورود را با CLI انجام دهید؛ pool بقیهٔ سشن‌های شروع‌شده را
هم می‌بندد و خطا را بازمی‌گرداند.

## دریافت هم‌زمان از چند حساب

برای هر حساب handler مستقل ثبت کنید؛ سپس `run()` آن‌ها را با یک `TaskGroup`
اجرا کنید. `workers` برای تعداد handler workerهای **همان یک سشن** است، نه
تعداد حساب‌ها.

```python
import asyncio
from fnc_rubika import SessionPool


async def main() -> None:
    async with SessionPool("personal", "business") as sessions:
        for session_name in sessions.names:
            client = sessions[session_name]

            @client.on("message")
            async def on_message(_, delivery, name=session_name):
                print(name, delivery.event.event_id, delivery.event.payload)

        async with asyncio.TaskGroup() as group:
            for client in sessions:
                group.create_task(client.run(workers=2))
```

در برنامهٔ واقعی یک مسیر توقف کنترل‌شده (signal، دکمهٔ stop یا cancellation)
داشته باشید. با خروج از `async with`، همهٔ taskهای transport لغو و storeها بسته
می‌شوند.

## رفتار restart و crash

1. قبل از ارسال، عملیات در outbox رمزگذاری‌شده ذخیره می‌شود.
2. هر عملیات کلید idempotency مستقل دارد.
3. اگر نتیجهٔ ارسال قطعی نباشد، فقط endpointهایی که در catalog صراحتاً
   idempotent هستند retry می‌شوند؛ وگرنه وضعیت `unknown` می‌گیرند.
4. event قبل از تحویل در inbox ذخیره می‌شود؛ cursor فقط پس از `ack()` جلو
   می‌رود.

نتیجهٔ دریافت `at-least-once` است. handler باید `event_id` را در database
خودش unique کند تا side effectهای خودش نیز عملاً تکراری نشوند.

## حفظ و حذف امن داده

- از `%LOCALAPPDATA%\fnc-rubika` نسخهٔ پشتیبان plaintext نگیرید.
- SQLite، فایل WAL و SHM آن و `*.salt` را commit نکنید.
- حذف دستی پوشهٔ یک سشن، صف ارسال و cursor آن را هم از بین می‌برد؛ فقط پس از
  بستن برنامه و با آگاهی از این اثر انجام دهید.
- این نسخه متد حذف سشن در API ندارد تا پاک‌سازی سشن ناخواسته رخ ندهد.
- اگر OS keyring در محیط سرور موجود نیست، maintainer باید `PassphraseKeyProvider`
  با گذرواژهٔ تعاملی (حداقل ۱۲ کاراکتر) را هنگام راه‌اندازی inject کند؛ گذرواژه
  را در فایل config ذخیره نکنید.
