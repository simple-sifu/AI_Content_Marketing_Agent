"""Offline tests for the Image Generator: one test per I/O matrix row via graph.invoke.

The LLM is faked (tests/conftest.py FakeLLM) and so is the OpenAI images client
(FakeImages); images are saved under pytest's tmp_path, so no key and no network are needed."""

from __future__ import annotations

from pathlib import Path

import httpx
import openai
import pytest
from langchain_core.exceptions import OutputParserException
from PIL import Image

from content_agent import images, llm
from content_agent.graph import graph
from content_agent.images import ImagePrompt, image_generator
from content_agent.router import RouteDecision
from tests.conftest import FakeLLM, png_b64

REQUEST = "Make an image of a sunrise over a city"
TOPIC = "sunrise over a city"
PROMPT = "A golden sunrise over a dense city skyline, warm light, wide angle, photorealistic."
SECRET = "sk-test-SECRET-123"


def _fake(prompt: str = PROMPT, **kwargs) -> FakeLLM:
    return FakeLLM(
        {
            RouteDecision: RouteDecision(intent="image", topic=TOPIC),
            ImagePrompt: ImagePrompt(prompt=prompt),
        },
        **kwargs,
    )


def _api_error(cls, status: int):
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    response = httpx.Response(status, request=request)
    return cls(f"rejected for key {SECRET}", response=response, body=None)


def _assert_png(path: str, tmp_path: Path) -> None:
    saved = Path(path)
    assert saved.parent == tmp_path / "outputs"
    assert saved.suffix == ".png"
    assert saved.name.split("-", 1)[1].startswith("sunrise-over-a-city-")
    with Image.open(saved) as img:
        assert img.format == "PNG"
        assert img.size == (4, 4)


def test_gpt_image_1_answers(use_llm, use_images, tmp_path):
    fake = use_llm(_fake())
    client = use_images([png_b64()])

    result = graph.invoke({"request": REQUEST})

    assert result["intent"] == "image"
    assert result["image_model"] == "gpt-image-1"
    assert result["image_prompt"] == PROMPT
    assert result["errors"] == []
    _assert_png(result["image_path"], tmp_path)
    assert result["final_output"] == (
        f"**Image saved:** `{result['image_path']}`\n**Model:** gpt-image-1\n**Prompt:** {PROMPT}\n"
    )
    assert client.calls == [{"model": "gpt-image-1", "prompt": PROMPT, "n": 1, "size": "1024x1024"}]
    assert fake.schemas_called() == ["RouteDecision", "ImagePrompt"]
    enhance_prompt = fake.calls[-1][1]
    assert REQUEST in enhance_prompt and f"Topic: {TOPIC}" in enhance_prompt


def test_falls_back_to_dall_e_3(use_llm, use_images, tmp_path):
    use_llm(_fake())
    client = use_images([_api_error(openai.PermissionDeniedError, 403), png_b64()])

    result = graph.invoke({"request": REQUEST})

    assert client.models() == ["gpt-image-1", "dall-e-3"]
    assert client.calls[1] == {"model": "dall-e-3", "prompt": PROMPT, "n": 1, "size": "1024x1024"}
    assert result["image_model"] == "dall-e-3"
    assert result["errors"] == ["image_generator: gpt-image-1 failed (PermissionDeniedError)"]
    _assert_png(result["image_path"], tmp_path)


def test_falls_back_to_dall_e_2_with_truncated_prompt(use_llm, use_images, tmp_path):
    long_prompt = "x" * 2000  # the node caps the enhanced prompt at 800 first
    use_llm(_fake(prompt=long_prompt))
    client = use_images(
        [_api_error(openai.BadRequestError, 400), _api_error(openai.NotFoundError, 404), png_b64()]
    )

    result = graph.invoke({"request": REQUEST})

    assert client.models() == ["gpt-image-1", "dall-e-3", "dall-e-2"]
    assert all(len(c["prompt"]) <= 1000 for c in client.calls)
    assert len(client.calls[2]["prompt"]) == images.PROMPT_MAX
    assert result["image_model"] == "dall-e-2"
    assert result["errors"] == [
        "image_generator: gpt-image-1 failed (BadRequestError)",
        "image_generator: dall-e-3 failed (NotFoundError)",
    ]
    _assert_png(result["image_path"], tmp_path)


def test_dall_e_2_limit_applies_to_its_prompt():
    assert dict(images.IMAGE_MODELS)["dall-e-2"] == 1000


@pytest.mark.parametrize("unusable", [None, "", "bm90IGFuIGltYWdl", "***not base64***"])
def test_unusable_response_falls_back(use_llm, use_images, tmp_path, unusable):
    use_llm(_fake())
    client = use_images([unusable, png_b64()])

    result = graph.invoke({"request": REQUEST})

    assert client.models() == ["gpt-image-1", "dall-e-3"]
    assert result["image_model"] == "dall-e-3"
    assert result["errors"] == ["image_generator: gpt-image-1 failed (UnusableImage)"]
    _assert_png(result["image_path"], tmp_path)


