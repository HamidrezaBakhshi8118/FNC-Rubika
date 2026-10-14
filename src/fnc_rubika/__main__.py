"""Terminal login and public catalog inspection."""
from __future__ import annotations

import argparse
import asyncio
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import sys

from .auth import Client, default_catalog_path
from .contracts import ContractRegistry
from .exceptions import FncRubikaError


def main() -> int:
    parser = argparse.ArgumentParser(prog='fnc-rubika')
    sub = parser.add_subparsers(dest='command', required=True)
    login = sub.add_parser('login', help='Sign in through the terminal and save an encrypted session')
    login.add_argument('session_name', nargs='?', default='personal')
    login.add_argument('--data-dir')
    diagnose = sub.add_parser('diagnose', help='Check stored session and destination access using read APIs')
    diagnose.add_argument('session_name', nargs='?', default='personal')
    diagnose.add_argument('--data-dir')
    diagnose.add_argument('--chat-id', help='Destination GUID or Rubika web conversation URL')
    sub.add_parser('methods', help='List methods from the bundled public web catalog')
    export = sub.add_parser('export-session', help='Export a portable encrypted session without network access')
    export.add_argument('session_name')
    export.add_argument('destination')
    export.add_argument('--data-dir')
    export.add_argument('--from-keyring', action='store_true', help='Read a legacy source using its original OS-keyring key')
    args = parser.parse_args()
    if args.command == 'methods':
        for operation in ContractRegistry.from_file(default_catalog_path()).operations():
            print(operation)
        return 0

    async def sign_in():
        async with Client(args.session_name, data_dir=args.data_dir):
            print('Session is ready. Credentials are stored encrypted.')

    async def run_diagnostics():
        from .diagnostics import diagnose_access
        client = Client(args.session_name, data_dir=args.data_dir, auto_login=False)
        try:
            if not client.has_session():
                report = {'assessment': 'session_missing'}
            else:
                low_level = client.async_client()
                session = low_level.load_session()
                if session.is_expired:
                    report = {'assessment': 'stored_session_expired'}
                else:
                    # No start()/context entry: the outbox and realtime workers
                    # remain stopped throughout these direct read requests.
                    report = await diagnose_access(low_level.transport, account_id=session.account_id, chat_id=args.chat_id)
                    report['session_api_version'] = session.api_version if session.api_version in {'4', '5', '6'} else 'unknown'
            try:
                report['package_version'] = version('fnc-rubika')
            except PackageNotFoundError:
                report['package_version'] = 'source_checkout'
            print(json.dumps(report, ensure_ascii=True, indent=2))
        finally:
            await client.aclose()
    try:
        if args.command == 'export-session':
            from .auth import _SESSION_NAME
            from .exceptions import SecurityConfigurationError
            from .storage import EncryptedSQLiteStore, KeyringKeyProvider
            from .session_keys import DefaultSessionKeyProvider
            name = args.session_name.removesuffix('.rubika')
            if not _SESSION_NAME.fullmatch(name):
                raise ValueError('Invalid source session name')
            path = Path(args.data_dir or Path.cwd()) / f'{name}.rubika'
            store = EncryptedSQLiteStore.open_readonly(
                path, key_provider=KeyringKeyProvider(create=False) if args.from_keyring else DefaultSessionKeyProvider(),
            )
            try:
                if not store.load_secret('session'):
                    raise SecurityConfigurationError('Source session has no saved authentication material')
                path = store.export_portable(args.destination)
                print(f'Portable encrypted session exported to {path}. No network workers were started.')
            finally:
                store.close()
            return 0
        asyncio.run(run_diagnostics() if args.command == 'diagnose' else sign_in())
    except (KeyboardInterrupt, EOFError):
        print('Login cancelled.', file=sys.stderr)
        return 130
    except FncRubikaError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError:
        print('Invalid input. Check the session name and destination GUID or Rubika conversation URL.', file=sys.stderr)
        return 1
    except OSError:
        print('Unable to access the session file or export destination; no existing export was overwritten.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
