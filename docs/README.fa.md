# راهنمای fnc-rubika

> برای راهنمای کاربر نهایی و login با شمارهٔ `+98`، ابتدا [راهنمای کاربر](USER_GUIDE.fa.md) را بخوانید. این صفحه برای نگهدارندهٔ catalog و توسعهٔ integration است.

## وضعیت نسخهٔ نخست

`fnc-rubika` یک پایهٔ خصوصی و clean-room برای کلاینت سشنی مجاز Rubika است. هستهٔ آن برای پیام، رسانه، صف خروجی پایدار و دریافت رویداد طراحی شده است. هیچ endpoint، هدر احراز هویت یا فریم WebSocket در سورس حدس زده نشده است؛ پیش از اتصال واقعی باید قرارداد بازبینی‌شده نصب شود.

## نصب خصوصی

```bash
pip install .
# برای نگهداری کلید در OS keyring، در صورت نیاز:
pip install '.[keyring]'
```

پکیج با نام `fnc-rubika` ساخته می‌شود و import آن `fnc_rubika` است. انتشار در PyPI در این نسخه انجام نمی‌شود.

## ساخت session store امن

گزینهٔ مناسب سرویس‌های محلی، OS keyring است. اگر keyring در محیط اجرا وجود ندارد، passphrase را از secret manager برنامه بگیرید؛ آن را در source، فایل پیکربندی یا log قرار ندهید.

```python
from fnc_rubika import EncryptedSQLiteStore, PassphraseKeyProvider

store = EncryptedSQLiteStore(
    "./private/rubika-session.sqlite3",
    key_provider=PassphraseKeyProvider(load_secret_from_your_secret_manager()),
)
```

همهٔ session material، payload صف خروجی، دادهٔ event و cursor با AES-256-GCM رمزگذاری می‌شوند. فایل `.salt` کنار database secret نیست، اما باید همراه database باقی بماند. حذف آن باعث می‌شود دادهٔ پیشین قابل بازخوانی نباشد.

## قرارداد endpoint و WebSocket

1. یک حساب و گفت‌وگوی آزمایشی غیرشخصی آماده کنید.
2. ورود OTP را خودتان در محیط تست انجام دهید؛ شماره، OTP، token، cookie و device-id را در issue، chat یا fixture قرار ندهید.
3. مستندات رسمی و captureهای مجاز را به یک کاتالوگ JSON نسخه‌دار تبدیل کنید. از [نمونه کاتالوگ](../contracts/session.catalog.example.json) شروع کنید.
4. برای هر operation این موارد را ثبت کنید: method، path، نوع body، auth، statusهای موفق، schema درخواست/پاسخ، pagination، خطاها و idempotency header.
5. برای WebSocket: URL، روش auth، resume cursor، event id/type/payload/cursor fields، heartbeat و پیام‌های خطا را ثبت کنید.

فقط endpointی که در کاتالوگ باشد قابل فراخوانی است. بنابراین نسخهٔ جدید وب یا قرارداد ناسازگار به‌جای ارسال به URL حدسی با خطای واضح متوقف می‌شود.

```python
from fnc_rubika import AsyncClient, EncryptedSQLiteStore, Session
from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.storage import KeyringKeyProvider
from fnc_rubika.transport import HttpWebSocketTransport

store = EncryptedSQLiteStore("./private/session.sqlite3", key_provider=KeyringKeyProvider())
session = store.load_secret("session")
assert session is not None

registry = ContractRegistry.from_file("./contracts/reviewed-session-v1.json")
transport = HttpWebSocketTransport(registry, Session.from_dict(session))
client = AsyncClient(transport, store)
```

## ورود OTP

پکیج یک `OtpAuthenticator` interface دارد تا adapter آن تنها از قرارداد بازبینی‌شده استفاده کند. OTP در storage ذخیره نمی‌شود و library آن را log نمی‌کند.

```python
challenge_id = await client.begin_login(authenticator, phone_number)
# code را فقط از ورودی امن برنامهٔ خودتان بگیرید.
session = await client.complete_login(authenticator, challenge_id, code)
```

