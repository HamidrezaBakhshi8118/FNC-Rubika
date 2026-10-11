# مرجع کامل API — fnc-rubika 0.1

این مرجع API عمومی نسخهٔ `0.1` است. همهٔ نمونه‌ها Python 3.11+ و `asyncio`
هستند. نام distribution در pip برابر `fnc-rubika` و نام import برابر
`fnc_rubika` است.

> نکتهٔ صداقت فنی: متدهای پیام و رسانه API پایدار محلی هستند، اما فقط پس از
> عرضهٔ catalog بازبینی‌شده به endpoint واقعی وصل می‌شوند. در catalog همراه این
> repository هیچ endpoint واقعی حدس زده نشده است. وضعیت و روش تکمیل آن در
> [راهنمای catalog](CONTRACT_CATALOG.fa.md) آمده است.

## 1. Client — API پیشنهادی

```python
from fnc_rubika import Client

async with Client("personal") as client:
    ...
```

### سازنده

```python
Client(
    session_name: str,
    *,
    registry: ContractRegistry | None = None,
    contract_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    key_provider: KeyProvider | None = None,
)
```

| ورودی | اجباری | شرح |
| --- | --- | --- |
| `session_name` | بله | ۱ تا ۶۴ کاراکتر؛ ابتدا حرف/عدد و سپس فقط حرف، عدد، `_` یا `-`. مانند `personal` یا `business-1`. |
| `registry` | خیر | catalog از قبل بارگذاری‌شده؛ برای تست یا integration کنترل‌شده. با `contract_path` هم‌زمان ندهید. |
| `contract_path` | خیر | مسیر JSON catalog بازبینی‌شده. پیش‌فرض catalog همراه بسته است. |
| `data_dir` | خیر | پوشهٔ ذخیرهٔ encrypted DBها. پیش‌فرض `%LOCALAPPDATA%\fnc-rubika` در ویندوز است. |
| `key_provider` | خیر | provider کلید؛ پیش‌فرض OS keyring است. برای محیط بدون keyring، `PassphraseKeyProvider` تزریق کنید. |

### چرخهٔ عمر

| متد / ویژگی | امضا | نتیجه و خطا |
| --- | --- | --- |
| context manager | `async with Client("personal") as client` | سشن ذخیره‌شده را بار می‌کند؛ اگر نبود، شماره و OTP را در ترمینال می‌پرسد، سپس receiver/outbox را آغاز می‌کند. هنگام خروج همه‌چیز بسته می‌شود. |
| `start` | `await client.start()` | معادل بخش آغازین context manager؛ در نبود سشن ورود تعاملی را آغاز می‌کند و تا قبل از بستن idempotent است. |
| `aclose` | `await client.aclose()` | receiver، outbox، HTTP و store را می‌بندد؛ idempotent است. کلاینت بسته restart نمی‌شود. |
| `has_session` | `client.has_session()` | `bool`؛ تنها وجود سشن ذخیره‌شده را می‌سنجد، اعتبار آن در سرویس را نه. |
| `session_name` | `client.session_name` | نام محلی immutable سشن. |
| `session_expired` | `client.session_expired` | اگر provider سشن را رد کرده باشد `True` می‌شود؛ login خودکار انجام نمی‌شود. |
| `async_client` | `client.async_client()` | `AsyncClient` داخلی برای integration پیشرفته؛ در کد عادی به‌جای آن از خود `client` استفاده کنید. |

### ورود

| متد | امضا | ورودی و رفتار |
| --- | --- | --- |
| `login` | `await client.login(phone_number, code, *, authenticator=None)` | API پیشرفته برای adapterهای تاییدشده. `phone_number` دقیقاً `+989XXXXXXXXX` و `code` OTP غیرخالی است. سشن رمزگذاری‌شده ذخیره می‌شود. |
| `login_interactive` | `await client.login_interactive(*, input_func=input, otp_input_func=getpass, authenticator=None)` | شماره و OTP را از ترمینال می‌پرسد. labelهای غیرحساس Chroma-styled هستند و OTP پیش‌فرض echo نمی‌شود. برای تست، inputها و adapter قابل تزریق‌اند. |

پس از login، object باز می‌ماند و می‌توانید `async with client:` استفاده کنید؛ اگر تنها برای login ساخته‌اید، همیشه `await client.aclose()` را در `finally` بگذارید.

