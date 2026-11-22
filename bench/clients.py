"""Mock-mode client adapters. make(name, base) -> async run() -> (first_text_time, n_events)."""
import importlib
import time

SYSTEM = ("You are a coding agent. " * 300)[:6000]
HISTORY = [("user", "Refactor module.py to use dataclasses."), ("assistant", "I'll read the file first."),
           ("user", "Also keep the public API stable."), ("assistant", "Understood, editing now."),
           ("user", "Go ahead.")]
TOOLS = [{"name": f"tool_{i}", "description": "Does a thing in the workspace. " * 4,
          "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"},
                         "line": {"type": "integer"}}, "required": ["path"]}} for i in range(15)]

MOCK_CLIENTS = ["symphony-openai", "openai-sdk", "litellm-openai",
                "symphony-anthropic", "anthropic-sdk", "litellm-anthropic",
                "symphony-gemini", "google-genai"]


def oa_messages():
    return [{"role": "system", "content": SYSTEM}] + [{"role": r, "content": c} for r, c in HISTORY]


def oa_tools():
    return [{"type": "function", "function": t} for t in TOOLS]


def symphony(kind, base):
    from core_ai.types import Message
    msgs = [Message(role="system", content=SYSTEM)] + [Message(role=r, content=c) for r, c in HISTORY]
    if kind == "openai":
        p = importlib.import_module("core_ai.providers.openai").OpenAIProvider(api_key="sk-test", base_url=base + "/v1")
        model = "o4-mini"  # catalog api=chat_completions -> exercises /chat/completions + [DONE]
    elif kind == "anthropic":
        p = importlib.import_module("core_ai.providers.anthropic").AnthropicProvider(api_key="sk-ant-test", base_url=base)
        model = "claude-sonnet-4-5"
    else:
        p = importlib.import_module("core_ai.providers.gemini").GeminiProvider(api_key="g-test", base_url=base + "/v1beta")
        model = "gemini-3.8-flash"

    async def run():
        first = None
        n = 0
        async for ev in p.stream(model, msgs, TOOLS):
            if first is None and ev.type == "text_delta":
                first = time.perf_counter()
            n += 1
        return first, n
    return run


def openai_sdk(base):
    from openai import AsyncOpenAI
    c = AsyncOpenAI(api_key="sk-test", base_url=base + "/v1")

    async def run():
        first = None
        n = 0
        s = await c.chat.completions.create(model="o4-mini", messages=oa_messages(), tools=oa_tools(), stream=True,
                                            stream_options={"include_usage": True})
        async for ch in s:
            if first is None and ch.choices and ch.choices[0].delta.content:
                first = time.perf_counter()
            n += 1
        return first, n
    return run


def anthropic_sdk(base):
    from anthropic import AsyncAnthropic
    c = AsyncAnthropic(api_key="sk-ant-test", base_url=base)
    tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in TOOLS]

    async def run():
        first = None
        n = 0
        s = await c.messages.create(model="claude-sonnet-4-5", max_tokens=8192, system=SYSTEM, tools=tools,
                                    messages=[{"role": r, "content": c_} for r, c_ in HISTORY], stream=True)
        async for ev in s:
            if first is None and ev.type == "content_block_delta" and ev.delta.type == "text_delta":
                first = time.perf_counter()
            n += 1
        return first, n
    return run


def genai_sdk(base):
    from google import genai
    from google.genai import types
    c = genai.Client(api_key="g-test", http_options=types.HttpOptions(base_url=base + "/", api_version="v1beta"))
    cfg = types.GenerateContentConfig(system_instruction=SYSTEM, tools=[types.Tool(function_declarations=[
        types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"])
        for t in TOOLS])])
    contents = [types.Content(role="user" if r == "user" else "model", parts=[types.Part(text=c_)]) for r, c_ in HISTORY]

    async def run():
        first = None
        n = 0
        async for ch in await c.aio.models.generate_content_stream(model="gemini-3.8-flash", contents=contents, config=cfg):
            if first is None and ch.candidates and ch.candidates[0].content.parts[0].text:
                first = time.perf_counter()
            n += 1
        return first, n
    return run


def litellm_client(kind, base):
    import litellm
    if kind == "openai":
        model, kw = "openai/o4-mini", dict(api_base=base + "/v1", api_key="sk-test")
    else:
        model, kw = "anthropic/claude-sonnet-4-5", dict(api_base=base, api_key="sk-ant-test")

    async def run():
        first = None
        n = 0
        s = await litellm.acompletion(model=model, messages=oa_messages(), tools=oa_tools(), stream=True, **kw)
        async for ch in s:
            if first is None and ch.choices and ch.choices[0].delta.content:
                first = time.perf_counter()
            n += 1
        return first, n
    return run


def make(name, base):
    if name.startswith("symphony-"):
        return symphony(name.split("-")[1], base)
    if name == "openai-sdk":
        return openai_sdk(base)
    if name == "anthropic-sdk":
        return anthropic_sdk(base)
    if name == "google-genai":
        return genai_sdk(base)
    if name.startswith("litellm-"):
        return litellm_client(name.split("-")[1], base)
    raise SystemExit(f"unknown client {name}")


IMPORTS = {
    "symphony": "import core_ai",
    "openai-sdk": "import openai",
    "anthropic-sdk": "import anthropic",
    "google-genai": "from google import genai",
    "litellm": "import litellm",
}
