"""Pytest fixtures built on tests.helpers."""

from __future__ import annotations

import pytest

from tests.helpers import make_mock_client


@pytest.fixture
def mock_client_factory():
    return make_mock_client
