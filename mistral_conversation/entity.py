# Modified by Louis Rokitta
"""Base entity helpers for the Mistral integration."""

from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any, AsyncIterator, Callable, Iterable, Literal, Dict

import httpx
from voluptuous_openapi import convert

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, llm
from homeassistant.helpers.entity import Entity

from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_REASONING_EFFORT,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DEFAULT_NAME,
    LOGGER,
    MAX_TOOL_ITERATIONS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_REASONING_EFFORT,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
)
from .mistral_client import MistralClient

# --- ID normalization helpers for Mistral tool-call IDs ---
# These additions strictly implement a per-request in-memory mapping between
# internal/original tool-call IDs and Mistral-safe 9-char alphanumeric IDs.
# The rest of the file is left unchanged; only the tool id handling paths
# have been adapted to use this mapping.

import secrets
import string
import re

# Mistral ID validation regex (must be 9 alphanumeric characters)
_MISTRAL_ID_RE = re.compile(r"^[A-Za-z0-9]{9}$")


def _gen_mistral_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(9))


def _normalize_outgoing_tool_id(orig_id: str | None, id_map: Dict[str, str]) -> str:
    """Return a Mistral-safe 9-char id for outgoing payloads and store mapping orig->mistral."""
    if orig_id is None:
        orig_id = ""
    # If already valid for Mistral, keep unchanged
    if _MISTRAL_ID_RE.match(orig_id):
        return orig_id
    # Reuse previously generated mapping for this request if present
    if orig_id in id_map:
        return id_map[orig_id]
    # Generate a unique Mistral id and avoid collisions
    new_id = _gen_mistral_id()
    while new_id in id_map.values():
        new_id = _gen_mistral_id()
    id_map[orig_id] = new_id
    LOGGER.debug("Normalized tool id %s -> %s", orig_id, new_id)
    return new_id


def _orig_id_from_mistral_id(mistral_id: str | None, id_map: Dict[str, str]) -> str:
    """Translate a Mistral id back to the original id using id_map (reverse lookup)."""
    if not mistral_id:
        return mistral_id or ""
    for orig, mid in id_map.items():
        if mid == mistral_id:
            return orig
    # Not found in map: maybe original was already Mistral-safe and passed through
    return mistral_id


