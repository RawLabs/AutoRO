from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import settings
from app.ollama_client import OllamaError, generate as generate_ollama


@dataclass
class ModelResult:
    response_text: str
    duration_ms: int


class ModelError(RuntimeError):
    pass


def generate(
    prompt: str,
    model_name: str | None = None,
    timeout: int | None = None,
    max_tokens: int | None = None,
) -> ModelResult:
    provider = settings.model_provider
    if provider == "ollama":
        try:
            result = generate_ollama(prompt, model_name=model_name)
        except OllamaError as exc:
            raise ModelError(str(exc)) from exc
        return ModelResult(
            response_text=result.response_text,
            duration_ms=result.duration_ms,
        )
    if provider == "llamafile":
        return generate_llamafile(
            prompt,
            model_name=model_name,
            timeout=timeout,
            max_tokens=max_tokens,
        )
    raise ModelError(
        f"Unsupported MODEL_PROVIDER '{settings.model_provider}'. Use 'ollama' or 'llamafile'."
    )


def generate_llamafile(
    prompt: str,
    model_name: str | None = None,
    timeout: int | None = None,
    max_tokens: int | None = None,
) -> ModelResult:
    model = model_name or settings.model_name
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "stream": False,
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": max_tokens if max_tokens is not None else settings.max_response_tokens,
        # Qwen 3 enables a hidden reasoning pass by default. These estimate
        # requests need concise structured output, not a long chain of thought.
        "chat_template_kwargs": {"enable_thinking": False},
    }

    request = urllib.request.Request(
        f"{settings.llamafile_url}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.monotonic()
    req_timeout = timeout if timeout is not None else settings.request_timeout
    try:
        with urllib.request.urlopen(request, timeout=req_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ModelError(f"Llamafile HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ModelError(f"Could not reach Llamafile at {settings.llamafile_url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ModelError("Llamafile request timed out") from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    response_text = extract_openai_chat_response(data)
    if not response_text:
        raise ModelError("Llamafile returned an empty response")

    return ModelResult(response_text=response_text, duration_ms=duration_ms)


def extract_openai_chat_response(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    text = first.get("text")
    if isinstance(text, str):
        return text
    return ""
