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
python -m pip install .
python -m fnc_rubika login personal
python -m fnc_rubika methods
```

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

```python
import asyncio
from fnc_rubika import Client

async def main():
    async with Client("personal") as client:
        chats = await client.api.getChats()
        print(chats)

asyncio.run(main())
```

```python
from fnc_rubika import Client

with Client("personal") as client:
    chats = client.getChats()
```

Use `auto_login=False` for unattended applications that must never prompt.
A single process must own each named session store. After an ambiguous mutation
or process crash, delivery becomes `unknown` instead of being retried blindly.
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
