from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel


Content = Union[str, List[Dict[str, Any]]]


# The unified message format going INTO the provider
class Message(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: Content  # Text or canonical text/image parts
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


# The strict event stream coming OUT of the provider
class StreamEvent(BaseModel):
    type: Literal[
        "text_start",
        "text_delta",
        "reasoning_delta",
        "toolcall_start",
        "toolcall_delta",
        "retry",
        "usage",
        "done",
    ]
    content_index: int = 0
    delta: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    retry_after: Optional[float] = None
    retry_attempt: Optional[int] = None