### پیام

`client.messages` یک `MessagesService` است. تمام mutationها ابتدا به outbox durable می‌روند. `wait=True` پیش‌فرض است و نتیجهٔ typed می‌دهد؛ با `wait=False` سریعاً `QueuedOperation` برمی‌گردد.

| متد | امضا | خروجی |
| --- | --- | --- |
| `send` | `await client.messages.send(chat_id, text, *, reply_to_message_id=None, wait=True, timeout=30)` | `Message` یا `QueuedOperation`. `chat_id` و `text` اجباری‌اند. `timeout=None` یعنی منتظر نتیجه بمان. |
| `reply` | `await client.messages.reply(chat_id, message_id, text, *, wait=True, timeout=30)` | `Message` یا `QueuedOperation`; معادل send با `reply_to_message_id=message_id`. |
| `edit` | `await client.messages.edit(chat_id, message_id, text, *, wait=True, timeout=30)` | `Message` یا `QueuedOperation`. |
| `delete` | `await client.messages.delete(chat_id, message_id, *, wait=True, timeout=30)` | `Mapping[str, Any]` یا `QueuedOperation`. |
| `forward` | `await client.messages.forward(from_chat_id, message_id, to_chat_id, *, wait=True, timeout=30)` | `Message` یا `QueuedOperation`. |
| `history` | `await client.messages.history(chat_id, *, cursor=None, limit=None)` | `tuple[Message, ...]`. `cursor` و `limit` تنها زمانی اثر دارند که catalog آن endpoint را تعریف کند. |

نمونهٔ ارسال با عدم انتظار:

```python
queued = await client.messages.send("chat-id", "سلام", wait=False)
result = await client.wait_operation(queued.operation_id, timeout=60)
```

### رسانه

| متد | امضا | خروجی و ملاحظه |
| --- | --- | --- |
| `upload` | `await client.media.upload(path, *, content_type=None, wait=True, timeout=60)` | `MediaRef` یا `QueuedOperation`. `path` باید فایل موجود باشد و تا تحویل outbox حذف یا جابه‌جا نشود. |
| `download` | `await client.media.download(file_id, destination)` | `MediaRef`. `destination` مسیر نهایی محلی است؛ parent در صورت نیاز ساخته می‌شود. |

### event و handler

| متد | امضا | رفتار |
| --- | --- | --- |
| `events` | `client.events()` | async iterator از `Delivery`. بعد از side effect موفق `await delivery.ack()` و در خطا `await delivery.nack()`. |
| `on` | `@client.on(event_type)` یا `client.on(event_type, handler)` | handler sync یا async ثبت می‌کند. `event_type="*"` همهٔ eventها را می‌گیرد. امضای handler: `(client, delivery)`. |
| `run` | `await client.run(*, workers=1)` | receiver را آغاز و handlerهای ثبت‌شده را اجرا می‌کند. `workers >= 1`. پس از موفقیت همهٔ handlerها event ack می‌شود. exception باعث nack و تحویل مجدد می‌شود. |
| `wait_operation` | `await client.wait_operation(operation_id, *, timeout=30)` | تا `delivered` منتظر می‌ماند و response mapping می‌دهد؛ `failed` → `RemoteOperationError`، `unknown` → `OperationUnknownError`. |

نمونهٔ ایمن:

```python
@client.on("message")
async def persist_message(_, delivery):
    # event_id باید در DB خودتان unique باشد.
    await save_once(delivery.event.event_id, delivery.event.payload)
```

### عملیات catalog

`client.api` هیچ endpointی را حدس نمی‌زند. تنها نام‌هایی که در catalog فعال
هستند ظاهر می‌شوند. مثلاً فقط پس از اینکه catalog شامل `chats.get_info` باشد:

```python
info = await client.api.chats.get_info(chat_id="chat-id")
```

هر operation read به‌صورت مستقیم خوانده می‌شود و هر mutation از outbox رد
می‌شود. امضای عمومی همهٔ آن‌ها چنین است:

```python
await client.api.<namespace>.<operation>(*, wait=True, timeout=30, **payload)
```

payload و schema دقیق را همان catalog تعیین می‌کند؛ `wait` و `timeout` برای
mutationها معتبرند و readها بلافاصله mapping پاسخ را برمی‌گردانند.

