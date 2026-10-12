"""Read-only access probes with credential-free, English reports."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .exceptions import (AccessDeniedError, AmbiguousDeliveryError, ContractError,
                         FncRubikaError, RateLimitError, RemoteOperationError,
                         SessionExpiredError, TransportError)
from .messages import normalize_chat_id
from .transport import Transport


async def diagnose_access(transport: Transport, *, account_id: str | None, chat_id: str | None = None) -> dict[str, Any]:
    """Probe read APIs directly, without starting the outbox or sending messages.

    Never return response bodies, credentials, phone numbers, profile fields,
    chat titles, message text, or account/destination identifiers.
    """
    destination = normalize_chat_id(chat_id) if chat_id is not None else None
    checks: list[dict[str, str]] = []

    async def probe(operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        try:
            result = await transport.request(operation, payload, idempotency_key='diagnostic-read')
            status = 'ok' if isinstance(result, Mapping) else 'invalid_response'
        except AccessDeniedError:
            status = 'access_denied'
        except SessionExpiredError:
            status = 'session_rejected'
        except RateLimitError:
            status = 'rate_limited'
        except AmbiguousDeliveryError:
            status = 'unconfirmed_response'
        except TransportError:
            status = 'connection_failed'
        except RemoteOperationError:
            status = 'remote_rejected'
        except ContractError:
            status = 'unsupported_contract'
        except FncRubikaError:
            status = 'client_error'
        except Exception:
            status = 'unexpected_error'
        checks.append({'operation': operation, 'result': status})
        return result if status == 'ok' else None

    chats_result = await probe('getChats', {})
    session_read_ok = checks[-1]['result'] == 'ok'
    if account_id:
        await probe('getUserInfo', {'user_guid': account_id})
        checks[-1]['scope'] = 'own_account'
        session_read_ok = session_read_ok or checks[-1]['result'] == 'ok'

    report: dict[str, Any] = {'checks': checks, 'read_access_verified': session_read_ok}
    if destination is not None:
        report['destination_is_own_account'] = bool(account_id and destination == account_id)
        chats = chats_result.get('chats') if chats_result is not None else None
        chat = None
        if isinstance(chats, list):
            chat = next((item for item in chats if isinstance(item, Mapping) and item.get('object_guid') == destination), None)
            report['destination_in_first_chat_page'] = chat is not None

        # This user-info input is observed in the public web client. For other
        # object types, getAbsObjects is a read-only existence probe.
        if destination.startswith('u'):
            info = await probe('getUserInfo', {'user_guid': destination})
            user = info.get('user') if info is not None else None
            if isinstance(user, Mapping):
                report['destination_resolved'] = user.get('user_guid') == destination
            if info is not None and isinstance(info.get('chat'), Mapping):
                chat = info['chat']
        else:
            info = await probe('getAbsObjects', {'objects_guids': [destination]})
            objects = info.get('abs_objects') if info is not None else None
            if isinstance(objects, list):
                report['destination_resolved'] = any(isinstance(item, Mapping) and item.get('object_guid') == destination for item in objects)
        checks[-1]['scope'] = 'destination'
        session_read_ok = session_read_ok or checks[-1]['result'] == 'ok'
        report['read_access_verified'] = session_read_ok

        if isinstance(chat, Mapping):
            # Only expose known protocol labels and permission booleans.
            status = chat.get('status')
            if status in ('Active', 'ObjRemoved', 'NoAccess', 'Stopped', 'NotExist'):
                report['destination_chat_status'] = status
            access = chat.get('access')
            if isinstance(access, list):
                report['destination_can_send'] = 'SendMessages' in access

    destination_check = next((check for check in checks if check.get('scope') == 'destination'), None)
    if session_read_ok:
        if destination_check and destination_check['result'] == 'access_denied':
            assessment = 'destination_read_access_denied'
        elif report.get('destination_can_send') is False:
            assessment = 'destination_send_permission_missing'
        elif report.get('destination_resolved') is False:
            assessment = 'destination_not_resolved'
        else:
            assessment = 'read_access_verified_send_failure_unresolved'
    elif any(check['result'] == 'session_rejected' for check in checks):
        assessment = 'session_rejected'
    elif all(check['result'] == 'access_denied' for check in checks):
        assessment = 'account_or_protocol_access_denied'
    else:
        assessment = 'read_checks_inconclusive'
    report['assessment'] = assessment
    return report
