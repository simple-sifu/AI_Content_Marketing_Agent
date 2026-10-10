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


def png_b64(color: str = "red") -> str:
    """A real 4x4 PNG, base64-encoded, as the images API returns it."""
    import base64
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class FakeImages:
    """Stands in for openai.OpenAI(): `images.generate(**kwargs).data[0].b64_json`.

    `outcomes` gives one item per call (the last repeats): a base64 string, None (a
    response with no data), or an exception to raise. Every call's kwargs are recorded."""

    def __init__(self, outcomes: list):
        self.outcomes = outcomes
        self.calls: list[dict] = []
        self.images = self

    def generate(self, **kwargs):
        from types import SimpleNamespace

        self.calls.append(kwargs)
        outcome = self.outcomes[min(len(self.calls), len(self.outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        data = [] if outcome is None else [SimpleNamespace(b64_json=outcome)]
        return SimpleNamespace(data=data)

    def models(self) -> list[str]:
        return [c["model"] for c in self.calls]


@pytest.fixture
def use_images(monkeypatch, tmp_path):
    """Install a FakeImages client and save images under tmp_path/outputs."""
    monkeypatch.setenv("IMAGE_OUTPUT_DIR", str(tmp_path / "outputs"))

    def install(outcomes: list) -> FakeImages:
        fake = FakeImages(outcomes)
        monkeypatch.setattr(llm, "get_image_client", lambda: fake)
        return fake

    return install
