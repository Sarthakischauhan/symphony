"""Live OpenAI Responses benchmark: Symphony core_ai vs openai-python, interleaved.

Per round, client order is shuffled and each client runs its whole block back-to-back:
  for each effort: one plain answer, then a 2-step tool loop (tool call -> tool result -> final answer).
The first request of a block follows the other clients' blocks (idle socket); the rest are warm.
A global budget is enforced *before* every request using worst-case cost (prompt estimate + max_output_tokens).
"""
import asyncio
import os
import random
import time

from _common import CONN, install_connection_counters, pct

FALLBACK_PRICES = {"gpt-4o-mini": (0.15, 0.60, 0.075)}  # $/1M in, out, cached-in
ANSWER_PROMPT = "In about 60 words, explain why HTTP keep-alive matters for streaming LLM clients."
TOOL_SYSTEM = "You are a coding agent. Always use the tools to inspect files; never guess file contents. Be brief."
TOOL_PROMPT = "What is the project name in /repo/README.md? Read the file first."
TOOL_RESULT = "# Symphony\n\nSymphony is a fast terminal coding agent with plugins, skills and themes.\n"
TOOLS = [
    {"name": "read_file", "description": "Read a UTF-8 text file from the workspace and return its contents.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Absolute path of the file."},
         "start_line": {"type": "integer", "description": "1-based first line to read."},
         "end_line": {"type": "integer", "description": "1-based last line to read."}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "bash", "description": "Run a shell command in the workspace and return stdout/stderr.",
     "parameters": {"type": "object", "properties": {
         "command": {"type": "string", "description": "The command line to run."},
         "timeout_ms": {"type": "integer", "description": "Kill the command after this many ms."}},
         "required": ["command"], "additionalProperties": False}},
    {"name": "search", "description": "Search file contents with a regular expression.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "path": {"type": "string"}},
         "required": ["pattern"], "additionalProperties": False}},
]
MAX_OUT = 300
EST_IN = {"answer": 40, "tool": 420, "final": 520}


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, usd, price):
        self.usd, self.spent = usd, 0.0
        self.pin, self.pout, self.pcache = price

    def worst(self, est_in):
        return (est_in * self.pin + MAX_OUT * self.pout) / 1e6

    def check(self, *est_ins):
        if self.spent + sum(self.worst(e) for e in est_ins) > self.usd:
            raise BudgetExceeded(f"next request could exceed budget (${self.spent:.4f} spent of ${self.usd})")

    def charge(self, usage, est_in):
        if not usage or usage.get("in") is None:
            cost = self.worst(est_in)
        else:
            cached = usage.get("cached") or 0
            cost = ((usage["in"] - cached) * self.pin + cached * self.pcache + (usage.get("out") or 0) * self.pout) / 1e6
        self.spent += cost
        return cost


def prices_for(model, override):
    if override:
        return override
    from core_ai.models import get_model
    info = get_model("openai", model)
    if info is not None and info.price is not None:
        return (info.price.input, info.price.output, info.price.cache_read or info.price.input)
    if model in FALLBACK_PRICES:
        return FALLBACK_PRICES[model]
    raise SystemExit(f"no price known for {model}; pass --price-in/--price-out so the budget can be enforced")


def model_facts(model):
    from core_ai.models import get_model
    from core_ai.providers.openai import OpenAIProvider
    info = get_model("openai", model)
    facts = {"in_catalog": info is not None, "catalog_api": info.api if info else None,
             "catalog_reasoning": info.reasoning if info else None,
             "symphony_routes_to": "chat_completions" if OpenAIProvider._uses_chat_completions(model) else "responses",
             "symphony_is_reasoning_model": OpenAIProvider._is_reasoning_model(model),
             "symphony_sends_reasoning_param": OpenAIProvider._is_reasoning_model(model)}  # gate in _stream_responses
    return facts


# ---------------- clients ----------------
class Result(dict):
    pass


