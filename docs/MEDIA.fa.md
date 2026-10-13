# فوروارد، عکس و فیلم

متدهای زیر روی `Client` تعریف صریح و type hint دارند و در تکمیل کد VS Code
دیده می‌شوند. همین متدها در کلاینت هم‌زمان `SyncClient` نیز موجودند.

```python
await client.forward_message(source_chat_id, message_id, destination_chat_id)
await client.send_photo(chat_id, "photo.jpg")
await client.send_photo(chat_id, "photo.jpg", caption="کپشن عکس")
await client.send_video(chat_id, "video.mp4")
await client.send_video(chat_id, "video.mp4", caption="کپشن فیلم")
```

`forward_message` نام خواناتر همان متد `forward` است. ترتیب پارامترها:
گفت‌وگوی مبدأ، شناسهٔ پیام و گفت‌وگوی مقصد. فوروارد، متن و رسانهٔ پیام
اصلی را به سرور معرفی می‌کند و فایل را دوباره آپلود نمی‌کند.

در ارسال عکس و فیلم، مسیر فایل از نوع `str` یا `Path` پذیرفته می‌شود.
آپلود، اندازهٔ فایل، ابعاد، پیش‌نمایش و مدت فیلم خودکار آماده می‌شوند.
فایل اصلی در دیسک تغییر نمی‌کند. مدت فیلم در پروتکل بر حسب میلی‌ثانیه است.

`send_photo` و `upload_photo` برای ارسال به‌عنوان عکس، یک نسخهٔ JPEG
در اندازهٔ حداکثر ۱۰۰۰×۱۰۰۰ با حفظ نسبت تصویر آماده می‌کنند. نام نسخهٔ
ارسالی پسوند `.jpg` دارد؛ فایل اصلی روی دیسک دست‌نخورده می‌ماند.
پیش‌نمایش JPEG معتبر با اندازهٔ حداکثر ۴۰×۴۰ الزامی است. اگر ساخت یا
اعتبارسنجی آن شکست بخورد، ارسال عکس متوقف می‌شود. مرجع `MediaRef` عکس
هم باید همین شرط را داشته باشد. فراخوانی مستقیم RPC `sendMessage` برای
`file_inline.type="Image"` نیز بدون تامنیل معتبر به سرور فرستاده نمی‌شود.

نسخهٔ موقت عکس پس از پایان آپلود پاک می‌شود. اگر انتظار آپلود timeout
یا لغو شود، نسخهٔ موقت برای عملیات صف‌شده نگه داشته می‌شود.
برای خواندن رسانه، Pillow و PyAV در وابستگی‌های پکیج قرار دارند.

پارامترهای اختیاری هر دو متد:

| پارامتر | رفتار |
|---|---|
| `caption=None` | ارسال بدون کپشن؛ برای کپشن یک رشته بده |
| `reply_to_message_id=None` | ارسال در پاسخ به پیام مشخص |
| `wait=True` | انتظار برای تأیید ارسال پیام |
| `timeout=300` | زمان انتظار بر حسب ثانیه، جداگانه برای آپلود و تأیید پیام |

خروجی با `wait=True` از نوع `Message` است و `message_id` دارد. با
`wait=False` ابتدا آپلود کامل می‌شود، سپس خروجی `QueuedOperation` مربوط
به ارسال پیام است. با `client.wait_operation(operation_id)` نتیجهٔ صف
را بررسی کن. timeout انتظار، به‌تنهایی عملیات صف را لغو نمی‌کند.

برای ارسال چندبارهٔ یک فایل، یک بار آپلود کن و `MediaRef` را استفاده کن:

```python
photo = await client.upload_photo("photo.jpg")
await client.send_photo(chat_id, photo)
await client.send_photo(chat_id, photo, caption="همان عکس با کپشن")

video = await client.upload_video("video.mp4", timeout=600)
await client.send_video(chat_id, video)
await client.send_video(chat_id, video, caption="همان فیلم با کپشن")
```

مراجع آپلودشده را در همان حساب استفاده کن. `upload` عمومی، فرادادهٔ
مخصوص عکس و فیلم را آماده نمی‌کند؛ برای مرجع قابل استفاده در این متدها
از `upload_photo` یا `upload_video` استفاده کن.

نمونهٔ کامل در `examples/media_client.py` موجود است.