## 2. SessionPool — چندسشنی

```python
SessionPool(
    *session_names: str,
    registry: ContractRegistry | None = None,
    contract_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    key_provider: KeyProvider | None = None,
)
```

| عضو | امضا | شرح |
| --- | --- | --- |
| context manager | `async with SessionPool("personal", "business") as sessions` | تمام سشن‌های موجود را concurrent باز می‌کند. نام تکراری یا لیست خالی `ValueError` است. |
| `names` | `sessions.names` | tuple نام‌ها به ترتیب ساخت. |
| `get` | `sessions.get("personal")` | `Client` همان نام، یا `KeyError`. |
| `[]` | `sessions["personal"]` | معادل `get`. |
| iteration | `for client in sessions:` | `Client`ها به ترتیب نام. |
| `aclose` | `await sessions.aclose()` | تمام اعضا را concurrent می‌بندد؛ idempotent. |

جزئیات امنیتی و الگوهای هم‌زمانی در [راهنمای سشن](SESSIONS.fa.md) است.

## 3. مدل‌ها

| مدل | فیلدها |
| --- | --- |
| `Session` | `access_token`, `device_id | None`, `expires_at | None`. نباید چاپ یا log شود. |
| `Message` | `chat_id`, `message_id`, `text | None`, `reply_to_message_id | None`, `raw`. |
| `MediaRef` | `file_id`, `name | None`, `content_type | None`, `size | None`, `raw`. |
| `EventEnvelope` | `event_id`, `type`, `payload`, `cursor | None`, `received_at`. |
| `Delivery` | `event` و متدهای async `ack()` / `nack()`. هر کدام فقط نخستین‌بار اثر دارند. |
| `QueuedOperation` | `operation_id`, `operation`, `idempotency_key`. |

## 4. AsyncClient و SyncClient (پیشرفته)

### AsyncClient

`AsyncClient(transport, store, *, reconnect_base_seconds=0.5,
reconnect_max_seconds=30, event_lease_seconds=60)` سطح پایین است. `transport`
باید قرارداد `request`, `stream_events`, `download`, `aclose` را پیاده کند و
`store` یک `EncryptedSQLiteStore` باشد. متدهای آن همان `start`, `aclose`,
`messages`, `media`, `api`, `on`, `events`, `run`, `wait_operation`,
`begin_login`, `complete_login`, `load_session` و `session_expired` هستند. در
کاربرد عادی آن را مستقیم نسازید؛ `Client` سازندهٔ مطمئن‌تر است.

### SyncClient

`SyncClient(async_client)` برای برنامه‌هایی است که event loop ندارند:

```python
from fnc_rubika import SyncClient

async_client = Client("personal").async_client()
with SyncClient(async_client) as client:
    message = client.messages.send("chat-id", "سلام")
```

متدهای sync `messages.send/reply/edit/delete/forward/history` و
`media.upload/download` ورودی و خروجی همتای async خود را دارند. lifecycle:
`start()`, `close()`, context manager، `on(event_type, handler)` و
`run(workers=1)` هستند. از `SyncClient` داخل event loop در حال اجرا استفاده
نکنید.

## 5. خطاها

| خطا | علت / اقدام |
| --- | --- |
| `SecurityConfigurationError` | سشن وجود ندارد، keyring در دسترس نیست یا کلید نامعتبر است. |
| `SessionExpiredError` | login خودکار انجام نمی‌شود؛ یک `Client` جدید با همان نام بسازید و `await client.login_interactive()` را اجرا کنید. |
| `ContractError` | catalog ناقص، فاقد OTP/WS، یا نامعتبر است. |
| `UnsupportedOperationError` | operation در catalog بازبینی‌شده وجود ندارد. |
| `RateLimitError` | سرویس rate limit داده؛ `Retry-After` رعایت می‌شود. سرعت را بالا نبرید. |
| `OperationUnknownError` | نتیجهٔ mutation مبهم و non-idempotent است؛ قبل از ارسال مجدد reconciliation کنید. |
| `RemoteOperationError` | سرویس mutation را رد کرده است؛ payload/permission را بررسی کنید. |
| `TransportError` | شبکه، frame یا قرارداد realtime مشکل دارد؛ client reconnect با backoff می‌کند. |