def _tool_call_struct(call_id, name, args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


class SymphonyClient:
    def __init__(self, key, model):
        from core_ai.providers.openai import OpenAIProvider
        self.p = OpenAIProvider(api_key=key)
        self.model = model

    async def _stream(self, messages, tools, effort):
        from core_ai.types import Message
        msgs = [Message(**m) for m in messages]
        r = Result(first_text=None, first_arg=None, args_done=None, call=None, usage=None, text="")
        call_id = name = None
        args = ""
        async for ev in self.p.stream(self.model, msgs, tools, max_output_tokens=MAX_OUT, reasoning_effort=effort):
            now = time.perf_counter()
            if ev.type == "text_delta" and ev.delta:
                r["first_text"] = r["first_text"] or now
                r["text"] += ev.delta
            elif ev.type == "toolcall_start":
                call_id, name = ev.tool_call_id, ev.tool_name
            elif ev.type == "toolcall_delta" and ev.delta:
                r["first_arg"] = r["first_arg"] or now
                args += ev.delta
            elif ev.type == "toolcall_arguments":
                r["args_done"] = r["args_done"] or now
                args = ev.delta or args
            elif ev.type == "usage":
                r["usage"] = {"in": ev.prompt_tokens, "out": ev.completion_tokens, "reasoning": ev.reasoning_tokens,
                              "cached": ev.cache_read_tokens}
        if name:
            r["call"] = (call_id, name, args)
        return r

    async def answer(self, effort):
        return await self._stream([{"role": "user", "content": ANSWER_PROMPT}], None, effort)

    async def tool_step(self, effort):
        return await self._stream([{"role": "system", "content": TOOL_SYSTEM}, {"role": "user", "content": TOOL_PROMPT}], TOOLS, effort)

    async def final_step(self, effort, call):
        call_id, name, args = call
        return await self._stream([
            {"role": "system", "content": TOOL_SYSTEM}, {"role": "user", "content": TOOL_PROMPT},
            {"role": "assistant", "content": "", "tool_calls": [_tool_call_struct(call_id, name, args)]},
            {"role": "tool", "content": TOOL_RESULT, "tool_call_id": call_id}], TOOLS, effort)


class OpenAISDKClient:
    def __init__(self, key, model, reasoning):
        from openai import AsyncOpenAI
        self.c = AsyncOpenAI(api_key=key)
        self.model = model
        self.reasoning = reasoning

    async def _stream(self, input_items, tools, effort):
        kw = {"model": self.model, "input": input_items, "max_output_tokens": MAX_OUT, "stream": True}
        if self.reasoning and effort:
            kw["reasoning"] = {"effort": effort}
        if tools:
            kw["tools"] = [{"type": "function", **t} for t in tools]
        r = Result(first_text=None, first_arg=None, args_done=None, call=None, usage=None, text="")
        call_id = name = None
        args = ""
        stream = await self.c.responses.create(**kw)
        async for ev in stream:
            now = time.perf_counter()
            if ev.type == "response.output_text.delta" and ev.delta:
                r["first_text"] = r["first_text"] or now
                r["text"] += ev.delta
            elif ev.type == "response.output_item.added" and ev.item.type == "function_call":
                call_id, name = ev.item.call_id, ev.item.name
            elif ev.type == "response.function_call_arguments.delta" and ev.delta:
                r["first_arg"] = r["first_arg"] or now
                args += ev.delta
            elif ev.type == "response.function_call_arguments.done":
                r["args_done"] = r["args_done"] or now
                args = ev.arguments
            elif ev.type in ("response.completed", "response.incomplete"):
                r["incomplete"] = ev.type == "response.incomplete"
                u = ev.response.usage
                r["usage"] = {"in": u.input_tokens, "out": u.output_tokens,
                              "reasoning": u.output_tokens_details.reasoning_tokens if u.output_tokens_details else None,
                              "cached": u.input_tokens_details.cached_tokens if u.input_tokens_details else None}
        if name:
            r["call"] = (call_id, name, args)
        return r

    async def answer(self, effort):
        return await self._stream([{"role": "user", "content": ANSWER_PROMPT}], None, effort)

    async def tool_step(self, effort):
        return await self._stream([{"role": "system", "content": TOOL_SYSTEM}, {"role": "user", "content": TOOL_PROMPT}], TOOLS, effort)

    async def final_step(self, effort, call):
        call_id, name, args = call
        return await self._stream([
            {"role": "system", "content": TOOL_SYSTEM}, {"role": "user", "content": TOOL_PROMPT},
            {"type": "function_call", "call_id": call_id, "name": name, "arguments": args},
            {"type": "function_call_output", "call_id": call_id, "output": TOOL_RESULT}], TOOLS, effort)


# ---------------- runner ----------------
async def _timed(budget, kind, coro_fn):
    budget.check(EST_IN[kind])
    c0 = CONN["n"]
    s = time.perf_counter()
    try:
        r = await coro_fn()
        err = None
    except BudgetExceeded:
        raise
    except Exception as exc:  # recorded, not fatal
        r, err = Result(usage=None), f"{type(exc).__name__}: {str(exc)[:300]}"
    e = time.perf_counter()
    row = {"kind": kind, "total_ms": (e - s) * 1e3, "new_conns": CONN["n"] - c0, "error": err}
    if err is None:
        u = r["usage"] or {}
        row.update(usage=u,
                   ttft_ms=(r["first_text"] - s) * 1e3 if r["first_text"] else None,
                   first_arg_ms=(r["first_arg"] - s) * 1e3 if r["first_arg"] else None,
                   args_done_ms=(r["args_done"] - s) * 1e3 if r["args_done"] else None,
                   tool_called=r["call"][1] if r["call"] else None,
                   # Symphony yields no usage/stop signal on response.incomplete (openai.py:303), so missing usage == incomplete
                   incomplete=r.get("incomplete", not r["usage"]),
                   text_chars=len(r["text"]))
        visible = (u.get("out") or 0) - (u.get("reasoning") or 0)
        if r["first_text"] and e > r["first_text"] and visible > 0:
            row["visible_tok_per_s"] = visible / (e - r["first_text"])
    row["cost_usd"] = budget.charge(row.get("usage"), EST_IN[kind])
    return row, (r if err is None else None)


async def run_model(key, model, efforts, rounds, budget, seed=1):
    facts = model_facts(model)
    reasoning = bool(facts["catalog_reasoning"]) or model.startswith(("gpt-5", "gpt-6", "o"))
    efforts = efforts if reasoning else [None]
    clients = {"symphony": SymphonyClient(key, model),
               "openai-sdk": OpenAISDKClient(key, model, reasoning)}
    rows, stopped = [], None
    rng = random.Random(seed)
    try:
        for rnd in range(rounds):
            order = list(clients)
            rng.shuffle(order)
            for name in order:
                c = clients[name]
                pos = 0
                for eff in efforts:
                    for kind in ("answer", "loop"):
                        base = {"model": model, "client": name, "round": rnd, "effort": eff or "n/a", "block_pos": pos}
                        if kind == "answer":
                            row, _ = await _timed(budget, "answer", lambda: c.answer(eff))
                            rows.append({**base, **row})
                            pos += 1
                            continue
                        budget.check(EST_IN["tool"], EST_IN["final"])  # whole loop must fit
                        s = time.perf_counter()
                        row1, r1 = await _timed(budget, "tool", lambda: c.tool_step(eff))
                        rows.append({**base, **row1})
                        pos += 1
                        if r1 is None or r1["call"] is None:
                            continue
                        row2, _ = await _timed(budget, "final", lambda: c.final_step(eff, r1["call"]))
                        row2["loop_e2e_ms"] = (time.perf_counter() - s) * 1e3
                        rows.append({**base, "block_pos": pos, **row2})
                        pos += 1
            print(f"  [{model}] round {rnd + 1}/{rounds} done, spent ${budget.spent:.4f}", flush=True)
    except BudgetExceeded as exc:
        stopped = str(exc)
        print(f"  [{model}] HARD STOP: {stopped}", flush=True)
    return {"model": model, "facts": facts, "efforts": [e or "n/a" for e in efforts], "rows": rows,
            "stopped": stopped, "summary": summarize(rows)}


def summarize(rows):
    out = {}
    keyset = sorted({(r["client"], r["effort"]) for r in rows})
    for client, eff in keyset:
        rs = [r for r in rows if r["client"] == client and r["effort"] == eff]
        ok = [r for r in rs if not r["error"]]
        ans = [r for r in ok if r["kind"] == "answer"]
        tool = [r for r in ok if r["kind"] == "tool"]
        fin = [r for r in ok if r["kind"] == "final"]

        def p(rows_, key, q):
            return pct([r.get(key) for r in rows_], q)
        out[f"{client}|{eff}"] = {
            "client": client, "effort": eff, "n_requests": len(rs), "errors": len(rs) - len(ok),
            "error_samples": sorted({r["error"] for r in rs if r["error"]})[:3],
            "answer_ttft_p50": p(ans, "ttft_ms", 50), "answer_ttft_p95": p(ans, "ttft_ms", 95),
            "answer_total_p50": p(ans, "total_ms", 50), "answer_total_p95": p(ans, "total_ms", 95),
            "answer_visible_tok_s_p50": p(ans, "visible_tok_per_s", 50),
            "answer_reasoning_tokens_p50": pct([(r["usage"] or {}).get("reasoning") for r in ans], 50),
            "tool_first_arg_p50": p(tool, "first_arg_ms", 50), "tool_first_arg_p95": p(tool, "first_arg_ms", 95),
            "tool_args_done_p50": p(tool, "args_done_ms", 50), "tool_args_done_p95": p(tool, "args_done_ms", 95),
            "tool_called_rate": (sum(1 for r in tool if r["tool_called"]) / len(tool)) if tool else None,
            "loop_e2e_p50": p(fin, "loop_e2e_ms", 50), "loop_e2e_p95": p(fin, "loop_e2e_ms", 95),
            "final_ttft_p50": p(fin, "ttft_ms", 50),
            "incomplete": sum(1 for r in ok if r.get("incomplete")),
            "empty_answers": sum(1 for r in ans if not r.get("text_chars")),
            "warm_new_conns": sum(r["new_conns"] for r in ok if r["block_pos"] > 0),
            "warm_requests": sum(1 for r in ok if r["block_pos"] > 0),
            "cost_usd": sum(r["cost_usd"] for r in rs),
        }
    return out


def run(models, budget_usd, rounds, efforts, price_override=None):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY is not set: skipping live benchmark.")
        return {"skipped": True, "reason": "OPENAI_API_KEY not set"}
    install_connection_counters()
    results = {"skipped": False, "budget_usd": budget_usd, "models": []}
    budget = None
    for model in models:
        price = prices_for(model, price_override)
        if budget is None:
            budget = Budget(budget_usd, price)
        else:  # one global budget across models; switch the price table
            budget.pin, budget.pout, budget.pcache = price
        print(f"live: {model} prices $/1M in={price[0]} out={price[1]} cached={price[2]}", flush=True)
        res = asyncio.run(run_model(key, model, efforts, rounds, budget))
        res["price_per_1m"] = price
        results["models"].append(res)
        if res["stopped"]:
            break
    results["spent_usd"] = budget.spent if budget else 0.0
    return results
