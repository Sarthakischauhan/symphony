from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel


# The unified message format going INTO the provider
class Message(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: Union[str, List[Dict[str, Any]]]  # Handles text or image/tool payloads
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


# The strict event stream coming OUT of the provider
class StreamEvent(BaseModel):
    type: Literal[
        "text_start", "text_delta", "toolcall_start", "toolcall_delta", "done"
    ]
    content_index: int
    delta: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
