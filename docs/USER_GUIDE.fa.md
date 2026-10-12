# راهنمای fnc-rubika 0.2

کاتالوگ عمومی وب روبیکا و آداپتور اختصاصی HTTP و WebSocket همراه بسته هستند.
تست‌های محلی و کشف عمومی سرورها پاس شده‌اند. ورود حساب، ارسال پیام و تمام
schemaها هنوز نیازمند تأیید عملی روی حساب هستند.

## نصب و ورود

نصب مستقیم از GitHub داخل venv فعال:

```powershell
python -m pip install "git+https://github.com/HamidrezaBakhshi8118/FNC-Rubika.git@main"
```

برای ورود هیچ CLI جداگانه‌ای لازم نیست. اولین اجرای
`async with Client("personal")` اگر سشن موجود نباشد شماره و OTP را در همان
ترمینال می‌پرسد.

در VS Code از `Python: Select Interpreter` مفسر
`venv\\Scripts\\python.exe` را انتخاب کنید. نصب در Python 3.14 سراسری برای
فایلی که با Python 3.12 یا venv دیگری اجرا می‌شود قابل مشاهده نیست.

در نبود سشن، انقضای محلی یا رد شدن سشن توسط سرویس، شماره و کد در ترمینال
پرسیده می‌شوند. شماره‌های `09…`، `989…`، `+989…` و `00989…` و ارقام فارسی
پذیرفته می‌شوند. کد و رمز دومرحله‌ای موجود با getpass خوانده می‌شوند؛ در
ترمینال واقعی اجرا کنید تا ورودی پنهان بماند. تا سه تلاش برای شماره، رمز و
کد نامعتبر مجاز است. برای کد منقضی‌شده، دستور ورود را دوباره اجرا کنید.

سشن پیش‌فرض در `%LOCALAPPDATA%\fnc-rubika` ذخیره می‌شود. auth و کلید خصوصی
نسخه ۶ در SQLite با AES-GCM رمزگذاری می‌شوند؛ کلید ذخیره‌سازی در keyring
سیستم است. OTP و رمز دومرحله‌ای ذخیره نمی‌شوند. شناسه حساب برای جلوگیری از
اجرای صف حساب قبلی روی حساب دیگر ذخیره می‌شود. برای حساب دیگر نام سشن جدید
انتخاب کنید. هر فایل سشن در هر لحظه باید متعلق به یک پردازش باشد.

## کلاینت ناهم‌زمان

```python
import asyncio
from fnc_rubika import Client

async def main():
    client = Client("personal")

    @client.on("message")
    async def on_message(_, delivery):
        print(delivery.event.event_id)

    async with client:
        chats = await client.getChats()
        # معادل: await client.api.getChats()
        await client.run()

asyncio.run(main())
```

ثبت هندلر قبل از ورود مجاز است. ورود مجدد، هندلرها و صف را حفظ می‌کند.
خطاهای هم‌زمان HTTP و WebSocket فقط یک prompt ایجاد می‌کنند. promptهای ورود
چند سشن نیز با یکدیگر تداخل ندارند. `Client(..., auto_login=False)` برای
برنامه بدون ورودی انسانی است و در نبود سشن معتبر SessionExpiredError می‌دهد.

## کلاینت هم‌زمان

```python
from fnc_rubika import Client

with Client("personal") as client:
    chats = client.api.getChats()
```

## پیام و رسانه

```python
async with Client("personal") as client:
    sent = await client.messages.send("u0BZZ2v005a960184e514f3254431d0c", "سلام")
    history = await client.messages.history("u0BZZ2v005a960184e514f3254431d0c", limit=20)
    media = await client.media.upload("photo.jpg")
    await client.media.download(media, "downloaded.jpg")
```

شناسه گفت‌وگو همان object_guid روبیکا است. مقدار خام GUID، `#c=GUID` و URL
کامل نسخهٔ وب پذیرفته می‌شوند و قبل از RPC به GUID خام تبدیل می‌شوند. دانلود به MediaRef یا descriptor
شامل `file_id`، `access_hash_rec`، `dc_id` و `size` نیاز دارد؛ شناسه تنها کافی
نیست. برای فایل دریافتی از `file_inline` واقعی استفاده کنید. فایل محلی آپلود
تا پایان صف باید باقی بماند.

## متدها و دریافت

۲۰۵ نام RPC و ۶ alias در کاتالوگ هستند؛ فهرست در [WEB_METHODS.fa.md](WEB_METHODS.fa.md)
آمده است. نام‌های واقعی مانند `client.api.getUserInfo(user_guid="...")` قابل
فراخوانی‌اند. پارامترها، نام‌های واقعی سرویس هستند و کلیدهای جدول schema کامل
نیستند. `getSelection` و `searchSelection` به `dc_url` واقعی بازگردانده‌شده
از سرویس نیاز دارند. `handShake` مخصوص WebSocket است.

سرورها با getDCs کشف می‌شوند. اتصال WebSocket handshake و heartbeat دارد و
batchهای messenger را رمزگشایی می‌کند. رویدادهای دریافت‌شده پیش از تحویل در
SQLite نگهداری می‌شوند. پروتکل وب مشاهده‌شده resume token ندارد؛ بازیابی
خودکار شکاف رویدادها پیاده نشده است. برای backfill از getChatsUpdates و
getMessagesUpdates با state واقعی برنامه استفاده کنید.

ارسال مبهم دوباره انجام نمی‌شود، چون تضمین deduplication سرویس تأیید نشده
است. پس از crash نیز عملیات در حال ارسال به unknown تبدیل می‌شوند و نیاز به
بررسی نتیجه در سمت برنامه دارند. WebRTC تماس صوتی پیاده نشده است؛ نام‌های
RPC مدیریت voice chat در کاتالوگ موجودند.
