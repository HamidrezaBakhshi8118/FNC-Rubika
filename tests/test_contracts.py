from __future__ import annotations

import pytest

from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.exceptions import UnsupportedOperationError


def test_registry_reads_reviewed_contract_shape():
    registry = ContractRegistry.from_mapping(
        {
            "version": "test-v1",
            "base_url": "https://example.invalid",
            "endpoints": [
                {
                    "operation": "messages.send",
                    "method": "POST",
                    "path": "/messages",
                    "idempotency_header": "Idempotency-Key",
                }
            ],
        }
    )
    assert registry.endpoint("messages.send").supports_idempotency is True
    with pytest.raises(UnsupportedOperationError):
        registry.endpoint("messages.delete")
