"""Extract public RPC names and routing evidence from a supplied Rubika JS bundle.

This reads source text; it never executes JavaScript or inspects browser sessions.
Run: python scripts/extract_web_catalog.py bundle.js output.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def extract(source: str) -> dict:
    constants = dict(re.findall(r'\be\.([A-Za-z]+)="(https?://[^" ]+|wss?://[^" ]+)"', source))
    required = ['DefaultApiUrl', 'GetDcUrl', 'DefaultSocketUrl', 'AppVersion']
    app_version = re.search(r'\be\.AppVersion="([^"]+)"', source)
    if not all(key in constants for key in required[:-1]) or app_version is None:
        raise ValueError('The bundle lacks expected public client constants')
    entries = {}
    for match in re.finditer(r'\bmethod:"([A-Za-z][A-Za-z0-9_]*)"', source):
        name = match[1]
        # Calls use inline configuration objects. Stop at the following .success().
        start = max(source.rfind('getResponsePost({', 0, match.start()),
                    source.rfind('getServiceResponsePost({', 0, match.start()),
                    source.rfind('dcResponsePost({', 0, match.start()))
        end = source.find('}).success', match.end())
        context = source[start:end] if start >= 0 and 0 < end - start < 4000 else source[match.start():match.end()]
        target = re.search(r'dcUrl:(?:vh\.([A-Za-z]+)|"([^"]+)")', context)
        dc = re.search(r'dc_type:Sm\.([A-Za-z]+)', context)
        version = re.search(r'api_version:"([^"]+)"', context)
        service = 'getServiceResponsePost' in context
        mode = 'service' if service else ('plain' if 'not_encrypt:!0' in context else 'encrypted')
        target_url = constants.get(target[1]) if target and target[1] else target[2] if target else None
        fields = []
        model = re.search(r'model:\{([^{}]*)\}', context)
        if model:
            fields = sorted(set(re.findall(r'(?:^|,)\s*([A-Za-z_][A-Za-z0-9_]*):', model[1])))
        item = {
            'operation': name, 'method': 'POST', 'path': '/', 'rpc_method': name,
            'auth': 'not_authorized:!0' not in context,
            'operation_kind': 'read' if name.startswith(('get', 'search', 'check')) or name.endswith('PreviewByJoinLink') else 'mutation',
            'dc_type': dc[1].lower() if dc else 'api', 'wire_mode': mode,
            'evidence': {'offset': match.start(), 'input_fields_observed': fields, 'validation': 'source-only'},
        }
        if target_url:
            item['target_url'] = target_url
        elif re.search(r'dcUrl:[a-z]\b', context):
            item['target_url_field'] = 'dc_url'
        if version:
            item['api_version'] = version[1]
        if name == 'getDCs':
            item.update(auth=False, target_url=constants['GetDcUrl'], api_version='4', wire_mode='plain')
        if name == 'handShake':
            item['wire_mode'] = 'websocket-only'
        entries.setdefault(name, item)
    # These names are in the source's rotated string table and resolved call site.
    for name, authorized in [('signIn', False), ('setPublicKey', True)]:
        if '"'+name+'"' not in source and name != 'setPublicKey':
            raise ValueError('Expected v6 authentication strings are missing')
        entries[name] = dict(operation=name, method='POST', path='/', rpc_method=name,
                             auth=authorized, operation_kind='mutation', api_version='6',
                             evidence={'validation': 'source-only', 'callsite': 'qg' if name == 'signIn' else 'Wg'})
    aliases = {'messages.send': 'sendMessage', 'messages.edit': 'editMessage',
               'messages.delete': 'deleteMessages', 'messages.forward': 'forwardMessages',
               'messages.history': 'getMessages', 'media.upload': 'requestSendFile'}
    for alias, name in aliases.items():
        entries[alias] = {**entries[name], 'operation': alias}
    return {
        'version': 'rubika-web-'+app_version[1], 'protocol': 'rubika',
        'base_url': constants['DefaultApiUrl'],
        'provider': {
            'dc_url': constants['GetDcUrl'], 'socket_url': constants['DefaultSocketUrl'],
            'app_version': app_version[1], 'bot_url': constants['DefaultApiUrl'],
            'rubino_url': constants.get('DefaultRubinoUrl'),
            'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'source_url': 'https://web.rubika.ir/main-es2015.6421623571994c9dd619.js',
            'observed_date': '2026-10-11', 'validation': 'source-only',
            'rpc_method_count': len(entries) - len(aliases),
        },
        'endpoints': [entries[name] for name in sorted(entries)],
        'authentication': dict(request_code_operation='sendCode', verify_code_operation='signIn',
                               phone_field='phone_number', challenge_field='phone_code_hash',
                               code_field='phone_code', token_field='auth'),
        'websocket': None,
        'notes': ['RubikaTransport implements native handshake, AES frames and DC discovery.',
                  'Names and wire formats extracted from public source; account integration is not yet verified.',
                  'handShake is available only through the realtime transport.'],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(extract(args.bundle.read_text(encoding='utf-8')), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
