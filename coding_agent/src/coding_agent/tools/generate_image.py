"""Generate an image from a prompt and write it into the workspace."""

from __future__ import annotations

import base64
import inspect
import os
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from core_ai.content import image_part_from_bytes, sniff_image_media_type

GenerateFn = Callable[[str, str], Any]
OUTPUT_FORMATS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
}
FORMAT_MEDIA_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
DEFAULT_MODEL = "gpt-image-1"
DEFAULT_SIZE = "1024x1024"
DEFAULT_TIMEOUT_SECONDS = 120.0


class GenerateImageArgs(ToolArgsModel):
    prompt: str = Field(
        ...,
        min_length=1,
        description="What to generate, e.g. 'a flat app icon of a blue otter'.",
    )
    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Workspace-relative path to write, including an image suffix "
            "(.png, .jpg, .jpeg, or .webp), e.g. 'assets/icon.png'."
        ),
    )


class GenerateImageTool(WorkspaceTool):
    name = "generate_image"
    description = (
        "Generate an image from a text prompt and write it to a workspace path. "
        "Use for icons, mockups, and other visual assets. The path must end in "
        ".png, .jpg, .jpeg, or .webp. Requires OPENAI_API_KEY."
    )
    args_model = GenerateImageArgs

    def __init__(
        self,
        workspace: str | Path,
        *,
        generate: Optional[GenerateFn] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        super().__init__(workspace)
        self._generate = generate
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._transport = transport

    async def run(self, prompt: str, path: str) -> str | list[dict[str, object]]:
        if not isinstance(prompt, str) or not prompt.strip():
            return "error: prompt must be a non-empty string"
        try:
            target = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"

        suffix = target.suffix.lower()
        output_format = OUTPUT_FORMATS.get(suffix)
        if output_format is None:
            return (
                "error: path must end in .png, .jpg, .jpeg, or .webp: "
                f"{path}"
            )

        try:
            payload, media_type = await self._produce(prompt.strip(), output_format)
        except Exception as exc:  # noqa: BLE001
            return f"error: image generation failed: {exc}"

        media_type = (
            sniff_image_media_type(payload, filename=target.name)
            or media_type
            or FORMAT_MEDIA_TYPES[output_format]
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        except OSError as exc:
            return f"error: failed to write {path}: {exc}"

        return [
            {
                "type": "text",
                "text": f"Wrote image {path} ({media_type}, {len(payload):,} bytes)",
            },
            image_part_from_bytes(
                payload,
                media_type=media_type,
                filename=target.name,
            ),
        ]

    async def _produce(self, prompt: str, output_format: str) -> tuple[bytes, str]:
        if self._generate is not None:
            raw = self._generate(prompt, output_format)
            if inspect.isawaitable(raw):
                raw = await raw
            if isinstance(raw, tuple) and len(raw) == 2:
                payload, media_type = raw
                return bytes(payload), str(media_type)
            return bytes(raw), FORMAT_MEDIA_TYPES[output_format]
        return await self._openai_generate(prompt, output_format)

    async def _openai_generate(self, prompt: str, output_format: str) -> tuple[bytes, str]:
        api_key = self._api_key if self._api_key is not None else os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("image generation requires OPENAI_API_KEY")
        base_url = (
            self._base_url
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        model = self._model or os.getenv("OPENAI_IMAGE_MODEL") or DEFAULT_MODEL
        body: dict[str, object] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": DEFAULT_SIZE,
        }
        if str(model).startswith("gpt-image"):
            body["output_format"] = output_format
        else:
            body["response_format"] = "b64_json"

        async with httpx.AsyncClient(
            transport=self._transport, timeout=DEFAULT_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                f"{base_url}/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if response.status_code >= 400:
                raise RuntimeError(_http_error(response))
            payload = response.json()

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise RuntimeError("provider returned no image data")
        item = data[0] if isinstance(data[0], dict) else {}
        encoded = item.get("b64_json")
        if encoded:
            return base64.b64decode(encoded), FORMAT_MEDIA_TYPES[output_format]
        url = str(item.get("url") or "")
        if not url:
            raise RuntimeError("provider returned no image data")
        async with httpx.AsyncClient(
            transport=self._transport, timeout=DEFAULT_TIMEOUT_SECONDS
        ) as client:
            downloaded = await client.get(url)
            if downloaded.status_code >= 400:
                raise RuntimeError(_http_error(downloaded))
            return downloaded.content, FORMAT_MEDIA_TYPES[output_format]


def _http_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
    text = (response.text or "").strip()
    return text or f"HTTP {response.status_code}"
