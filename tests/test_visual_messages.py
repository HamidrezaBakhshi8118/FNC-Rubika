from __future__ import annotations

import asyncio
import base64
from io import BytesIO
import json

import av
import httpx
from PIL import Image
import pytest

from fnc_rubika import Client, MediaRef, Session, SyncClient
from fnc_rubika.models import QueuedOperation
from fnc_rubika.exceptions import OperationUnknownError, RemoteOperationError
from fnc_rubika.rubika import RubikaCipher, RubikaTransport


AUTH = 'abcdefghijklmnopqrstuvwxyz012345'


class TestKey:
    def get_key(self, path):
        return bytes(32)


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / 'photo.jpg'
    Image.new('RGB', (320, 180), 'navy').save(path)
    return path


@pytest.fixture
def video(tmp_path):
    path = tmp_path / 'video.mp4'
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('mpeg4', rate=2)
        stream.width, stream.height, stream.pix_fmt = 64, 48, 'yuv420p'
        for index in range(4):
            frame = av.VideoFrame.from_image(Image.new('RGB', (64, 48), (index * 40, 0, 0)))
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return path


def make_client(tmp_path, *, fail_upload=False, ambiguous_send=False):
    calls, parts, sends = [], [], []

    def server(request):
        assert request.headers['Referer'] == 'https://web.rubika.ir/'
        if request.url.host == 'storage.iranlms.ir':
            assert request.headers['file-id'] == '42'
            parts.append(request.content)
            return httpx.Response(200, json={'status_det': 'OK', 'data': {'access_hash_rec': 'download-hash'}})
        inner = RubikaCipher(AUTH).decrypt(json.loads(request.content)['data_enc'])
        method, payload = inner['method'], inner['input']
        calls.append(method)
        if method in ('registerDevice', 'getChats'):
            data = {'chats': []}
        elif method == 'requestSendFile':
            if fail_upload:
                reply = {'status': 'ERROR_GENERIC', 'status_det': 'INVALID_INPUT'}
                return httpx.Response(200, json={'data_enc': RubikaCipher(AUTH).encrypt(reply)})
            data = {'id': 42, 'dc_id': '1', 'access_hash_send': 'upload-hash', 'upload_url': 'https://storage.iranlms.ir/'}
        elif method == 'sendMessage':
            sends.append(payload)
            if ambiguous_send:
                return httpx.Response(503)
            data = {'message_update': {'message': {'message_id': str(len(sends)), **payload}}}
        elif method == 'forwardMessages':
            sends.append(payload)
            data = {'message_updates': [{'message': {'message_id': 'forwarded'}}]}
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={'data_enc': RubikaCipher(AUTH).encrypt({'status': 'OK', 'data': data})})

    client = Client('test', data_dir=tmp_path, key_provider=TestKey(), auto_login=False)
    client.store.save_secret('session', Session(AUTH).as_dict())
    def transport_factory(session):
        transport = RubikaTransport(client.registry, session, http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))
        transport._dcs = {'default_api_urls': ['https://messenger.iranlms.ir/']}
        async def stream_events(cursor):
            await asyncio.Event().wait()
            yield {}
        transport.stream_events = stream_events
        return transport
    client._transport = transport_factory
    return client, calls, parts, sends


@pytest.mark.parametrize('kind', ['photo', 'video'])
@pytest.mark.parametrize('caption', [None, 'کپشن آزمایشی'])
def test_named_client_sends_visual_with_native_payload(tmp_path, photo, video, kind, caption):
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path)
        path = photo if kind == 'photo' else video
        async with client:
            message = await getattr(client, 'send_' + kind)('#c=destination', path, caption=caption,
                reply_to_message_id='previous', timeout=2)
            assert message.chat_id == 'destination'
            assert message.message_id == '1'
        assert calls == ['registerDevice', 'getChats', 'requestSendFile', 'sendMessage']
        if kind == 'video':
            assert b''.join(parts) == path.read_bytes()
        else:
            with Image.open(BytesIO(b''.join(parts))) as uploaded_photo:
                assert uploaded_photo.format == 'JPEG'
                assert uploaded_photo.size == (320, 180)
        payload = sends[0]
        assert payload['object_guid'] == 'destination'
        assert payload['reply_to_message_id'] == 'previous'
        assert payload.get('text') == caption
        assert 'text' in payload if caption is not None else 'text' not in payload
        assert 1 <= int(payload['rnd']) <= 1_000_000
        inline = payload['file_inline']
        assert inline['type'] == ('Image' if kind == 'photo' else 'Video')
        assert inline['file_id'] == '42'
        assert inline['dc_id'] == '1'
        assert inline['size'] == len(b''.join(parts))
        assert inline['mime'] == ('jpg' if kind == 'photo' else 'mp4')
        assert (inline['width'], inline['height']) == ((320, 180) if kind == 'photo' else (64, 48))
        if kind == 'video':
            assert inline['time'] == 2000  # Rubika uses milliseconds.
        with Image.open(BytesIO(base64.b64decode(inline['thumb_inline']))) as preview:
            assert preview.format == 'JPEG'
            assert max(preview.size) <= 40
        assert not {'file_path', 'access_hash_send', 'content_type', 'upload_url', 'name'} & inline.keys()
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['photo', 'video'])
def test_uploaded_visual_is_reused_and_wait_false_queues_only_message(tmp_path, photo, video, kind):
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path)
        path = photo if kind == 'photo' else video
        async with client:
            uploaded = await getattr(client, 'upload_' + kind)(path, timeout=2)
            assert isinstance(uploaded, MediaRef)
            await getattr(client, 'send_' + kind)('destination', uploaded, timeout=2)
            queued = await getattr(client, 'send_' + kind)('destination', uploaded, caption='caption', wait=False)
            assert isinstance(queued, QueuedOperation)
            assert queued.operation == 'messages.send'
            await client.wait_operation(queued.operation_id, timeout=2)
        assert calls.count('requestSendFile') == 1
        assert len(sends) == 2
        assert sends[0]['file_inline'] == sends[1]['file_inline']
    asyncio.run(scenario())


