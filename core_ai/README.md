# core-ai

Small Python package for streaming model responses through a shared provider
interface.

Source code lives in `src/core_ai`.

## Layout

- `registry.py` registers providers and routes `provider:model` requests.
- `types.py` defines shared message and stream event models.
- `providers/` contains provider implementations.

## Development

Run tests from this package directory:

```sh
uv run pytest
```