`authenticator` باید یک adapter داخلیِ بازبینی‌شده باشد که `begin(phone_number)` و `complete(challenge_id, code)` را پیاده‌سازی می‌کند. تا زمانی که قرارداد رسمی وجود ندارد، چنین adapterی نباید ساخته یا فعال شود.

## ارسال پیام و رسانه

```python
async with client:
    message = await client.messages.send("chat-id", "سلام")
    await client.messages.reply(message.chat_id, message.message_id, "پاسخ")
    attachment = await client.media.upload("./report.pdf", content_type="application/pdf")
```

هر mutation پیش از ارسال در outbox رمزگذاری‌شده ثبت می‌شود. عملیات در صورت timeout فقط وقتی تکرار می‌شود که قرارداد همان endpoint idempotency key را تأیید کند؛ در غیر این صورت نتیجه `unknown` می‌شود تا از ارسال تکراری جلوگیری شود.

`wait=False` یک `QueuedOperation` برمی‌گرداند؛ سپس با `await client.wait_operation(operation_id)` می‌توان نتیجه را گرفت. فایل upload باید تا تحویل موفق، در همان مسیر باقی بماند.

محدودیت‌های اعلامی سرویس، `Retry-After` و anti-abuse رعایت می‌شوند. کتابخانه هیچ روش دورزدن quota یا spam protection ندارد.

## دریافت رویدادها

```python
async with client:
    async for delivery in client.events():
        try:
            print(delivery.event.type, delivery.event.payload)
            await save_to_your_database(delivery.event)
        except Exception:
            await delivery.nack()  # تحویل مجدد پس از خطا
        else:
            await delivery.ack()   # cursor فقط اکنون جلو می‌رود
```

مدل تحویل `at-least-once` است. inbox رمزگذاری‌شده قبل از تحویل به برنامه ثبت می‌شود؛ event تکراری با `event_id` حذف می‌شود، و cursor فقط پس از `ack` جلو می‌رود. پس handler باید برای اجرای تکراری نیز idempotent باشد.

برای handlerهای ثبت‌شده:

```python
@client.on("message")
async def on_message(client, delivery):
    await client.messages.reply(
        delivery.event.payload["chat_id"],
        delivery.event.payload["message_id"],
        "دریافت شد",
    )

await client.run(workers=4)
```

موفقیت handler باعث `ack` و exception باعث `nack` می‌شود. با انقضای lease یا restart، event تأییدنشده دوباره تحویل داده می‌شود.

## رابط sync

```python
from fnc_rubika import SyncClient

with SyncClient(client) as sync_client:
    sync_client.messages.send("chat-id", "hello")
```

برای handlerهای sync، callback در thread جداگانه اجرا می‌شود تا بتواند از همان facade استفاده کند.

## تست و عملیات

```bash
$env:PYTHONPATH = "src"
py -3 -m pytest
```

تست‌های unit شامل رمزگذاری، deduplication، cursor، outbox، rate-limit retry و handler acknowledgement هستند. تست integration باید فقط با حساب و گفت‌وگوی آزمایشی اجرا شود و fixtureهای آن redact شوند. پیش از release داخلی، قطع اتصال قبل/بعد از پاسخ، restart process، event تکراری، ارسال رسانه و soak test طولانی‌مدت را اجرا کنید.

## ماتریس پشتیبانی v1

| حوزه | وضعیت |
| --- | --- |
| سشن و OTP | interface آماده؛ adapter پس از قرارداد رسمی |
| HTTP/WebSocket | generic و contract-driven |
| دریافت message event | پایدار و at-least-once |
| send/reply/edit/delete/forward/history | API پایدار؛ فعال‌سازی با قرارداد هر operation |
| upload/download رسانه | API پایدار؛ فعال‌سازی با قرارداد media |
| سایر endpointهای مجاز | در catalog ثبت می‌شوند، خارج از API پایدار v1 |
