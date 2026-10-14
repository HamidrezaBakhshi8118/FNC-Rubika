# fnc-rubika 0.2

Python 3.11–3.14 Rubika session client with terminal login, encrypted local
sessions, durable message operations, synchronous and asynchronous APIs, and
native HTTP/WebSocket transports.

The bundled catalog contains 205 RPC names found in the public Rubika web
client plus six convenience aliases. Its provenance is recorded in the catalog.
The adapter and login flow pass local protocol tests. Public DC discovery was
also tested against the service. Account login, message delivery and all method
schemas still need account integration testing; name coverage is not a claim
that every method has been validated live.

```powershell
python -m pip install "git+https://github.com/HamidrezaBakhshi8118/FNC-Rubika.git@main"
```

No login command is required. The first `async with Client("personal")`
prompts for the phone number and OTP when the named session does not exist.

`Client("personal")` creates `personal.rubika` in the current working directory.
`Client("personal.rubika")` opens the same file. Use `data_dir="sessions"` to
choose a different directory, and `client.session_path` to inspect the path.
The file contains encrypted SQLite state, including the session, inbox and
outbox. Starting with 0.2.7, new sessions use a password-derived key (scrypt)
and AES-256-GCM, with non-secret salt and key verification metadata inside the
same database. New sessions do not require an OS keyring. Set
`FNC_RUBIKA_SESSION_PASSWORD` for unattended Linux/PM2 runs, pass
`session_password=` to `Client`, or enter the password using the hidden terminal
prompt. Use a strong password of at least 12 characters. It is not stored.
After stopping the process, copy the closed `.rubika` file to another system
and open it with the same password; no path, user or OS binding is used.
Do not copy an active SQLite database while its WAL still contains changes.

Existing OS-keyring sessions keep working on their original system. To move one,
install the optional `keyring` extra and export an encrypted portable copy there:

```powershell
python -m fnc_rubika export-session personal portable/personal.rubika --from-keyring
```

The command obtains the export password from the same environment variable or
a hidden prompt. It performs no network requests and never overwrites the source
or an existing destination. Copy the exported file, then set the same password on
the server. Existing explicit `PassphraseKeyProvider` sessions still use their
`.salt` sidecar; export them too if a single-file session is required.

Version 0.2.5 no longer
automatically opens the earlier `%LOCALAPPDATA%/fnc-rubika/*.sqlite3` stores;
those files remain untouched, and the local `.rubika` session prompts for a
new login on first use.

When the session is missing, locally expired or rejected by the provider,
`Client` prompts for a phone number, OTP and, if required, the existing two-step
password. OTPs and passwords are hidden and not stored. Session keys and the
v6 signing key are encrypted locally.

All built-in terminal messages and login prompts are in English. Persian and
Arabic digits are still accepted for phone numbers and verification codes.

`ERROR_ACTION/INVALID_AUTH` triggers session renewal. Rubika's web client treats
`ERROR_GENERIC/INVALID_AUTH` as access denied; this raises `AccessDeniedError`,
which also inherits from `RemoteOperationError`. Before starting workers, the
named client registers the device with `registerDevice`, then checks account
access using `getChats` and, if necessary, the
account's own `getUserInfo`. If all account checks are denied, it requests a
fresh login once. A rejected fresh session raises `SessionRenewalError` without
repeating OTP requests. Network errors do not trigger login. A denial limited
to the destination still raises `AccessDeniedError`. This response alone does
not prove the session has expired. Failed operations
are recorded without automatic replay. Message `rnd` values follow the web
client's range of 1 through 1,000,000.

To investigate `ERROR_GENERIC/INVALID_AUTH`, use an existing session:

```powershell
python -m fnc_rubika diagnose personal --chat-id YOUR_DESTINATION_GUID
```

The English JSON report distinguishes read access for the account from access
to the destination and reports `SendMessages` permission when returned by the
provider. It omits credentials, phone numbers, GUIDs, profiles, chat titles and
messages. Diagnosis runs direct read requests with the outbox and realtime
workers stopped; it does not initiate OTP login or send queued messages.
Successful read checks do not prove that sending will succeed. An inconclusive
report is not a reason to delete the session.

```python
import asyncio
from fnc_rubika import Client

async def main():
    async with Client("personal") as client:
        await client.send("YOUR_DESTINATION_GUID", "سلام")

asyncio.run(main())
```

`client.messages.send(...)` remains available. Message and media services have
concrete types, and the package includes `py.typed` for editor completion.

Photos, videos, captions and forwards have readable client methods:

```python
await client.forward_message(source_chat_id, message_id, destination_chat_id)
await client.send_photo(chat_id, "photo.jpg")
await client.send_photo(chat_id, "photo.jpg", caption="Photo caption")
await client.send_video(chat_id, "video.mp4")
await client.send_video(chat_id, "video.mp4", caption="Video caption")
```

Dimensions, a thumbnail and video duration are read automatically.
`send_photo()` prepares a JPEG copy fitting within 1000×1000 pixels and requires
a valid JPEG preview fitting within 40×40 pixels before sending. The source
file is preserved. Missing or invalid photo previews also block direct
`sendMessage` calls carrying an Image descriptor.

Use `upload_photo()` or `upload_video()` to upload once and reuse the returned
`MediaRef` in multiple sends. The same methods are available in synchronous
clients. See [the Persian media guide](docs/MEDIA.fa.md) for queue and timeout
behavior and [the complete example](examples/media_client.py).

`Client` and `SyncClient` expose all 205 catalog RPC names as explicit methods,
for example `await client.getChats()` or
`await client.getUserInfo(user_guid="YOUR_USER_GUID")`. Their keyword payloads
follow the provider's method schemas; name completion does not imply that every
payload schema or server operation has been verified live. Regenerate these
definitions after updating the catalog with `python scripts/generate_client_methods.py`.

In VS Code select the project's `venv\\Scripts\\python.exe` interpreter. A
successful `pip install` into another Python installation will not be visible
to Pylance or to the Run button that uses a different interpreter.

```python
from fnc_rubika import Client

with Client("personal") as client:
    chats = client.getChats()
```

Use `auto_login=False` for unattended applications that must never prompt.
A single process must own each named session store. After an ambiguous mutation
or process crash, delivery becomes `unknown` instead of being retried blindly.
Closing the client during a mutation, malformed success responses, and HTTP 5xx
responses also leave delivery unconfirmed. Retry is automatic only when the
transport explicitly guarantees idempotency. Failed terminal renewal raises
`SessionRenewalError` and stops repeated login prompts until explicit login
replaces the session.
The web protocol has no observed WebSocket resume token: update APIs are
available for application backfill, but automatic gap recovery is not implemented.

- [Persian usage guide](docs/USER_GUIDE.fa.md)
- [Public web method catalog](docs/WEB_METHODS.fa.md)
- [Protocol evidence and limits](docs/CONTRACT_CATALOG.fa.md)
- [API reference](docs/API_REFERENCE.fa.md)
- [Session guide](docs/SESSIONS.fa.md)
- [Review and validation report](docs/REVIEW.fa.md)
- [Offline HTML guide](docs/site/index.html)
- [Async example](examples/async_client.py)
- [Sync example](examples/sync_client.py)
