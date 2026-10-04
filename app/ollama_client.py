from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import settings


@dataclass
class OllamaResult:
    response_text: str
    duration_ms: int


class OllamaError(RuntimeError):
    pass


def generate(prompt: str, model_name: str | None = None) -> OllamaResult:
    model = model_name or settings.model_name
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
        },
    }

    request = urllib.request.Request(
        f"{settings.ollama_url}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=settings.request_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OllamaError(f"Could not reach Ollama at {settings.ollama_url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OllamaError("Ollama request timed out") from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    response_text = data.get("response", "")
    if not response_text:
        raise OllamaError("Ollama returned an empty response")

    return OllamaResult(response_text=response_text, duration_ms=duration_ms)
