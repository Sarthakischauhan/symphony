---
name: pick-model
description: Choose the cheapest model that can do the task. Use before a long run, a subagent, or when the user asks which model to use.
---

# Pick a model

Stay on the current provider. Name one model and why. Do not switch it yourself; tell the user the `/model` id.

Use the small model for lookup, a local edit, a test, a summary, or a subagent:

- openai: `openai:gpt-5.4-mini`
- gemini: `gemini:gemini-3.1-flash-lite`
- anthropic: `anthropic:claude-haiku-5-5`
- grok: `grok:grok-4.6`

Use the larger model only when the task needs it: a design choice, a bug that has already survived one attempt, or a change across several modules.

- openai: `openai:gpt-5.6-sol`
- gemini: `gemini:gemini-3.1-pro-preview`
- anthropic: `anthropic:claude-sonnet-5`
- grok: `grok:grok-4.7`

A subagent never needs the larger model. Leave its `model_id` empty so it runs on the cheap sibling. Do not pick a `pro` model for either.
