"""Native Rubika wire adapter derived from the public web client.

Source and validation status are recorded in the bundled catalog. No browser
credentials are imported. OTP login creates independent encrypted sessions.
"""
from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Mapping
import hashlib
import json
import math
from pathlib import Path
import platform
import secrets
import string
from typing import Any
from urllib.parse import urlsplit

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Util.Padding import pad, unpad
import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from .contracts import ContractRegistry
from .exceptions import (AccessDeniedError, AmbiguousDeliveryError, ContractError, InvalidCodeError,
                         RateLimitError, RemoteOperationError, SessionExpiredError,
                         TransportError, TwoStepRequiredError)
from .models import Session


_WEB_REFERER = 'https://web.rubika.ir/'


def transform_auth(value: str) -> str:
    result = []
    for char in value:
        if '0' <= char <= '9':
            result.append(chr((13 - (ord(char) - 48)) % 10 + 48))
        elif 'A' <= char <= 'Z':
            result.append(chr((29 - (ord(char) - 65)) % 26 + 65))
        elif 'a' <= char <= 'z':
            result.append(chr((32 - (ord(char) - 97)) % 26 + 97))
        else:
            result.append(char)
    return ''.join(result)


class RubikaCipher:
    def __init__(self, auth: str) -> None:
        if len(auth) != 32 or any(c not in string.ascii_lowercase + string.digits for c in auth):
            raise ContractError('Rubika auth must contain 32 lowercase letters or digits')
        reordered = auth[16:24] + auth[:8] + auth[24:32] + auth[8:16]
        self._key = ''.join(chr((ord(c)-48+5) % 10+48) if c.isdigit()
                            else chr((ord(c)-97+9) % 26+97) for c in reordered).encode()

    def encrypt(self, value: Mapping[str, Any]) -> str:
        plaintext = json.dumps(dict(value), ensure_ascii=False, separators=(',', ':')).encode()
        return base64.b64encode(AES.new(self._key, AES.MODE_CBC, bytes(16)).encrypt(pad(plaintext, 16))).decode()

    def decrypt(self, value: str) -> Mapping[str, Any]:
        try:
            data = unpad(AES.new(self._key, AES.MODE_CBC, bytes(16)).decrypt(base64.b64decode(value, validate=True)), 16)
            result = json.loads(data)
        except (ValueError, UnicodeDecodeError, TypeError) as exc:
            raise TransportError('Rubika returned an invalid encrypted frame') from exc
        if not isinstance(result, Mapping):
            raise TransportError('Rubika returned an invalid object frame')
        return result


def _trusted_url(value: str, *, websocket: bool = False) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    if parsed.scheme != ('wss' if websocket else 'https') or not host.endswith('.iranlms.ir') or parsed.username or parsed.password:
        raise ContractError('The provider returned an unsupported service URL')
    return value


