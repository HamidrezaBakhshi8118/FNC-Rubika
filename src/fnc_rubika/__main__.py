"""Terminal login and public catalog inspection."""
from __future__ import annotations

import argparse
import asyncio
import sys

from .auth import Client, default_catalog_path
from .contracts import ContractRegistry
from .exceptions import FncRubikaError


def main() -> int:
    parser = argparse.ArgumentParser(prog='fnc-rubika')
    sub = parser.add_subparsers(dest='command', required=True)
    login = sub.add_parser('login', help='Sign in through the terminal and save an encrypted session')
    login.add_argument('session_name', nargs='?', default='personal')
    sub.add_parser('methods', help='List methods from the bundled public web catalog')
    args = parser.parse_args()
    if args.command == 'methods':
        for operation in ContractRegistry.from_file(default_catalog_path()).operations():
            print(operation)
        return 0

    async def sign_in():
        async with Client(args.session_name):
            print('Session is ready. Credentials are stored encrypted.')
    try:
        asyncio.run(sign_in())
    except (KeyboardInterrupt, EOFError):
        print('Login cancelled.', file=sys.stderr)
        return 130
    except FncRubikaError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
