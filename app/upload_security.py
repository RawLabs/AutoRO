from __future__ import annotations

import os
from pathlib import Path
from typing import Any


MAX_PDF_UPLOAD_BYTES = 25 * 1024 * 1024


async def stream_pdf_upload(
    request: Any,
    destination: Path,
    max_bytes: int = MAX_PDF_UPLOAD_BYTES,
) -> int:
    """Stream a PDF to disk without buffering the full request body."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header.") from exc
        if declared_size < 0 or declared_size > max_bytes:
            raise ValueError("Uploaded PDF is too large. Limit is 25 MB.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.part")
    total = 0
    signature = bytearray()
    try:
        with partial.open("wb") as output:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Uploaded PDF is too large. Limit is 25 MB.")
                if len(signature) < 4:
                    signature.extend(chunk[: 4 - len(signature)])
                output.write(chunk)
        if total == 0:
            raise ValueError("Uploaded PDF was empty.")
        if bytes(signature) != b"%PDF":
            raise ValueError("Uploaded file does not look like a PDF.")
        os.replace(partial, destination)
        return total
    except BaseException:
        partial.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
