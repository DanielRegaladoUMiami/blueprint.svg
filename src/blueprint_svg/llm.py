"""LLM client — calls the Hugging Face Inference API and returns a Diagram.

We use `huggingface_hub.InferenceClient`'s chat-completions interface, which
works across providers (HF Inference, Together, Fireworks, ...). The user
controls the backbone with an env var (`BP_TEXT_MODEL`, `BP_VISION_MODEL`)
so the same code path works for paid and free tiers.

The model can lie about JSON shape. We don't trust it: we strip code fences,
parse, and validate with pydantic. Errors bubble up so the UI can show them.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Optional

from huggingface_hub import InferenceClient

from blueprint_svg.ir import Diagram, DiagramType
from blueprint_svg.prompts import build_messages

# Defaults are deliberately small — they fit the HF free serverless tier,
# so the Space works for anonymous visitors without a token. Users can
# upgrade to the 72B variants by setting the env var or pasting a token
# in the UI (the env vars then become the floor, not a hard cap).
DEFAULT_TEXT_MODEL = os.getenv("BP_TEXT_MODEL", "Qwen/Qwen2.5-7B-Instruct")
DEFAULT_VISION_MODEL = os.getenv("BP_VISION_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")

# Models we'll try as fallbacks when the user provides their own token,
# in case the chosen provider doesn't host the default.
_TEXT_FALLBACKS = ["Qwen/Qwen2.5-72B-Instruct", "meta-llama/Llama-3.3-70B-Instruct"]


class LLMError(RuntimeError):
    """Raised when the model returns something we can't parse into a Diagram."""


def _resolve_token(token: Optional[str]) -> Optional[str]:
    """Return the token to use, or None to call anonymously.

    Order: explicit arg → HF_TOKEN env → HUGGINGFACE_HUB_TOKEN env → None.
    Anonymous calls work for the free serverless tier on small models.
    """
    return (
        token
        or os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_HUB_TOKEN")
        or None
    )


def _client(token: Optional[str] = None) -> InferenceClient:
    resolved = _resolve_token(token)
    # provider="auto" with no token defaults to the free HF serverless backend.
    return InferenceClient(token=resolved, provider="auto")


def generate_from_text(
    prompt: str,
    diagram_type: DiagramType,
    model: Optional[str] = None,
    token: Optional[str] = None,
) -> Diagram:
    """Generate a Diagram IR from a text prompt.

    If the caller passes a token we silently upgrade the default model to
    the 72B variant — the user is paying for inference, give them quality.
    """
    chosen_model = model or (
        _TEXT_FALLBACKS[0] if _resolve_token(token) and model is None else DEFAULT_TEXT_MODEL
    )
    messages = build_messages(prompt, diagram_type)
    raw = _chat(messages, chosen_model, token)
    return _parse_diagram(raw)


def generate_from_image(
    image_bytes: bytes,
    diagram_type: DiagramType,
    prompt: str = "Re-create this diagram cleanly.",
    model: Optional[str] = None,
    token: Optional[str] = None,
    mime: str = "image/png",
) -> Diagram:
    """Generate a Diagram IR from an input image (whiteboard photo, screenshot, ...)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    messages = build_messages(prompt, diagram_type, image_data_url=data_url)
    raw = _chat(messages, model or DEFAULT_VISION_MODEL, token)
    return _parse_diagram(raw)


def _chat(messages: list[dict], model: str, token: Optional[str]) -> str:
    client = _client(token)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2048,
            temperature=0.2,
        )
    except Exception as e:  # noqa: BLE001 — surface whatever the SDK raises
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg or "authentication" in msg.lower():
            raise LLMError(
                f"This model ({model!r}) needs authentication. "
                "Paste a free HF token in the 'Hugging Face token' accordion — "
                "create one at https://huggingface.co/settings/tokens with the "
                "'Make calls to Inference Providers' scope."
            ) from e
        if "429" in msg or "rate" in msg.lower():
            raise LLMError(
                "Rate limited by the free serverless tier. Wait a minute, or "
                "paste your own token in the accordion to get a higher quota."
            ) from e
        raise LLMError(f"Inference call failed on model {model!r}: {e}") from e
    choice = resp.choices[0]
    content = choice.message.content
    if not content:
        raise LLMError("Model returned empty content.")
    return content


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_diagram(raw: str) -> Diagram:
    """Strip code fences if any, parse JSON, validate against the IR."""
    text = _FENCE_RE.sub("", raw).strip()
    # Some models still wrap with prose. Try to locate the first {...} block.
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMError(f"No JSON object found in model output:\n{raw[:500]}")
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"Model output was not valid JSON: {e}\n---\n{text[:500]}") from e
    try:
        diagram = Diagram.model_validate(data)
        diagram.validate_refs()
    except Exception as e:  # noqa: BLE001 — pydantic / our own ValueError
        raise LLMError(f"Model output did not match the Diagram schema: {e}") from e
    return diagram


def image_bytes_from_pil(img) -> bytes:
    """Helper: convert a PIL Image to PNG bytes (used by the Gradio handler)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
