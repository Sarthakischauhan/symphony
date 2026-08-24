"""Provider-neutral multimodal content helpers.

Canonical user/assistant parts look like:

    {"type": "text", "text": "hello"}
    {"type": "image", "media_type": "image/png", "data": "<base64>", "filename": "shot.png"}
    {"type": "image", "media_type": "image/jpeg", "url": "https://example.com/a.jpg"}

Providers translate this shape into their native request payloads. Incoming
OpenAI / Anthropic / Gemini image parts are normalized back to the canonical
form so mixed histories keep working.
"""

from __future__ import annotations

import base64
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
from urllib.parse import unquote, urlparse

from core_ai.types import Content

ContentPart = Dict[str, Any]

IMAGE_TOKEN_ESTIMATE = 768
_DATA_URL_RE = re.compile(
    r"^data:(?P<media>image/[A-Za-z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)


def text_from_content(content: Optional[Content]) -> str:
    """Return the human-readable text from a message body."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    chunks: List[str] = []
    for part in _iter_parts(content):
        kind = _part_type(part)
        if kind == "text":
            text = str(part.get("text") or "")
            if text:
                chunks.append(text)
        elif kind == "image":
            chunks.append(f"[image:{_image_filename(part)}]")
    return "\n".join(chunks)


def normalize_content(content: Optional[Content]) -> List[ContentPart]:
    """Expand a message body into canonical text/image parts."""
    if content is None or content == "":
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    parts: List[ContentPart] = []
    for item in content:
        part = _normalize_part(item)
        if part is not None:
            parts.append(part)
    return parts


def to_openai_chat_content(content: Optional[Content]) -> Content:
    """Chat Completions content: string or text / image_url parts."""
    if isinstance(content, str) or content is None:
        return content or ""
    parts: List[ContentPart] = []
    for part in normalize_content(content):
        if part["type"] == "text":
            parts.append({"type": "text", "text": part.get("text") or ""})
            continue
        url = _openai_image_url(part)
        if url:
            parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


def to_openai_responses_content(content: Optional[Content], *, role: str = "user") -> Content:
    """Responses API content: string, or input_text / input_image parts."""
    if isinstance(content, str) or content is None:
        return content or ""
    text_type = "output_text" if role == "assistant" else "input_text"
    parts: List[ContentPart] = []
    for part in normalize_content(content):
        if part["type"] == "text":
            parts.append({"type": text_type, "text": part.get("text") or ""})
            continue
        url = _openai_image_url(part)
        if url:
            parts.append({"type": "input_image", "image_url": url})
    return parts


def to_anthropic_blocks(content: Optional[Content]) -> List[ContentPart]:
    """Anthropic Messages content blocks."""
    blocks: List[ContentPart] = []
    for part in normalize_content(content):
        if part["type"] == "text":
            text = part.get("text") or ""
            if text:
                blocks.append({"type": "text", "text": text})
            continue
        source = _anthropic_image_source(part)
        if source is not None:
            blocks.append({"type": "image", "source": source})
    return blocks


def to_gemini_parts(content: Optional[Content]) -> List[ContentPart]:
    """Gemini generateContent parts."""
    parts: List[ContentPart] = []
    for part in normalize_content(content):
        if part["type"] == "text":
            text = part.get("text") or ""
            if text:
                parts.append({"text": text})
            continue
        media_type = str(part.get("media_type") or "image/png")
        data = part.get("data")
        url = str(part.get("url") or "")
        if data:
            parts.append({"inlineData": {"mimeType": media_type, "data": data}})
        elif url.startswith(("http://", "https://")):
            parts.append({"fileData": {"mimeType": media_type, "fileUri": url}})
        elif url:
            parsed = _parse_data_url(url)
            if parsed is not None:
                parts.append(
                    {
                        "inlineData": {
                            "mimeType": parsed[0],
                            "data": parsed[1],
                        }
                    }
                )
    return parts


def image_part(
    *,
    media_type: str,
    data: Optional[str] = None,
    url: Optional[str] = None,
    filename: Optional[str] = None,
) -> ContentPart:
    part: ContentPart = {"type": "image", "media_type": media_type}
    if data:
        part["data"] = data
    if url:
        part["url"] = url
    if filename:
        part["filename"] = filename
    return part


def image_part_from_bytes(
    payload: bytes,
    *,
    media_type: str,
    filename: Optional[str] = None,
) -> ContentPart:
    return image_part(
        media_type=media_type,
        data=base64.b64encode(payload).decode("ascii"),
        filename=filename,
    )


def estimate_content_tokens(content: Optional[Content]) -> int:
    """Heuristic tokens for a message body, without dumping image bytes."""
    if content is None:
        return 0
    if isinstance(content, str):
        return _text_tokens(content)
    total = 0
    for part in normalize_content(content):
        if part["type"] == "image":
            total += IMAGE_TOKEN_ESTIMATE
        else:
            total += _text_tokens(str(part.get("text") or ""))
    return total


def _text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _iter_parts(content: Sequence[Any]) -> Iterable[Dict[str, Any]]:
    for item in content:
        if isinstance(item, dict):
            yield item


def _part_type(part: Dict[str, Any]) -> str:
    declared = str(part.get("type") or "")
    if declared in {"text", "input_text", "output_text"}:
        return "text"
    if declared in {"image", "image_url", "input_image"}:
        return "image"
    if "inlineData" in part or "fileData" in part or "source" in part:
        return "image"
    if "text" in part:
        return "text"
    return declared or "unknown"


def _normalize_part(item: Any) -> Optional[ContentPart]:
    if not isinstance(item, dict):
        if item is None or item == "":
            return None
        return {"type": "text", "text": str(item)}

    kind = _part_type(item)
    if kind == "text":
        text = item.get("text")
        return {"type": "text", "text": "" if text is None else str(text)}

    if kind != "image":
        return None

    media_type = str(item.get("media_type") or item.get("mime_type") or "")
    data = item.get("data")
    url = item.get("url")
    filename = item.get("filename") or item.get("name")

    nested = item.get("image_url")
    if isinstance(nested, dict):
        url = nested.get("url") or url
    elif isinstance(nested, str) and nested:
        url = nested

    source = item.get("source")
    if isinstance(source, dict):
        media_type = str(source.get("media_type") or media_type)
        if source.get("type") == "base64" and source.get("data"):
            data = source.get("data")
        elif source.get("url"):
            url = source.get("url")

    inline = item.get("inlineData") or item.get("inline_data")
    if isinstance(inline, dict):
        media_type = str(inline.get("mimeType") or inline.get("mime_type") or media_type)
        data = inline.get("data") or data

    file_data = item.get("fileData") or item.get("file_data")
    if isinstance(file_data, dict):
        media_type = str(file_data.get("mimeType") or file_data.get("mime_type") or media_type)
        url = file_data.get("fileUri") or file_data.get("file_uri") or url

    if isinstance(url, str):
        parsed = _parse_data_url(url)
        if parsed is not None:
            media_type = media_type or parsed[0]
            data = data or parsed[1]
            url = None

    if not media_type:
        media_type = "image/png"

    part = image_part(
        media_type=media_type,
        data=str(data) if data else None,
        url=str(url) if url else None,
        filename=str(filename) if filename else None,
    )
    if "data" not in part and "url" not in part:
        return None
    return part


def _image_filename(part: Dict[str, Any]) -> str:
    name = part.get("filename")
    if name:
        return str(name)
    url = str(part.get("url") or "")
    if url:
        path = unquote(urlparse(url).path)
        leaf = path.rsplit("/", 1)[-1]
        if leaf:
            return leaf
    media = str(part.get("media_type") or "image")
    suffix = media.split("/", 1)[-1] or "png"
    return f"image.{suffix}"


def _openai_image_url(part: Dict[str, Any]) -> Optional[str]:
    data = part.get("data")
    media_type = str(part.get("media_type") or "image/png")
    if data:
        return f"data:{media_type};base64,{data}"
    url = str(part.get("url") or "")
    return url or None


def _anthropic_image_source(part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    data = part.get("data")
    media_type = str(part.get("media_type") or "image/png")
    if data:
        return {"type": "base64", "media_type": media_type, "data": data}
    url = str(part.get("url") or "")
    if url.startswith(("http://", "https://")):
        return {"type": "url", "url": url}
    parsed = _parse_data_url(url) if url else None
    if parsed is not None:
        return {"type": "base64", "media_type": parsed[0], "data": parsed[1]}
    return None


def _parse_data_url(value: str) -> Optional[tuple[str, str]]:
    match = _DATA_URL_RE.match(value.strip())
    if match is None:
        return None
    data = re.sub(r"\s+", "", match.group("data"))
    return match.group("media").lower(), data
