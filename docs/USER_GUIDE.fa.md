# راهنمای کاربر fnc-rubika

## هدف

برای ساخت سشن لازم نیست endpoint، token، شماره یا OTP را در برنامه hard-code کنید. هر حساب فقط یک نام محلی دارد و اطلاعات حساس آن به‌صورت رمزگذاری‌شده روی همان دستگاه نگهداری می‌شود.

## نصب

```powershell
py -3.13 -m pip install .
```

Python 3.11 تا 3.13 پشتیبانی می‌شود. نصب عادی شامل keyring سیستم‌عامل است؛ بنابراین کلید رمزگذاری از سیستم‌عامل گرفته می‌شود و در پروژه ذخیره نمی‌شود.

## ساخت سشن از ترمینال

فقط یک‌بار برای هر حساب این دستور را اجرا کنید:

```powershell
fnc-rubika login personal
```

CLI دو مقدار می‌پرسد:

```text
شماره روبیکا را با فرمت +989XXXXXXXXX وارد کنید: +989123456789
کد تایید ارسال‌شده را وارد کنید: 12345
Session 'personal' was created securely.
```

- شماره باید دقیقاً با `+989` آغاز شود؛ شکل‌هایی مثل `0912…` یا `989…` پذیرفته نمی‌شوند تا کشور و فرمت مبهم نباشد.
- `personal` صرفاً نام سشن محلی است. برای حساب‌های دیگر، مثلاً `business` یا `test`, نام دیگری انتخاب کنید.
- شماره، OTP، token، cookie و device-id در log چاپ نمی‌شوند و OTP در فایل سشن ذخیره نمی‌شود.
- فایل رمزگذاری‌شدهٔ سشن در مسیر دادهٔ برنامه (`%LOCALAPPDATA%\fnc-rubika` در ویندوز) قرار می‌گیرد، نه در پوشهٔ repository.

## استفاده در Python

پس از یک‌بار login، فقط نام سشن لازم است:

```python
from fnc_rubika import Client

async with Client("personal") as client:
    sent = await client.messages.send("chat-id", "سلام")
```

`Client("personal")` خودش کلاینت سشنی است؛ در کاربرد عادی نیازی به
`async_client()` ندارید. آن متد فقط برای integrationهای سطح پایین باقی مانده
است. برای چند حساب هم‌زمان، از `SessionPool` استفاده کنید؛ راهنمای کامل در
[SESSIONS.fa.md](SESSIONS.fa.md) است.

برای ساخت سشن در یک برنامهٔ ترمینالی، بدون ذخیره‌سازی شماره یا code در source:

```python
from fnc_rubika import Client

client = Client("personal")
try:
    await client.login_interactive()
finally:
    await client.aclose()
```

## همهٔ APIها بدون hard-code

`fnc-rubika` دو سطح API دارد:

1. APIهای typed و پایدار برای مسیرهای پرکاربرد: `messages.send`, `reply`, `edit`, `delete`, `forward`, `history` و `media.upload/download`.
2. `client.api` که هر operation موجود در catalog بازبینی‌شده را خودکار در اختیار می‌گذارد. اگر catalog شامل `chats.get_info` باشد، همان لحظه این فراخوانی بدون افزودن route به برنامهٔ مصرف‌کننده قابل استفاده است:

```python
async with Client("personal") as client:
    result = await client.api.chats.get_info(chat_id="chat-id")
```

برای operationهای تغییردهنده، catalog مشخص می‌کند که درخواست باید از outbox پایدار و idempotency عبور کند. برای خواندن، همان catalog روش HTTP، schema، pagination و خطاها را تعیین می‌کند. به این ترتیب با کامل‌شدن catalog مجاز، همهٔ APIها قابل دسترسی‌اند و کاربر endpoint یا payload transport را hard-code نمی‌کند.

## دریافت پایدار پیام

```python
async with Client("personal") as client:
    async for delivery in client.events():
        try:
            await save_to_database(delivery.event)
        except Exception:
            await delivery.nack()
        else:
            await delivery.ack()
```

دریافت `at-least-once` است: event ابتدا در inbox رمزگذاری‌شده ثبت می‌شود؛ سپس تحویل داده می‌شود؛ و cursor فقط بعد از `ack` جلو می‌رود. بنابراین handler باید از شناسهٔ event برای جلوگیری از اثر تکراری استفاده کند.

## ارسال و محدودیت سرویس

پیام‌های خروجی ابتدا در outbox رمزگذاری‌شده ثبت می‌شوند. قطع اتصال، timeout و `Retry-After` باعث از دست رفتن کار نمی‌شوند. تکرار خودکار فقط برای endpointهایی اتفاق می‌افتد که catalog آن‌ها را idempotent اعلام کرده باشد؛ در غیر این صورت وضعیت `unknown` برمی‌گردد تا پیام تکراری ایجاد نشود.

کتابخانه محدودیت‌های Rubika و anti-abuse را دور نمی‌زند. ظرفیت صف و retry قابل تنظیم‌اند، اما quota و rate limit سرویس معتبر می‌مانند.

## وضعیت catalog Rubika

فایل همراه بسته در این commit یک placeholder امن است، نه قرارداد زنده. این تصمیم عمدی است: بدون مستندات تأییدشده و حساب تست مجاز، قرار دادن endpoint یا WebSocket حدسی می‌تواند باعث از کار افتادن login یا افشای داده شود.

برای فعال‌شدن login واقعی و پوشش کامل API، maintainers باید catalog رسمی و بازبینی‌شدهٔ Rubika را با این اجزا منتشر کنند:

- تمام endpointها: نام operation، HTTP method/path، schema، خطا، pagination و idempotency.
- قرارداد OTP: operation ارسال کد، operation تأیید کد و field mapping پاسخ session.
- قرارداد WebSocket: URL، auth، heartbeat، event id/type/payload/cursor و resume.
- fixtureهای کاملاً redact‌شده و تست integration با حساب آزمایشی جدا.

پس از انتشار catalog معتبر در خود package، دستور `fnc-rubika login personal` بدون فایل پیکربندی یا کدنویسی اضافه برای کاربر کار خواهد کرد.

## خطاهای رایج

| پیام | علت و اقدام |
| --- | --- |
| `Phone number must use ...` | شماره را مانند `+989123456789` وارد کنید. |
| `no reviewed OTP authentication contract` | نسخهٔ نصب‌شده catalog زنده ندارد؛ نسخهٔ دارای catalog تأییدشده را نصب کنید. |
| `No session exists` | ابتدا `fnc-rubika login <session-name>` را اجرا کنید. |
| `SessionExpiredError` | دوباره با همان نام سشن login کنید؛ سیستم خودکار OTP دریافت نمی‌کند. |
| `unknown` در outbox | پاسخ ارسال مبهم بوده و endpoint idempotent نیست؛ قبل از ارسال مجدد نتیجه را بررسی کنید. |

## امنیت

- پوشهٔ سشن، `*.sqlite3` و `*.salt` را هرگز commit نکنید.
- OTP یا token را برای پشتیبانی ارسال نکنید.
- برای تست، از حساب و گفت‌وگوی غیرشخصی استفاده کنید.
- catalogها و fixtureها را پیش از commit از شماره، متن پیام، URL رسانه، token، cookie و device-id پاک‌سازی کنید.
