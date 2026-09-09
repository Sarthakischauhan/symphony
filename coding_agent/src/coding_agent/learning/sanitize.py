"""Sanitize and redact content before learning persistence / prompt injection."""

from __future__ import annotations

import re

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|passwd|password)\s*[:=]\s*['\"]?([^\s'\"]+)"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)(\S+)"),
    re.compile(r"(?i)(sk-[a-z0-9]{10,})"),
    re.compile(r"(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----)(.*?)(-----END [A-Z ]*PRIVATE KEY-----)", re.S),
]

_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all )?(previous|prior) instructions"),
    re.compile(r"(?i)system\s*prompt"),
    re.compile(r"(?i)you are now"),
    re.compile(r"(?i)<\s*/?\s*system\s*>"),
]


def redact_secrets(text: str) -> str:
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(_redact_match, out)
    return out


def neutralize_injection(text: str) -> str:
    """Neutralize common prompt-injection phrases in stored/injected text."""
    out = text
    for pattern in _INJECTION_PATTERNS:
        out = pattern.sub("[filtered-instruction]", out)
    # Neutralize markdown/system-role spoofing
    out = out.replace("```", "` ` `")
    return out


def sanitize_text(text: str, *, max_chars: int = 400) -> str:
    cleaned = neutralize_injection(redact_secrets(text))
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def sanitize_task(task: str) -> str:
    return sanitize_text(task, max_chars=240)


def sanitize_memory(text: str, *, max_chars: int = 1400) -> str:
    """Sanitize memory at injection time while preserving Markdown line breaks."""
    cleaned = neutralize_injection(redact_secrets(str(text or "")))
    lines = [" ".join(line.split()) for line in cleaned.splitlines()]
    cleaned = "\n".join(lines).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def _redact_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 2:
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"
