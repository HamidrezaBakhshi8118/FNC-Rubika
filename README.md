# fnc-rubika

`fnc-rubika` is a private, clean-room Python foundation for an authorised
Rubika session client.  Version `0.1` implements durable message operations,
media hooks, encrypted local state, and at-least-once event delivery.

It deliberately contains no guessed Rubika endpoints. A named terminal login
flow is available as `fnc-rubika login <session-name>`; it prompts for a
`+989…` phone number and OTP without putting either in application source.
Live login becomes available when the package ships a reviewed Rubika contract
catalog produced from authorised documentation and a dedicated test account.

See [the Persian user guide](docs/USER_GUIDE.fa.md) and the [maintainer guide](docs/README.fa.md)
for setup, security, event handling, and the contract-catalog workflow.
