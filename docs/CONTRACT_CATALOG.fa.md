# قرارداد endpoint و WebSocket

## وضعیت واقعی این repository

این repository در حال حاضر catalog نمونه/placeholder دارد و آن **هیچ مسیر یا
WebSocket واقعی Rubika را ادعا نمی‌کند**. چنین ادعایی بدون مستندات رسمی یا
بررسی مجاز حساب آزمایشی، هم ناپایدار و هم ناامن است.

`fnc-rubika` برای پوشش همهٔ APIها آماده است: هر operation بررسی‌شده‌ای که به
catalog اضافه شود بدون hard-code در `client.api` در دسترس خواهد بود؛ اما
«آماده بودن معماری» با «کشف و تأیید همهٔ endpointهای زنده» یکسان نیست.

## چه چیزهایی باید ثبت شود

هر endpoint باید این موارد را با fixtureهای redact‌شده داشته باشد:

| کلید | کاربرد |
| --- | --- |
| `operation` | نام پایدار نقطه‌ای مانند `messages.send` |
| `method`, `path`, `base_url` | قرارداد HTTP دقیق و version آن |
| `auth` | نیاز یا عدم نیاز به سشن |
| `operation_kind` | `read` یا `mutation`؛ mutation اجباراً outbox durable می‌گیرد |
| `idempotency_header` | فقط اگر سرویس صراحتاً پشتیبانی می‌کند |
| `request_schema`, `response_schema`, `errors` | ورودی، خروجی، خطاها و fieldهای اجباری |
| `pagination` | cursor/limit/next cursor اگر وجود دارد |
| `body_mode`, `file_field` | برای آپلودهای multipart |

قرارداد OTP نیز باید نام operationهای request/verify و fieldهای phone,
challenge, code, token, device و expiry را مشخص کند؛ هیچ مقدار واقعی secret
نباید در catalog وجود داشته باشد.

برای WebSocket باید URL، handshake/auth، روش resume، heartbeat، و fieldهای
`event_id`, `type`, `payload`, `cursor` ثبت و با disconnect کنترل‌شده تست شود.

## روند مجاز کشف و بازبینی

1. فقط با حساب و گفت‌وگوی آزمایشی مجاز وارد web/client رسمی شوید.
2. از ابزار توسعه‌دهنده، روش، host، path، headerهای **غیرحساس**، schemaهای
   request/response، status و frameهای WebSocket را ثبت کنید.
3. token، cookie، authorization header، شماره، متن واقعی پیام، شناسهٔ شخصی و
   URL رسانه را پیش از ذخیره یا commit redact کنید.
4. رفتار pagination، rate limit، retry، session expiry و reconnect را در یک
   محیط آزمایشی جدا تایید کنید.
5. هر route را با integration test بازتولید کنید؛ سپس به catalog versioned
   اضافه کنید.
6. تنها پس از review، آن route برای مصرف‌کننده از `client.api` ظاهر می‌شود.

از دریافت یا ارسال انبوه، تلاش برای دورزدن quota، جعل client fingerprint،
یا استفاده از دادهٔ سایر کاربران خودداری کنید. این کتابخانه نیز نباید چنین
رفتاری پیاده‌سازی کند.

## نتیجهٔ مورد انتظار پس از تکمیل catalog

فرض کنید catalog تاییدشده operationهای زیر را تعریف کرده باشد:

```json
[
  {"operation": "chats.get_info", "operation_kind": "read"},
  {"operation": "contacts.search", "operation_kind": "read"},
  {"operation": "messages.pin", "operation_kind": "mutation"}
]
```

فراخوانی‌های public بدون route hard-code‌شده چنین‌اند:

```python
await client.api.chats.get_info(chat_id="...")
await client.api.contacts.search(query="...")
await client.api.messages.pin(chat_id="...", message_id="...")
```

وجود واقعی و schema این نمونه‌ها را این repository تایید نمی‌کند؛ نمونه فقط
نشان می‌دهد namespaceهای catalog چگونه به API تبدیل می‌شوند.