def test_all_models_fail(use_llm, use_images, tmp_path):
    use_llm(_fake())
    client = use_images(
        [
            _api_error(openai.PermissionDeniedError, 403),
            _api_error(openai.BadRequestError, 400),
            _api_error(openai.RateLimitError, 429),
        ]
    )

    result = graph.invoke({"request": REQUEST})

    assert client.models() == ["gpt-image-1", "dall-e-3", "dall-e-2"]
    assert result["intent"] == "error"
    assert result["image_path"] == "" and result["image_model"] == ""
    out = result["final_output"]
    assert "- gpt-image-1: PermissionDeniedError" in out
    assert "- dall-e-3: BadRequestError" in out
    assert "- dall-e-2: RateLimitError" in out
    assert result["errors"] == [
        "image_generator: gpt-image-1 failed (PermissionDeniedError)",
        "image_generator: dall-e-3 failed (BadRequestError)",
        "image_generator: dall-e-2 failed (RateLimitError)",
    ]
    assert SECRET not in out and all(SECRET not in e for e in result["errors"])
    assert not (tmp_path / "outputs").exists() or not any((tmp_path / "outputs").iterdir())


@pytest.mark.parametrize("error", [_api_error(openai.RateLimitError, 429), OutputParserException("bad")])
def test_enhancement_failure_ends_run(use_llm, use_images, error):
    use_llm(_fake(errors={ImagePrompt: error}))
    client = use_images([png_b64()])

    result = graph.invoke({"request": REQUEST})

    kind = type(error).__name__
    assert result["intent"] == "error"
    assert kind in result["final_output"]
    assert result["errors"] == [f"image_generator: {kind}"]
    assert client.calls == []


def test_missing_key_for_image_client(use_llm, monkeypatch):
    use_llm(_fake())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "get_image_client", lambda: openai.OpenAI())  # the real one

    result = graph.invoke({"request": REQUEST})

    assert result["intent"] == "error"
    assert "OPENAI_API_KEY" in result["final_output"]
    assert result["errors"] == ["image_generator: OpenAIError"]


def test_save_failure_ends_run(use_llm, use_images, monkeypatch, tmp_path):
    use_llm(_fake())
    use_images([png_b64()])
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file where the folder should be")
    monkeypatch.setenv("IMAGE_OUTPUT_DIR", str(blocker))

    result = graph.invoke({"request": REQUEST})

    assert result["intent"] == "error"
    assert "could not save the image from gpt-image-1" in result["final_output"]
    assert result["errors"] == ["image_generator: OSError"]
    assert result["image_path"] == ""


@pytest.mark.parametrize("intent", ["research", "blog", "linkedin"])
def test_other_intents_never_reach_image_generator(monkeypatch, use_llm, use_images, intent):
    from content_agent import research
    from tests.test_research import _fake as research_fake

    monkeypatch.setenv("SERPAPI_API_KEY", "serp-key")
    monkeypatch.setattr(research, "serpapi_search", lambda query, api_key: [])
    fake = use_llm(research_fake(intent))
    client = use_images([png_b64()])

    result = graph.invoke({"request": REQUEST})

    assert result["intent"] == intent
    assert "ImagePrompt" not in fake.schemas_called()
    assert client.calls == []
    assert result["image_path"] == ""


def test_empty_request_never_reaches_image_generator(use_images):
    client = use_images([png_b64()])

    result = graph.invoke({"request": "  "})

    assert result["intent"] == "empty"
    assert client.calls == []


def test_direct_call_keeps_earlier_errors(use_llm, use_images):
    use_llm(FakeLLM({ImagePrompt: ImagePrompt(prompt=PROMPT)}))
    use_images([_api_error(openai.InternalServerError, 500), png_b64()])

    result = image_generator({"request": REQUEST, "topic": TOPIC, "errors": ["earlier"]})

    assert result["errors"] == ["earlier", "image_generator: gpt-image-1 failed (InternalServerError)"]


def test_cmyk_image_is_converted_and_saved(use_llm, use_images, tmp_path):
    import base64
    from io import BytesIO

    buffer = BytesIO()
    Image.new("CMYK", (4, 4)).save(buffer, format="JPEG")
    use_llm(_fake())
    use_images([base64.b64encode(buffer.getvalue()).decode()])

    result = graph.invoke({"request": REQUEST})

    assert result["image_model"] == "gpt-image-1"
    _assert_png(result["image_path"], tmp_path)


def test_reused_thread_clears_previous_image(use_llm, use_images):
    from langgraph.checkpoint.memory import InMemorySaver

    from content_agent.graph import build_graph

    threaded = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "img"}}
    use_llm(_fake())
    use_images([png_b64()])
    first = threaded.invoke({"request": REQUEST}, config)
    assert first["image_model"] == "gpt-image-1"

    use_images([_api_error(openai.RateLimitError, 429)])
    second = threaded.invoke({"request": REQUEST}, config)

    assert second["intent"] == "error"
    assert second["image_path"] == "" and second["image_model"] == ""


def test_reused_thread_clears_target_format(use_llm, use_images, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    from content_agent import research
    from content_agent.blog import BlogDraft
    from content_agent.graph import build_graph
    from tests.test_research import TOPIC as RESEARCH_TOPIC
    from tests.test_research import _fake as research_fake
    from tests.test_research import _results
    from tests.test_validators import draft

    monkeypatch.setenv("SERPAPI_API_KEY", "serp-key")
    monkeypatch.setattr(research, "serpapi_search", lambda query, api_key: _results("a"))
    threaded = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "fmt"}}
    blog = research_fake("blog", target_format="blog")
    blog.responses[BlogDraft] = draft(RESEARCH_TOPIC, mentions=4)
    use_llm(blog)
    first = threaded.invoke({"request": "Write a blog post about AI in B2B marketing"}, config)
    assert first["target_format"] == "blog"

    use_llm(_fake())
    use_images([png_b64()])
    second = threaded.invoke({"request": REQUEST}, config)

    assert second["intent"] == "image"
    assert second["target_format"] == ""
