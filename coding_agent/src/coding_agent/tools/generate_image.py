"""Generate an image from a prompt and write it into the workspace."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable, Optional

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
            "Path to write, including an image suffix (.png, .jpg, .jpeg, or .webp). "
            "Relative paths start at the working directory."
        ),
    )


class GenerateImageTool(WorkspaceTool):
    name = "generate_image"
    description = (
        "Generate an image from a text prompt and write it to a path. "
        "Uses the current OpenAI or Gemini provider (same credentials as chat). "
        "The path must end in .png, .jpg, .jpeg, or .webp."
    )
    args_model = GenerateImageArgs

    def __init__(
        self,
        workspace: str | Path,
        *,
        generate: Optional[GenerateFn] = None,
        registry: Any = None,
        model_id: Optional[str] = None,
    ) -> None:
        super().__init__(workspace)
        self._generate = generate
        self._registry = registry
        self._model_id = model_id

    async def run(self, prompt: str, path: str) -> str | list[dict[str, object]]:
        if not isinstance(prompt, str) or not prompt.strip():
            return "error: prompt must be a non-empty string"
        try:
            target = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"

        output_format = OUTPUT_FORMATS.get(target.suffix.lower())
        if output_format is None:
            return f"error: path must end in .png, .jpg, .jpeg, or .webp: {path}"

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
                return bytes(raw[0]), str(raw[1])
            return bytes(raw), FORMAT_MEDIA_TYPES[output_format]
        from core_ai import build_default_registry, default_model_id

        registry = self._registry or build_default_registry()
        model_id = self._model_id
        if model_id is None and self._registry is None:
            model_id = default_model_id(registry)
        return await registry.generate_image(
            prompt, output_format=output_format, model_id=model_id
        )