def test_forward_alias_uses_source_and_destination_guids(tmp_path):
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path)
        async with client:
            message = await client.forward_message('#c=source', '123', '#c=destination', timeout=2)
            assert message.chat_id == 'destination'
            assert message.message_id == 'forwarded'
        assert sends[0]['from_object_guid'] == 'source'
        assert sends[0]['to_object_guid'] == 'destination'
        assert sends[0]['message_ids'] == ['123']
    asyncio.run(scenario())


def test_invalid_media_input_does_not_upload_or_send(tmp_path, photo):
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path)
        async with client:
            for chat, path, caption, exception in [('', photo, None, ValueError),
                    ('destination', photo, 123, TypeError),
                    ('destination', tmp_path / 'missing.jpg', None, FileNotFoundError)]:
                with pytest.raises(exception):
                    await client.send_photo(chat, path, caption=caption)
            with pytest.raises(ValueError, match='matching upload'):
                await client.send_photo('destination', MediaRef('42'))
        assert calls == ['registerDevice', 'getChats']
        assert not parts and not sends
    asyncio.run(scenario())


def test_upload_rejection_does_not_send_message(tmp_path, photo):
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path, fail_upload=True)
        async with client:
            with pytest.raises(RemoteOperationError):
                await client.send_photo('destination', photo, timeout=2)
        assert 'sendMessage' not in calls
    asyncio.run(scenario())


def test_unconfirmed_media_message_is_not_sent_twice(tmp_path, photo):
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path, ambiguous_send=True)
        async with client:
            with pytest.raises(OperationUnknownError):
                await client.send_photo('destination', photo, timeout=2)
        assert calls.count('sendMessage') == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['photo', 'video'])
def test_sync_client_exposes_typed_visual_methods(tmp_path, photo, video, kind):
    client, calls, parts, sends = make_client(tmp_path)
    with SyncClient(client) as sync:
        uploaded = getattr(sync, 'upload_' + kind)(photo if kind == 'photo' else video, timeout=2)
        message = getattr(sync, 'send_' + kind)('destination', uploaded, caption='caption', timeout=2)
        assert message.message_id == '1'
    assert calls.count('requestSendFile') == 1


@pytest.mark.parametrize('bad_thumbnail', [None, '', 'not-base64', base64.b64encode(b'not an image').decode()])
@pytest.mark.parametrize('wait', [False, True])
def test_photo_without_valid_thumbnail_is_never_queued(tmp_path, photo, bad_thumbnail, wait):
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path)
        async with client:
            uploaded = await client.upload_photo(photo, timeout=2)
            invalid = MediaRef.from_dict({**uploaded.raw, 'thumb_inline': bad_thumbnail})
            with pytest.raises(ValueError, match='valid JPEG thumbnail'):
                await client.send_photo('destination', invalid, wait=wait)
        assert calls.count('requestSendFile') == 1
        assert 'sendMessage' not in calls
        assert not sends
    asyncio.run(scenario())


def test_photo_thumbnail_generation_failure_stops_before_upload(tmp_path, photo, monkeypatch):
    monkeypatch.setattr('fnc_rubika.media_metadata._thumbnail', lambda image: '')
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path)
        async with client:
            with pytest.raises(ValueError, match='valid JPEG thumbnail'):
                await client.send_photo('destination', photo)
        assert calls == ['registerDevice', 'getChats']
        assert not parts and not sends
    asyncio.run(scenario())


def test_direct_send_message_cannot_bypass_photo_thumbnail_requirement(tmp_path):
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path)
        async with client:
            with pytest.raises(RemoteOperationError, match='valid JPEG thumbnail'):
                await client.sendMessage(object_guid='destination', file_inline={'type': 'Image', 'file_id': '42'}, timeout=2)
        assert calls == ['registerDevice', 'getChats']
        assert not sends
    asyncio.run(scenario())


def test_large_transparent_photo_is_prepared_and_original_is_unchanged(tmp_path):
    photo = tmp_path / 'large.png'
    Image.new('RGBA', (2400, 1200), (255, 0, 0, 0)).save(photo)
    original_bytes = photo.read_bytes()
    async def scenario():
        client, calls, parts, sends = make_client(tmp_path)
        async with client:
            message = await client.send_photo('destination', photo, timeout=2)
            assert message.message_id == '1'
        inline = sends[0]['file_inline']
        assert (inline['width'], inline['height']) == (1000, 500)
        assert inline['mime'] == 'jpg'
        assert inline['file_name'] == 'large.jpg'
        with Image.open(BytesIO(b''.join(parts))) as uploaded:
            assert uploaded.size == (1000, 500)
            assert uploaded.getpixel((0, 0)) == (255, 255, 255)
        assert photo.read_bytes() == original_bytes
    asyncio.run(scenario())


@pytest.mark.parametrize('format,size', [('PNG', (40, 40)), ('JPEG', (41, 40))])
def test_wrong_thumbnail_format_or_dimensions_are_rejected(format, size):
    from fnc_rubika.media_metadata import require_photo_thumbnail
    buffer = BytesIO()
    Image.new('RGB', size).save(buffer, format=format)
    with pytest.raises(ValueError, match='valid JPEG thumbnail'):
        require_photo_thumbnail(base64.b64encode(buffer.getvalue()).decode())
