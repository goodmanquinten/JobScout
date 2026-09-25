"""Pytest fixtures."""

import sqlite3

import pytest

from jobscout.store import Store


@pytest.fixture
def store() -> Store:
    return Store(sqlite3.connect(":memory:"))
