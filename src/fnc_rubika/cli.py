"""Terminal entry point that requires only a session name, phone number, and OTP."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

from .auth import Client
from .exceptions import FncRubikaError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fnc-rubika", description="Private Rubika session client")
    subparsers = parser.add_subparsers(dest="command", required=True)
    login = subparsers.add_parser("login", help="Create or refresh an encrypted named session")
    login.add_argument("session_name", help="A local name for this Rubika session, for example personal")
    login.add_argument("--contract", type=Path, help="Reviewed contract catalog; omit when one is bundled")
    login.add_argument("--data-dir", type=Path, help="Override the protected local session directory")
    return parser


async def _login(args: argparse.Namespace) -> int:
    client = Client(args.session_name, contract_path=args.contract, data_dir=args.data_dir)
    try:
        await client.login_interactive()
    finally:
        await client.aclose()
    print(f"Session '{args.session_name}' was created securely.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "login":
            return asyncio.run(_login(args))
    except (FncRubikaError, OSError, ValueError) as exc:
        print(f"fnc-rubika: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
