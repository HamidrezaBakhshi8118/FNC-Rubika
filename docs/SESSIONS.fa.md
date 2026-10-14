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
| کلید رمزگذاری | کلید تصادفی ۲۵۶بیتی در فایل `<name>.rubika.key` کنار سشن؛ بدون درخواست رمز اضافه یا وابستگی به keyring |

از نسخهٔ ۰٫۲٫۵، فایل سشن در پوشهٔ اجرای برنامه ساخته می‌شود:

```text
<current-working-directory>\<session-name>.rubika
```

فایل SQLite شامل دادهٔ برنامه است، اما هر رکورد حساس با AES-256-GCM رمزگذاری
و احراز اصالت می‌شود. کلید در خود فایل SQLite یا repository قرار نمی‌گیرد.

از نسخهٔ ۰٫۲٫۸، سشن تازه به‌صورت پیش‌فرض رمز اضافه نمی‌پرسد. کلید تصادفی
در فایل `.rubika.key` ساخته می‌شود؛ ورودی عادی ورود فقط شماره و OTP است.
رمز دومرحله‌ای خود روبیکا، اگر روی حساب فعال باشد، همچنان توسط سرویس لازم است.
برای اجرای سشن تازه روی لینوکس یا PM2 هیچ متغیر گذرواژه‌ای لازم نیست.
پس از بستن برنامه، دو فایل `.rubika` و `.rubika.key` را با هم به مقصد ببرید؛
مسیر و نام کاربر سیستم‌عامل در کلید دخالت ندارند. هرکس هر دو فایل را بخواند
می‌تواند سشن را باز کند؛ فایل کلید باید مانند اطلاعات ورود محافظت شود.
کلید گم‌شدهٔ سشن موجود به‌صورت خودکار بازسازی یا جایگزین نمی‌شود.

حالت گذرواژه فقط با انتخاب صریح `session_password=` یا `PortableKeyProvider`
فعال می‌شود. سشن‌های گذرواژه‌ای نسخهٔ ۰٫۲٫۷ همچنان رمز اصلی خود را لازم دارند؛
رمز را در آرگومان یا متغیر `FNC_RUBIKA_SESSION_PASSWORD` بدهید. حالت پیش‌فرض
برای آن‌ها رمز را از ترمینال نمی‌پرسد و بدون رمز، خطای تنظیم واضح می‌دهد.

سشن‌های قدیمی وابسته به keyring روی سیستم اصلی سازگار می‌مانند. برای انتقال
آن‌ها، برنامه را ببندید و روی سیستم اصلی خروجی رمزگذاری‌شده بسازید:

```powershell
python -m fnc_rubika export-session personal portable/personal.rubika --from-keyring
```

پوشهٔ سشن اصلی را در صورت نیاز با `--data-dir` تعیین کنید. خروجی شامل دیتابیس
و فایل کلید تازه است و رمز اضافه نمی‌پرسد. تبدیل، فایل مبدأ، مقصد یا کلید موجود
را بازنویسی نمی‌کند و هیچ worker یا درخواست شبکه‌ای اجرا نمی‌کند.
برای حالت برنامه‌نویسی، پیش از `start()` از `client.export_session(...)` استفاده کنید.
سشن قدیمی دارای provider گذرواژه و فایل `.salt` نیز سازگار است؛ قالب پیش‌فرض
جدید فایل `.key` لازم دارد. به‌روزرسانی پکیج، فایل‌های قدیمی را خودکار تبدیل نمی‌کند.

`Client("personal")` و `Client("personal.rubika")` همان فایل را باز می‌کنند.
با `data_dir="sessions"` پوشه را تغییر دهید و با `client.session_path` مسیر
را ببینید. سشن‌های قدیمی در `%LOCALAPPDATA%\fnc-rubika` دست‌نخورده می‌مانند؛
به‌صورت خودکار بارگذاری یا جابه‌جا نمی‌شوند. اولین اجرای نسخهٔ جدید در صورت
نبود سشن محلی، شماره و کد را در ترمینال می‌پرسد.

پیش از راه‌اندازی صف و وب‌سوکت، ابتدا `registerDevice` اجرا می‌شود و سپس
دسترسی حساب بررسی می‌شود؛ سشن تازه پیش از ثبت دستگاه می‌تواند
`NOT_REGISTERED` برگرداند. اگر تمام درخواست‌های
خواندن حساب رد شوند، یک بار ورود مجدد انجام می‌شود. رد شدن سشن تازه خطای
`SessionRenewalError` می‌دهد و درخواست کد تکرار نمی‌شود. خطای شبکه یا رد شدن
فقط یک مقصد، به‌تنهایی ورود مجدد را فعال نمی‌کند.

## ساخت و ورود چند سشن از داخل برنامه

برای هر نام سشن، نخستین `async with` شماره را به شکل `09…` یا `+989…` و سپس OTP
را در ترمینال می‌پرسد. `chroma-term-console` labelهای غیرحساس را رنگی می‌کند و
OTP با `getpass` بدون echo گرفته می‌شود:

```python
async with Client("personal") as client:
    ...
```

هیچ شماره، OTP، cookie یا token را در source code، `README`، issue یا commit
قرار ندهید. در انقضا یا رد شدن سشن، ورود مجدد ترمینالی خودکار است. auto_login=False آن را غیرفعال می‌کند.

## شکل پیشنهادی برای یک حساب

`async_client()` برای بیشتر کاربران لازم نیست. خود `Client` یک context manager
async است و سرویس‌ها را مستقیم ارائه می‌کند:

```python
from fnc_rubika import Client


async def main() -> None:
    async with Client("personal") as client:
        message = await client.send("chat-id", "سلام")
        print(message.message_id)
```

اگر می‌خواهید ورود را پیش از شروع کار انجام دهید، همان جریان تعاملی را در
برنامه صدا بزنید؛ هیچ مقدار حساسی را hard-code نکنید:

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

`SessionPool` ابتدا سشن‌های نداشته را **یکی‌یکی** در همان ترمینال login می‌کند
تا promptها با هم قاطی نشوند؛ سپس تمام اعضا را concurrent باز می‌کند. اگر ورود
یکی خطا بدهد، pool بقیهٔ سشن‌های شروع‌شده را هم می‌بندد.

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

- اطلاعات سشن را برای پشتیبان‌گیری به plaintext تبدیل نکنید.
- SQLite، فایل WAL و SHM آن و فایل‌های `*.salt` و `*.rubika.key` را commit نکنید.
- حذف دستی پوشهٔ یک سشن، صف ارسال و cursor آن را هم از بین می‌برد؛ فقط پس از
  بستن برنامه و با آگاهی از این اثر انجام دهید.
- این نسخه متد حذف سشن در API ندارد تا پاک‌سازی سشن ناخواسته رخ ندهد.
- سشن تازه روی سرور به OS keyring یا گذرواژهٔ رمزگذاری نیاز ندارد؛ فایل کلید
  کنار سشن باید در همان مسیر باقی بماند. روی لینوکس فایل‌های جدید با دسترسی
  مالک ساخته می‌شوند؛ هنگام انتقال نیز دسترسی فایل کلید را محدود نگه دارید.

هر فایل سشن باید در هر لحظه متعلق به یک پردازش باشد. حساب دیگر به نام دارای account_id قبلی پذیرفته نمی‌شود؛ نام جدید انتخاب کنید. بعد از crash، عملیات ارسال‌نشده قطعی در حالت unknown قرار می‌گیرد. بازیابی خودکار رخدادهای زمان قطع WebSocket پیاده نشده است.