class RubikaTransport:
    def __init__(self, registry: ContractRegistry, session: Session, *, http_client: httpx.AsyncClient | None = None) -> None:
        self.registry = registry
        self.session = session
        self._http = http_client or httpx.AsyncClient(timeout=30)
        self._tmp = ''.join(secrets.choice(string.ascii_lowercase) for _ in range(32))
        self._dcs: dict[str, Any] = {}
        self._dc_lock = asyncio.Lock()
        self._socket_index = 0
        self._sockets: set[Any] = set()
        self._closed = False
        self._prepared = False

    async def validate_session(self) -> None:
        """Check account-wide read access without sending or replaying messages.

        Register the device first: a freshly authenticated session otherwise
        rejects normal account RPCs with NOT_REGISTERED.
        A destination-specific denial remains AccessDeniedError. Only denial
        of every available account check makes the stored session unusable.
        This does not claim that generic INVALID_AUTH proves expiration.
        """
        await self.prepare()
        checks = [('getChats', {})]
        if self.session.account_id:
            checks.append(('getUserInfo', {'user_guid': self.session.account_id}))
        for method, payload in checks:
            try:
                await self.rpc(method, payload)
                return
            except AccessDeniedError:
                continue
        raise SessionExpiredError('The stored session failed all account access checks; sign-in is required')

    async def prepare(self) -> None:
        if self._prepared:
            return
        await self.rpc('registerDevice', {
            'token_type': 'Web', 'token': '',
            'app_version': 'WB_'+self.registry.provider['app_version'], 'lang_code': 'fa',
            'system_version': platform.system(), 'device_model': 'fnc-rubika',
            'device_hash': self.session.device_id or '',
        })
        self._prepared = True

    @property
    def client_info(self) -> dict[str, str]:
        return dict(app_name='Main', app_version=self.registry.provider['app_version'],
                    platform='Web', package='web.rubika.ir', lang_code='fa')

    async def _post(self, url: str, body: Mapping[str, Any], *, plain: bool = False) -> Mapping[str, Any]:
        try:
            response = await self._http.post(_trusted_url(url), content=json.dumps(dict(body), separators=(',', ':')),
                                             headers={'Content-Type': 'application/json' if plain else 'text/plain',
                                                      'Referer': _WEB_REFERER})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise TransportError('Could not connect to Rubika') from exc
        except httpx.HTTPError as exc:
            raise AmbiguousDeliveryError('Rubika request outcome could not be confirmed') from exc
        if response.status_code == 401:
            raise SessionExpiredError('Rubika rejected the current session')
        if response.status_code == 429:
            raise RateLimitError()
        if response.status_code >= 500:
            raise AmbiguousDeliveryError(f'Rubika returned HTTP {response.status_code}; delivery could not be confirmed')
        if response.status_code != 200:
            raise RemoteOperationError(f'Rubika returned HTTP {response.status_code}')
        try:
            result = response.json()
        except ValueError as exc:
            raise AmbiguousDeliveryError('Rubika returned a non-JSON response; delivery could not be confirmed') from exc
        if not isinstance(result, Mapping):
            raise AmbiguousDeliveryError('Rubika returned an invalid response; delivery could not be confirmed')
        return result

    @staticmethod
    def _unwrap(body: Mapping[str, Any]) -> Mapping[str, Any]:
        status, detail = body.get('status'), body.get('status_det')
        if status == 'ERROR_ACTION' and detail == 'INVALID_AUTH':
            raise SessionExpiredError('Rubika rejected the current session')
        if status == 'ERROR_GENERIC' and detail == 'INVALID_AUTH':
            raise AccessDeniedError()
        if detail == 'TOO_REQUESTS':
            raise RateLimitError()
        if detail == 'PASSWORD_HASH_INVALID':
            raise TwoStepRequiredError('The existing two-step password was rejected')
        if status != 'OK':
            # Only expose fixed protocol error names; never interpolate arbitrary bodies.
            known = {'INVALID_INPUT', 'INVALID_METHOD', 'NOT_REGISTERED', 'INVALID_AUTH',
                     'PASSWORD_HASH_INVALID', 'NOT_SUPPORTED_API_VERSION', 'SERVER_ERROR'}
            label = detail if detail in known else 'REMOTE_ERROR'
            raise RemoteOperationError(f'Rubika rejected the operation ({label})')
        data = body.get('data')
        if not isinstance(data, Mapping):
            raise TransportError('Rubika response is missing object data')
        return data

    async def discover(self) -> Mapping[str, Any]:
        if self._dcs:
            return self._dcs
        async with self._dc_lock:
            if not self._dcs:
                body = {'api_version': '4', 'method': 'getDCs', 'data': {}, 'client': self.client_info}
                # The web client includes the raw session auth in this plain v4 call.
                if self.session.access_token:
                    body['auth'] = self.session.access_token
                response = await self._post(self.registry.provider['dc_url'], body, plain=True)
                self._dcs = dict(self._unwrap(response))
        return self._dcs

    async def _url(self, dc_type: str) -> str:
        dcs = await self.discover()
        key = {'api': 'default_api_urls', 'bot': 'default_bot_urls', 'rubino': 'default_rubino_urls'}[dc_type]
        urls = dcs.get(key)
        if isinstance(urls, list) and urls:
            return _trusted_url(str(urls[0]))
        fallback = self.registry.base_url if dc_type == 'api' else self.registry.provider.get(dc_type+'_url')
        if not fallback:
            raise ContractError('The source catalog lacks a service address')
        return _trusted_url(fallback)

    async def rpc(self, method: str, payload: Mapping[str, Any], *, authenticated: bool = True,
                  api_version: str | None = None, url: str | None = None, wire_mode: str = 'encrypted',
                  dc_type: str = 'api') -> Mapping[str, Any]:
        if self._closed:
            raise TransportError('Rubika transport is closed')
        if authenticated and self.session.is_expired:
            raise SessionExpiredError('The stored session has expired')
        if authenticated and not self.session.access_token:
            raise SessionExpiredError('No Rubika session exists')
        auth = self.session.access_token if authenticated else self._tmp
        version = api_version or (self.session.api_version if authenticated else '6')
        if wire_mode in {'plain', 'service'}:
            body = dict(api_version=version, method=method, data=dict(payload), client=self.client_info)
            if authenticated:
                body['auth'] = auth
        elif wire_mode == 'encrypted':
            encrypted = RubikaCipher(auth).encrypt(dict(method=method, input=dict(payload), client=self.client_info))
            body = dict(api_version=version, data_enc=encrypted)
            if authenticated:
                body['auth'] = transform_auth(auth) if version == '6' else auth
                if version == '6':
                    if not self.session.private_key:
                        raise ContractError('Rubika v6 sessions require their own private key')
                    key = RSA.import_key(self.session.private_key)
                    body['sign'] = base64.b64encode(pkcs1_15.new(key).sign(SHA256.new(encrypted.encode()))).decode()
            else:
                body['tmp_session'] = self._tmp
        else:
            raise ContractError('This operation is available only through the realtime stream')
        response = await self._post(url or await self._url(dc_type), body, plain=wire_mode in {'plain', 'service'})
        try:
            if response.get('data_enc') and wire_mode == 'encrypted':
                response = RubikaCipher(auth).decrypt(response['data_enc'])
            return self._unwrap(response)
        except (SessionExpiredError, RateLimitError):
            # These are definitive server rejections, safe for the recovery flow.
            raise
        except TransportError as exc:
            raise AmbiguousDeliveryError('Rubika response could not be decoded; delivery could not be confirmed') from exc

    def supports_idempotency(self, operation: str) -> bool:
        # rnd is visible in source but deduplication guarantees were not verified.
        return False

    async def request(self, operation: str, payload: Mapping[str, Any], *, idempotency_key: str) -> Mapping[str, Any]:
        spec = self.registry.endpoint(operation)
        data = {key: value for key, value in payload.items() if value is not None}
        target_url = spec.target_url
        if spec.target_url_field:
            target_url = data.pop(spec.target_url_field, None)
            if not isinstance(target_url, str):
                raise ContractError('This method requires the dc_url returned by the provider')
            _trusted_url(target_url)
        if operation == 'media.upload':
            return await self._upload(data)
        if operation.startswith('messages.'):
            if 'chat_id' in data:
                data['object_guid'] = data.pop('chat_id')
            if operation in {'messages.send', 'messages.forward'}:
                # Match the web client's newRnd(): an integer string in 1..1,000,000.
                # Keep the same value across retries of this queued operation.
                data['rnd'] = str(int(hashlib.sha256(idempotency_key.encode()).hexdigest(), 16) % 1_000_000 + 1)
            if operation == 'messages.delete':
                data['message_ids'] = [data.pop('message_id')]
                data['type'] = 'Global'
            elif operation == 'messages.forward':
                data['from_object_guid'] = data.pop('from_chat_id')
                data['to_object_guid'] = data.pop('to_chat_id')
                data['message_ids'] = [data.pop('message_id')]
            elif operation == 'messages.history':
                cursor = data.pop('cursor', None)
                data.update(sort='FromMax')
                if cursor:
                    data['max_id'] = cursor
        result = await self.rpc(spec.rpc_method or operation, data, authenticated=spec.auth,
                                api_version=spec.api_version, url=target_url,
                                wire_mode=spec.wire_mode, dc_type=spec.dc_type)
        try:
            return self._normalize_result(operation, data, result)
        except (TransportError, KeyError, TypeError, AttributeError) as exc:
            raise AmbiguousDeliveryError('Rubika response lacks a valid operation result; delivery could not be confirmed') from exc

    def _normalize_result(self, operation: str, data: Mapping[str, Any], result: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation in {'messages.send', 'messages.edit'}:
            update = result.get('message_update') or {}
            message = update.get('message') or update
            return {'message': self._message(message, str(data['object_guid']))}
        if operation == 'messages.forward':
            updates = result.get('message_updates') or []
            if not updates:
                raise TransportError('The forward response lacks message updates')
            return {'message': self._message(updates[0].get('message') or updates[0], str(data['to_object_guid']))}
        if operation == 'messages.history':
            return {**result, 'messages': [self._message(m, str(data['object_guid'])) for m in result.get('messages', [])]}
        return result

    @staticmethod
    def _message(message: Mapping[str, Any], chat_id: str) -> dict[str, Any]:
        if not isinstance(message, Mapping) or not message.get('message_id'):
            raise TransportError('The provider response lacks a message ID')
        return {**message, 'chat_id': message.get('object_guid', chat_id)}

    def decode_push(self, frame: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        if frame.get('type') != 'messenger':
            return []
        data = RubikaCipher(self.session.access_token).decrypt(frame['data_enc']) if frame.get('data_enc') else frame.get('messenger')
        if not isinstance(data, Mapping):
            raise TransportError('The realtime frame lacks messenger data')
        events = []
        for key, values in data.items():
            if not key.endswith('_updates') or not isinstance(values, list):
                continue
            for update in values:
                if not isinstance(update, Mapping):
                    raise TransportError('The realtime update has an invalid shape')
                fingerprint = json.dumps({'kind': key, 'update': update}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
                events.append(dict(event_id=hashlib.sha256(fingerprint.encode()).hexdigest(),
                                   type='message' if key == 'message_updates' else key.removesuffix('_updates'),
                                   payload=dict(update), cursor=None))
        return events

    async def stream_events(self, cursor: str | None) -> AsyncIterator[Mapping[str, Any]]:
        # The web handshake has no resume token. Call update APIs for backfill.
        if self.session.is_expired:
            raise SessionExpiredError('The stored session has expired')
        dcs = await self.discover()
        urls = dcs.get('default_sockets') or [self.registry.provider['socket_url']]
        if not isinstance(urls, list):
            raise TransportError('The provider returned invalid realtime addresses')
        url = _trusted_url(str(urls[self._socket_index % len(urls)]), websocket=True)
        self._socket_index += 1
        try:
            async with connect(url, origin='https://web.rubika.ir', ping_interval=None, open_timeout=20) as socket:
                self._sockets.add(socket)
                try:
                    await socket.send(json.dumps(dict(api_version='5', auth=self.session.access_token, data='', method='handShake')))
                    while True:
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=30)
                        except TimeoutError:
                            await socket.send('{}')
                            raw = await asyncio.wait_for(socket.recv(), timeout=20)
                        try:
                            frame = json.loads(raw)
                        except (ValueError, TypeError) as exc:
                            raise TransportError('The realtime service returned invalid JSON') from exc
                        if not isinstance(frame, Mapping):
                            continue
                        if frame.get('status') == 'ERROR_ACTION' and frame.get('status_det') == 'INVALID_AUTH':
                            raise SessionExpiredError('Rubika rejected the realtime session')
                        for event in self.decode_push(frame):
                            yield event
                finally:
                    self._sockets.discard(socket)
        except InvalidStatus as exc:
            if exc.response.status_code == 401:
                raise SessionExpiredError('Rubika rejected the realtime session') from exc
            raise TransportError('The realtime service rejected the connection') from exc
        except (OSError, WebSocketException, TimeoutError) as exc:
            raise TransportError('Rubika realtime connection failed') from exc

    async def _upload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        path = Path(str(payload['file_path']))
        size = path.stat().st_size
        if size == 0:
            raise ValueError('Cannot upload an empty file')
        metadata = await self.rpc('requestSendFile', {'file_name': path.name, 'size': size, 'mime': path.suffix.lstrip('.')})
        # The web RPC returns "id"; accept "file_id" from older adapters too.
        file_id = metadata.get('id') or metadata.get('file_id')
        if file_id is None or not str(file_id):
            raise AmbiguousDeliveryError('The upload reservation lacks its file ID')
        url = _trusted_url(str(metadata['upload_url']))
        chunk_size, parts = 131072, math.ceil(size / 131072)
        received_hash = None
        with path.open('rb') as file:
            for part in range(1, parts+1):
                chunk = file.read(chunk_size)
                headers = {'Referer': _WEB_REFERER, 'auth': self.session.access_token, 'access-hash-send': str(metadata['access_hash_send']),
                           'file-id': str(file_id), 'part-number': str(part), 'total-part': str(parts), 'chunk-size': str(len(chunk))}
                try:
                    response = await self._http.post(url, content=chunk, headers=headers)
                except httpx.HTTPError as exc:
                    raise AmbiguousDeliveryError('The media upload outcome is unknown') from exc
                if response.status_code == 401:
                    raise SessionExpiredError('Rubika rejected the media session')
                if response.status_code >= 500:
                    raise AmbiguousDeliveryError('The media service failed; upload delivery could not be confirmed')
                if response.status_code != 200:
                    raise RemoteOperationError('Rubika rejected a media part')
                try:
                    body = response.json()
                except ValueError as exc:
                    raise AmbiguousDeliveryError('Invalid upload response; delivery could not be confirmed') from exc
                if not isinstance(body, Mapping):
                    raise AmbiguousDeliveryError('Invalid upload response; delivery could not be confirmed')
                if body.get('status_det') != 'OK':
                    raise RemoteOperationError('Rubika rejected a media part')
                received_hash = (body.get('data') or {}).get('access_hash_rec') or received_hash
        if not received_hash:
            raise AmbiguousDeliveryError('The upload response lacks its access hash; delivery could not be confirmed')
        return dict(file_id=str(file_id), name=path.name, size=size,
                    content_type=payload.get('content_type'), dc_id=metadata.get('dc_id'), access_hash_rec=received_hash)

    async def download(self, file_id: Any, destination: Path) -> Mapping[str, Any]:
        # Rubika requires a file descriptor, not a bare ID.
        from .models import MediaRef
        descriptor = file_id.raw if isinstance(file_id, MediaRef) else file_id
        if not isinstance(descriptor, Mapping) or not all(k in descriptor for k in ('file_id', 'access_hash_rec', 'dc_id', 'size')):
            raise ContractError('Rubika download needs file_id, access_hash_rec, dc_id and size (or a MediaRef)')
        dcs = await self.discover()
        url = _trusted_url(str((dcs.get('storages') or {}).get(str(descriptor['dc_id']), '')))
        headers = {'Referer': _WEB_REFERER, 'auth': self.session.access_token, 'access-hash-rec': str(descriptor['access_hash_rec']),
                   'file-id': str(descriptor['file_id']), 'start-index': '0', 'last-index': str(descriptor['size']), 'Content-Type': 'text/plain'}
        try:
            async with self._http.stream('POST', url, headers=headers) as response:
                if response.status_code == 401:
                    raise SessionExpiredError('Rubika rejected the media session')
                if response.status_code != 200:
                    raise RemoteOperationError('Rubika rejected the media download')
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Atomic replacement keeps an existing file intact on failure.
                temporary = destination.with_name(destination.name+'.'+secrets.token_hex(8)+'.part')
                try:
                    with temporary.open('xb') as output:
                        async for chunk in response.aiter_bytes():
                            output.write(chunk)
                    if temporary.stat().st_size != int(descriptor['size']):
                        raise TransportError('The downloaded file size does not match its descriptor')
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
        except httpx.HTTPError as exc:
            raise TransportError('Rubika media download failed') from exc
        return {**descriptor, 'path': str(destination)}

    async def aclose(self) -> None:
        self._closed = True
        for socket in tuple(self._sockets):
            await socket.close()
        await self._http.aclose()


class RubikaOtpAuthenticator:
    def __init__(self, registry: ContractRegistry) -> None:
        self._transport = RubikaTransport(registry, Session(''))
        self._phone: str | None = None
        self._challenge: str | None = None

    async def begin(self, phone_number: str) -> str:
        return await self.begin_with_password(phone_number, None)

    async def begin_with_password(self, phone_number: str, password: str | None) -> str:
        from .auth import validate_iranian_phone
        self._phone = validate_iranian_phone(phone_number).lstrip('+')
        payload = dict(phone_number=self._phone, send_type='SMS')
        if password is not None:
            payload['pass_key'] = password
        result = await self._transport.rpc('sendCode', payload, authenticated=False)
        if result.get('status') in {'SendPassKey', 'InvalidPassKey'}:
            raise TwoStepRequiredError('Enter the existing Rubika two-step password')
        if result.get('status') != 'OK' or not result.get('phone_code_hash'):
            raise RemoteOperationError('Rubika could not send a verification code')
        self._challenge = str(result['phone_code_hash'])
        return self._challenge

    async def complete(self, challenge_id: str, code: str) -> Session:
        if not self._phone or challenge_id != self._challenge:
            raise ContractError('Begin OTP login before verifying the code')
        if not code.strip().isascii() or not code.strip().isdigit():
            raise InvalidCodeError('Enter a numeric verification code')
        key = await asyncio.to_thread(RSA.generate, 1024)
        public = key.public_key().export_key().decode()
        payload = dict(phone_number=self._phone, phone_code_hash=challenge_id, phone_code=code.strip(),
                       public_key=transform_auth(base64.b64encode(public.encode()).decode()))
        result = await self._transport.rpc('signIn', payload, authenticated=False)
        if result.get('status') == 'CodeIsInvalid':
            raise InvalidCodeError('The verification code is invalid')
        if result.get('status') in {'CodeIsExpired', 'CodeIsUsed'}:
            raise RemoteOperationError('The verification code expired or was already used; start login again')
        if result.get('status') != 'OK' or not result.get('auth'):
            raise RemoteOperationError('Rubika sign-in was rejected')
        try:
            auth = PKCS1_OAEP.new(key).decrypt(base64.b64decode(result['auth'], validate=True)).decode()
            RubikaCipher(auth)
        except (ValueError, UnicodeDecodeError, TypeError) as exc:
            raise TransportError('Rubika returned invalid session material') from exc
        user = result.get('user') or {}
        return Session(auth, device_id=secrets.token_hex(16), private_key=key.export_key().decode(), api_version='6',
                       account_id=str(user['user_guid']) if user.get('user_guid') else None)

    async def aclose(self) -> None:
        await self._transport.aclose()