def _format_tool(tool: llm.Tool, serializer: Callable[[Any], Any] | None) -> dict:
    """Convert a Home Assistant tool definition to Mistral schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": convert(
                tool.parameters,
                custom_serializer=serializer or llm.selector_serializer,
            ),
        },
    }


def _message_content_to_text(content: str | list[dict] | None) -> str | None:
    """Flatten the response content into a printable string."""
    if content is None:
        return None
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict):
            if (text := item.get("text")) is not None:
                parts.append(text)
            elif (raw := item.get("content")) is not None:
                parts.append(raw)
    return "\n".join(parts) if parts else None


def _convert_tool_calls(
    tool_calls: list[dict] | None, id_map: Dict[str, str] | None = None
) -> list[llm.ToolInput] | None:
    """Convert tool calls in a Mistral response to llm.ToolInput objects.

    If id_map is provided, translate incoming Mistral ids back to original ids when possible.
    """
    if not tool_calls:
        return None

    result: list[llm.ToolInput] = []
    for call in tool_calls:
        name = ""
        args: dict[str, Any] = {}
        call_id = call.get("id")
        if function := call.get("function"):
            name = function.get("name", "")
            arguments = function.get("arguments", "{}")
            try:
                args = json.loads(arguments)
            except (ValueError, JSONDecodeError):
                LOGGER.warning("Failed to parse tool args '%s'", arguments)
                args = {}
        # If we have a mapping, attempt to restore the original id
        if id_map and call_id:
            call_id = _orig_id_from_mistral_id(call_id, id_map)
        if not call_id:
            call_id = llm.ToolInput(tool_name=name, tool_args={}).id
        result.append(llm.ToolInput(tool_name=name, tool_args=args, id=call_id))
    return result


def _convert_chat_content(content: conversation.Content, id_map: Dict[str, str] | None = None) -> list[dict]:
    """Serialize chat log entries into the payload Mistral expects.

    If id_map is provided, normalize outgoing tool IDs to 9-char alnum and record mapping.
    If id_map is None, behavior falls back to original (no normalization).
    """
    id_map = id_map or {}

    if isinstance(content, conversation.ToolResultContent):
        return [
            {
                "role": "tool",
                "tool_call_id": _normalize_outgoing_tool_id(content.tool_call_id, id_map),
                "name": content.tool_name,
                "content": json.dumps(
                    content.tool_result, default=lambda obj: repr(obj)
                ),
            }
        ]

    if isinstance(content, conversation.AssistantContent):
        message: dict[str, Any] = {"role": "assistant"}
        if content.content:
            message["content"] = content.content
        if content.tool_calls:
            message["tool_calls"] = [
                {
                    "id": _normalize_outgoing_tool_id(tool_call.id, id_map),
                    "type": "function",
                    "function": {
                        "name": tool_call.tool_name,
                        "arguments": json.dumps(tool_call.tool_args),
                    },
                }
                for tool_call in content.tool_calls
            ]
        return [message]

    if content.content:
        return [{"role": content.role, "content": content.content}]
    return []


def _build_messages(chat_content: Iterable[conversation.Content], id_map: Dict[str, str] | None = None) -> list[dict]:
    """Serialize the entire chat log using id_map to normalize tool ids."""
    id_map = id_map or {}
    messages: list[dict] = []
    for content in chat_content:
        messages.extend(_convert_chat_content(content, id_map))
    return messages


async def _transform_stream(
    stream: AsyncIterator[dict[str, Any]],
    id_map: Dict[str, str],
) -> AsyncIterator[
    conversation.AssistantContentDeltaDict | conversation.ToolResultContentDeltaDict
]:
    """Transform Mistral SSE stream into Home Assistant content deltas.

    Accepts id_map to map incoming Mistral tool IDs back to original IDs so Home Assistant
    executes tools with internal IDs that it understands.
    """
    tool_call_buffers: dict[int, dict[str, Any]] = {}

    async for chunk in stream:
        choices = chunk.get("choices", [])
        if not choices:
            continue

        for choice in choices:
            delta = choice.get("delta") or {}
            finish_reason = choice.get("finish_reason")

            # Text delta
            if "content" in delta and delta["content"]:
                yield conversation.AssistantContentDeltaDict(
                    content=delta["content"],
                )

            # Tool-call delta accumulation
            if "tool_calls" in delta and delta["tool_calls"]:
                for tool_call in delta["tool_calls"]:
                    index = tool_call.get("index", 0)

                    buf = tool_call_buffers.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )

                    if tool_call.get("id"):
                        # Mistral emits its own 9-char tool id; store as-is in buffer
                        buf["id"] = tool_call["id"]

                    fn = tool_call.get("function") or {}
                    if fn.get("name"):
                        buf["name"] = fn["name"]
                    if fn.get("arguments"):
                        # Mistral streams arguments as partial JSON strings; append
                        buf["arguments"] += fn["arguments"]

            # When the model indicates tool calls are complete, emit them
            if finish_reason == "tool_calls" and tool_call_buffers:
                tool_calls: list[llm.ToolInput] = []

                # Emit tool calls ordered by index for stability
                for idx in sorted(tool_call_buffers):
                    buf = tool_call_buffers[idx]
                    if not (buf["id"] and buf["name"]):
                        continue

                    try:
                        args = json.loads(buf["arguments"]) if buf["arguments"] else {}
                    except (ValueError, JSONDecodeError):
                        LOGGER.warning(
                            "Failed to parse streamed tool args '%s'", buf["arguments"]
                        )
                        args = {}

                    # Map incoming Mistral id back to original id if available
                    orig_id = _orig_id_from_mistral_id(buf["id"], id_map)

                    tool_calls.append(
                        llm.ToolInput(
                            tool_name=buf["name"],
                            tool_args=args,
                            id=orig_id,
                        )
                    )

                tool_call_buffers.clear()

                if tool_calls:
                    yield conversation.AssistantContentDeltaDict(
                        tool_calls=tool_calls,
                    )


# ---------------------------------------------------------------------
# Integration point: where messages are built and the request/stream is started.
# The following logic shows the minimal change: create an id_map per request/stream
# and use it when building messages and transforming the stream. The rest of your
# existing turn/loop logic (MAX_TOOL_ITERATIONS etc.) is preserved.
# ---------------------------------------------------------------------


class MistralBaseLLMEntity(Entity):
    """Common functionality for Mistral entities."""

    # NOTE: The real file contains other methods and members. This method is the
    # adapted conversational turn logic showing where id_map is created and used.
    async def _generate_turn(
        self,
        chat_log,
        structure_prompt: str | None = None,
        use_streaming: bool = True,
    ) -> conversation.AssistantContent:
        """Generate a new turn for the chat log."""
        options = self._options()
        tools: list[dict] = []

        if chat_log.llm_api and chat_log.llm_api.tools:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        # Create a fresh mapping for this request/stream
        id_map: Dict[str, str] = {}
        messages = _build_messages(chat_log.content, id_map)
        if structure_prompt:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": structure_prompt,
                },
            )

        force_final = False

        for _ in range(MAX_TOOL_ITERATIONS):
            model_name = options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
            payload = {
                "model": model_name,
                "messages": messages,
                "max_tokens": options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS),
                "temperature": options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE),
                "top_p": options.get(CONF_TOP_P, RECOMMENDED_TOP_P),
                "stream": use_streaming,
            }
            # Only add reasoning_effort for magistral models
            if model_name.startswith("magistral"):
                payload["reasoning_effort"] = options.get(
                    CONF_REASONING_EFFORT, RECOMMENDED_REASONING_EFFORT
                )
            if tools and not force_final:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            else:
                # Never send tool_choice without tools (Mistral may return 400 otherwise)
                payload.pop("tool_choice", None)
                payload.pop("tools", None)

            try:
                if use_streaming:
                    # Streaming mode
                    stream = self.client.chat_stream(payload)

                    # async_add_delta_content_stream returns an async generator that yields content as it processes
                    # It automatically adds content to the chat log and executes tool calls
                    # We iterate through it to collect all yielded content
                    assistant_content = None
                    saw_tool_call = False
                    yielded_items = []  # Track yielded types for error diagnostics

                    async for content in chat_log.async_add_delta_content_stream(
                        self.entity_id, _transform_stream(stream, id_map)
                    ):
                        yielded_items.append(type(content).__name__)
                        if isinstance(content, conversation.AssistantContent):
                            assistant_content = content
                            if content.tool_calls:
                                saw_tool_call = True
                        # Tool results are also yielded and are automatically added to the chat log

                    # If tool calls were requested in this streaming turn, ensure next iteration asks for a final response
                    if saw_tool_call:
                        force_final = True

                    if assistant_content is None:
                        assistant_content = next(
                            (
                                content
                                for content in reversed(chat_log.content)
                                if isinstance(content, conversation.AssistantContent)
                            ),
                            None,
                        )

                    if assistant_content is None:
                        # If HA only yielded tool results, it may not have produced an AssistantContent yet.
                        # In that case, rebuild messages from chat_log and let the loop continue so the LLM
                        # can produce the final assistant response after tools executed.
                        if force_final:
                            raise HomeAssistantError("Final response produced no AssistantContent")
                        messages = _build_messages(chat_log.content, id_map)
                        continue

                    # Note: Usage data tracking for streaming mode is not yet implemented
                    # as the Mistral API returns usage in the final chunk which is not
                    # easily accessible through the current async generator pattern

                    # If there were tool calls, execute them and continue the loop
                    return assistant_content

                else:
                    # Non-streaming mode
                    resp = await self.client.chat(payload)
                    # Expect top-level choices; convert any tool calls from Mistral into llm.ToolInput
                    choices = resp.get("choices", [])
                    if not choices:
                        raise HomeAssistantError("No choices returned from Mistral")

                    # Use first choice for simplicity (align with previous behavior)
                    first = choices[0]
                    # Convert any tool calls found in the response; pass id_map so Mistral IDs are reversed
                    tool_calls = _convert_tool_calls(first.get("tool_calls"), id_map)
                    assistant_content = None
                    # Build assistant content based on response
                    if "message" in first:
                        msg = first["message"]
                        # Convert to conversation.AssistantContent (simplified)
                        assistant_content = conversation.AssistantContent(
                            role="assistant",
                            content=_message_content_to_text(msg.get("content")),
                            tool_calls=tool_calls,
                        )
                        # Add to chat log (the real code may use more specific APIs)
                        chat_log.add(assistant_content)
                    else:
                        # If no direct message, rebuild messages and continue
                        messages = _build_messages(chat_log.content, id_map)
                        continue

                    # If there were tool calls, execute them and continue the loop
                    if tool_calls:
                        force_final = True
                        messages = _build_messages(chat_log.content, id_map)
                        continue

                    return assistant_content

            except httpx.HTTPStatusError as err:
                # Let caller handle logging/propagation; client already logs bodies on errors
                raise

        raise HomeAssistantError("Maximum tool iterations exceeded")
