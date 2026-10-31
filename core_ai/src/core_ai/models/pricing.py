"""Session cost from the catalog price, in the shape OpenCode shows.

OpenCode stores one cost on each assistant message and sums them. The rate
is USD per million tokens: uncached input, output, and cache read and write
when the provider reports them. A model with no price costs nothing here.
"""

from __future__ import annotations

from core_ai.models.registry import get_model
from core_ai.models.types import ModelPrice

MILLION = 1_000_000


def model_price(model_id: str) -> ModelPrice | None:
    """The catalog price for ``provider:model`` or a bare model id."""
    provider, _, name = model_id.partition(":")
    if not name:
        return None
    model = get_model(provider, name)
    return model.price if model is not None else None


def turn_cost(
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> float:
    """USD for one response. Cache reads are not billed again as input.

    Gemini bills ``thoughtsTokenCount`` on top of ``candidatesTokenCount``,
    both at the output rate. Other providers already fold reasoning into
    ``output_tokens``; they pass ``reasoning_tokens=0`` here.
    """
    price = model_price(model_id)
    if price is None:
        return 0.0
    cached = max(cache_read_tokens, 0)
    fresh = max(input_tokens - cached, 0)
    read_rate = price.input if price.cache_read is None else price.cache_read
    write_rate = price.input if price.cache_write is None else price.cache_write
    return (
        fresh * price.input
        + max(output_tokens, 0) * price.output
        + max(reasoning_tokens, 0) * price.output
        + cached * read_rate
        + max(cache_write_tokens, 0) * write_rate
    ) / MILLION


def format_cost(amount: float) -> str:
    """``$0.04`` above a cent, ``$0.0042`` below, ``$0.00`` at zero."""
    if amount <= 0:
        return "$0.00"
    if amount >= 0.01:
        return f"${amount:,.2f}"
    return f"${amount:.4f}"


__all__ = ["format_cost", "model_price", "turn_cost"]
