"""Shared offline fakes: a structured-output fake LLM and a no-network guard."""

from __future__ import annotations

import socket

import pytest

from content_agent import llm


class _Structured:
    def __init__(self, fake: "FakeLLM", schema):
        self.fake, self.schema = fake, schema

    def invoke(self, prompt):
        self.fake.calls.append((self.schema.__name__, prompt))
        error = self.fake.errors.get(self.schema, self.fake.error)
        if error is not None:
            raise error
        response = self.fake.responses[self.schema]
        if isinstance(response, list):  # successive calls get successive items; the last repeats
            index = sum(1 for name, _ in self.fake.calls if name == self.schema.__name__) - 1
            response = response[min(index, len(response) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


class FakeLLM:
    """Returns `responses[schema]` (a list gives one item per call, the last repeating; an
    exception item is raised); raises `errors[schema]`, else `error` for every schema."""

    def __init__(
        self,
        responses: dict | None = None,
        error: Exception | None = None,
        errors: dict | None = None,
    ):
        self.responses = responses or {}
        self.error = error
        self.errors = errors or {}
        self.calls: list[tuple[str, str]] = []

    def with_structured_output(self, schema):
        return _Structured(self, schema)

    def schemas_called(self) -> list[str]:
        return [name for name, _ in self.calls]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def guard(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def use_llm(monkeypatch):
    def install(fake: FakeLLM) -> FakeLLM:
        monkeypatch.setattr(llm, "get_llm", lambda *a, **k: fake)
        return fake

    return install
