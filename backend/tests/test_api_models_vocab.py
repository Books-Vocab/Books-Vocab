from __future__ import annotations

import pytest
from pydantic import ValidationError

from kg.api_models.vocab import BatchArchiveRequest, BatchDeleteRequest


@pytest.mark.parametrize("model", [BatchDeleteRequest, BatchArchiveRequest])
@pytest.mark.parametrize("bad_word", ["", "   ", "x" * 201])
def test_batch_vocab_requests_reject_invalid_words(model, bad_word):
    with pytest.raises(ValidationError):
        model(words=["valid", bad_word])


@pytest.mark.parametrize("model", [BatchDeleteRequest, BatchArchiveRequest])
def test_batch_vocab_requests_accept_max_length_words(model):
    req = model(words=["x" * 200])
    assert req.words == ["x" * 200]
