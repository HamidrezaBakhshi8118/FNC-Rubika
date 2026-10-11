# fnc-rubika

`fnc-rubika` is a private, clean-room Python foundation for an authorised
Rubika session client.  Version `0.1` implements durable message operations,
media hooks, encrypted local state, and at-least-once event delivery.

It deliberately contains no guessed Rubika endpoints. A named terminal login
flow is available as `fnc-rubika login <session-name>`; it prompts for a
`+989…` phone number and OTP without putting either in application source.
Live login becomes available when the package ships a reviewed Rubika contract
catalog produced from authorised documentation and a dedicated test account.

## Documentation

- [Persian quick start](docs/USER_GUIDE.fa.md)
- [Complete Persian API reference](docs/API_REFERENCE.fa.md)
- [Multi-session and security guide](docs/SESSIONS.fa.md)
- [Endpoint / WebSocket catalog policy](docs/CONTRACT_CATALOG.fa.md)
- [Offline HTML documentation](docs/site/index.html) (open this file locally)
- [Maintainer guide](docs/README.fa.md)

The normal async API is intentionally simple:

```python
from fnc_rubika import Client

async with Client("personal") as client:
    await client.messages.send("chat-id", "سلام")
```

`Client("personal")` is already the session-aware client.  The lower-level
`async_client()` method remains available only for advanced integrations.
