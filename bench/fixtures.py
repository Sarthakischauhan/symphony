"""Deterministic 'recorded-style' streams: ~2000 text tokens + 1 tool call (~150 arg chunks) + usage."""
import json
import random

random.seed(7)
WORDS = ("the provider layer streams server sent events and each delta carries a small "
         "fragment of text so the client must parse thousands of tiny json frames per "
         "response while keeping latency low for the terminal user interface").split()
N_TEXT = 2000
TEXT = [(" " if i else "") + WORDS[i % len(WORDS)] for i in range(N_TEXT)]
ARGS = json.dumps({"path": "/repo/src/module.py", "old_string": "x = 1\n" * 40, "new_string": "x = 2\n" * 40})
ARG_CHUNKS = [ARGS[i:i + 4] for i in range(0, len(ARGS), 4)][:150]
ARG_CHUNKS[-1] += ARGS[len("".join(ARG_CHUNKS)):]
TOKENS = N_TEXT + len(ARG_CHUNKS)

def sse(obj, event=None):
    head = f"event: {event}\n" if event else ""
    return (head + "data: " + json.dumps(obj, separators=(",", ":")) + "\n\n").encode()

def openai_chat():
    base = {"id": "chatcmpl-AbC123xyz", "object": "chat.completion.chunk", "created": 1763050000,
            "model": "gpt-4.1-mini-2025-04-14", "service_tier": "default", "system_fingerprint": "fp_6f2eabb9a5"}
    out = [sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "", "refusal": None}, "logprobs": None, "finish_reason": None}], "usage": None})]
    for t in TEXT:
        out.append(sse({**base, "choices": [{"index": 0, "delta": {"content": t}, "logprobs": None, "finish_reason": None}], "usage": None}))
    out.append(sse({**base, "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_Qz81", "type": "function", "function": {"name": "edit_file", "arguments": ""}}]}, "logprobs": None, "finish_reason": None}], "usage": None}))
    for a in ARG_CHUNKS:
        out.append(sse({**base, "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": a}}]}, "logprobs": None, "finish_reason": None}], "usage": None}))
    out.append(sse({**base, "choices": [{"index": 0, "delta": {}, "logprobs": None, "finish_reason": "tool_calls"}], "usage": None}))
    out.append(sse({**base, "choices": [], "usage": {"prompt_tokens": 1200, "completion_tokens": TOKENS, "total_tokens": 1200 + TOKENS,
            "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}}}))
    out.append(b"data: [DONE]\n\n")
    return out

def anthropic():
    out = [sse({"type": "message_start", "message": {"id": "msg_01XyZ", "type": "message", "role": "assistant", "model": "claude-sonnet-4-5", "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 1200, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1}}}, "message_start"),
           sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}, "content_block_start"),
           sse({"type": "ping"}, "ping")]
    for t in TEXT:
        out.append(sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}}, "content_block_delta"))
    out.append(sse({"type": "content_block_stop", "index": 0}, "content_block_stop"))
    out.append(sse({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_01A", "name": "edit_file", "input": {}}}, "content_block_start"))
    for a in ARG_CHUNKS:
        out.append(sse({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": a}}, "content_block_delta"))
    out.append(sse({"type": "content_block_stop", "index": 1}, "content_block_stop"))
    out.append(sse({"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": TOKENS}}, "message_delta"))
    out.append(sse({"type": "message_stop"}, "message_stop"))
    return out

def gemini():
    out = []
    meta = {"promptTokenCount": 1200, "totalTokenCount": 1200}
    for t in TEXT:
        out.append(sse({"candidates": [{"content": {"parts": [{"text": t}], "role": "model"}, "index": 0}], "usageMetadata": meta, "modelVersion": "gemini-3.8-flash", "responseId": "r1"}))
    out.append(sse({"candidates": [{"content": {"parts": [{"functionCall": {"name": "edit_file", "args": json.loads(ARGS)}}], "role": "model"}, "finishReason": "STOP", "index": 0}],
                    "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": TOKENS, "totalTokenCount": 1200 + TOKENS}, "modelVersion": "gemini-3.8-flash", "responseId": "r1"}))
    return out

STREAMS = {"openai": openai_chat(), "anthropic": anthropic(), "gemini": gemini()}
if __name__ == "__main__":
    for k, v in STREAMS.items():
        print(k, len(v), "frames", sum(map(len, v)), "bytes", "tokens", TOKENS)
