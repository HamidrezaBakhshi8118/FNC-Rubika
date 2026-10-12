from __future__ import annotations

import pytest

from fnc_rubika.messages import normalize_chat_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("u0BZZ2v005a960184e514f3254431d0c", "u0BZZ2v005a960184e514f3254431d0c"),
        ("#c=u0BZZ2v005a960184e514f3254431d0c", "u0BZZ2v005a960184e514f3254431d0c"),
        ("https://web.rubika.ir/#c=u0BZZ2v005a960184e514f3254431d0c", "u0BZZ2v005a960184e514f3254431d0c"),
    ],
)
def test_normalize_chat_id(value: str, expected: str) -> None:
    assert normalize_chat_id(value) == expected


@pytest.mark.parametrize("value", ["", "#c=", "https://example.com/"])
def test_normalize_chat_id_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="chat_id"):
        normalize_chat_id(value)
