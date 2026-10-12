# fnc-rubika 0.2

Python 3.11?3.14 Rubika session client with terminal login, encrypted local
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

When the session is missing, locally expired or rejected by the provider,
`Client` prompts for a phone number, OTP and, if required, the existing two-step
password. OTPs and passwords are hidden and not stored. Session keys and the
v6 signing key are encrypted locally.

All built-in terminal messages and login prompts are in English. Persian and
Arabic digits are still accepted for phone numbers and verification codes.

`ERROR_ACTION/INVALID_AUTH` triggers session renewal. Rubika's web client treats
`ERROR_GENERIC/INVALID_AUTH` as access denied; this raises `AccessDeniedError`,
which also inherits from `RemoteOperationError`. Check that the destination GUID
belongs to the intended chat and that the account has permission to send there.
This response alone does not prove the session has expired. Failed operations
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
        await client.messages.send("u0BZZ2v005a960184e514f3254431d0c", "سلام")

asyncio.run(main())
```

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
