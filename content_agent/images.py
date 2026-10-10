"""Image Generator: enhances the request into a visual prompt, then tries each image model
in turn (gpt-image-1 -> DALL-E 3 -> DALL-E 2) and saves the first image as a PNG with Pillow.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import secrets
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import openai
from langchain_core.exceptions import OutputParserException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.research import _LLM_ERRORS, _llm_failure, _topic
from content_agent.state import ContentState

NODE_NAME = "image_generator"
PROMPT_MAX = 800
SIZE = "1024x1024"
DEFAULT_OUTPUT_DIR = "outputs"

# (model, prompt character limit). Every model gets the same parameters: the images endpoint
# rejects `response_format` (unknown_parameter), so a response without data[0].b64_json
# counts as that model's failure.
IMAGE_MODELS = (
    ("gpt-image-1", 32000),
    ("dall-e-3", 4000),
    ("dall-e-2", 1000),
)

ENHANCE_PROMPT = """You write prompts for an image generation model. Turn the user's request
into one detailed visual prompt: subject, setting, composition, style, lighting and mood.
Plain text, at most {max_chars} characters, no text or logos in the image unless asked.

User request:
{request}

Topic: {topic}
"""

ALL_FAILED_MESSAGE = (
    "No image model could generate this image:\n{lines}\n\n"
    "Check that your OpenAI account has access to these models, or rephrase the request."
)
SAVE_FAILED_MESSAGE = (
    "The image generator could not save the image from {model} ({kind}). "
    "Check that the output folder ({folder}) is writable."
)
# Modes Pillow can write as PNG; anything else (e.g. CMYK) is converted before saving.
_PNG_MODES = frozenset({"1", "L", "LA", "I", "I;16", "P", "RGB", "RGBA"})
SUCCESS_TEMPLATE = "**Image saved:** `{path}`\n**Model:** {model}\n**Prompt:** {prompt}\n"


class ImagePrompt(BaseModel):
    prompt: str = Field(description=f"Detailed visual prompt, at most {PROMPT_MAX} characters.")


class UnusableImage(ValueError):
    """The model answered, but without image data Pillow can decode."""


def _enhance(state: ContentState, topic: str) -> str:
    structured = llm.get_llm(temperature=0.7).with_structured_output(ImagePrompt)
    result = structured.invoke(
        ENHANCE_PROMPT.format(
            max_chars=PROMPT_MAX, request=(state.get("request") or "").strip(), topic=topic
        )
    )
    if not isinstance(result, ImagePrompt):
        raise OutputParserException("structured output did not match ImagePrompt")
    return " ".join(result.prompt.split())[:PROMPT_MAX] or topic


def _generate(client, model: str, prompt: str) -> Image.Image:
    """One model's attempt; raises openai.OpenAIError or UnusableImage on failure."""
    response = client.images.generate(model=model, prompt=prompt, n=1, size=SIZE)
    data = getattr(response, "data", None) or []
    b64 = getattr(data[0], "b64_json", None) if data else None
    if not b64:
        raise UnusableImage("no image data")
    try:
        image = Image.open(BytesIO(base64.b64decode(b64, validate=True)))
        image.load()
        if image.mode not in _PNG_MODES:
            image = image.convert("RGBA")
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnusableImage(type(exc).__name__) from exc
    return image


def _output_dir() -> Path:
    return Path(os.getenv("IMAGE_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR)


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40].strip("-") or "image"


def _save(image: Image.Image, topic: str) -> Path:
    folder = _output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"{stamp}-{_slug(topic)}-{secrets.token_hex(3)}.png"
    image.save(path, format="PNG")
    return path


def image_generator(state: ContentState) -> dict:
    topic = _topic(state)
    try:
        prompt = _enhance(state, topic)
    except _LLM_ERRORS as exc:
        return _llm_failure(state, NODE_NAME, exc)

    errors = list(state.get("errors") or [])
    failed: list[tuple[str, str]] = []
    try:
        client = llm.get_image_client()  # with no key the client raises OpenAIError here
    except openai.OpenAIError as exc:
        return _llm_failure(state, NODE_NAME, exc)

    for model, limit in IMAGE_MODELS:
        try:
            image = _generate(client, model, prompt[:limit])
        except (openai.OpenAIError, UnusableImage) as exc:
            # Class name only: OpenAI error text can echo request details.
            kind = "UnusableImage" if isinstance(exc, UnusableImage) else type(exc).__name__
            failed.append((model, kind))
            errors.append(f"{NODE_NAME}: {model} failed ({kind})")
            continue
        try:
            path = _save(image, topic)
        except OSError as exc:
            kind = type(exc).__name__
            return {
                "intent": "error",
                "image_prompt": prompt,
                "final_output": SAVE_FAILED_MESSAGE.format(
                    model=model, kind=kind, folder=_output_dir()
                ),
                "errors": errors + [f"{NODE_NAME}: OSError"],  # the matrix's entry; kind is in the message
            }
        return {
            "image_prompt": prompt,
            "image_path": str(path),
            "image_model": model,
            "final_output": SUCCESS_TEMPLATE.format(path=path, model=model, prompt=prompt),
            "errors": errors,
        }

    lines = "\n".join(f"- {model}: {kind}" for model, kind in failed)
    return {
        "intent": "error",
        "image_prompt": prompt,
        "final_output": ALL_FAILED_MESSAGE.format(lines=lines),
        "errors": errors,
    }
