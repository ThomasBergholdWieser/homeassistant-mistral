"""Base entity helpers for the Mistral integration."""

from __future__ import annotations

import json
import secrets
import string
import re
from typing import Any, AsyncIterator, Callable, Iterable, Dict

from voluptuous_openapi import convert

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, llm
from homeassistant.helpers.entity import Entity

from .const import (
    CONF_CHAT_MODEL,
    DEFAULT_NAME,
    LOGGER,
    MAX_TOOL_ITERATIONS,
    RECOMMENDED_CHAT_MODEL,
    CONF_DEFAULT_MEDIA_PLAYER,
    DEFAULT_VOICE_BOX,
    CONF_MUSIC_ASSISTANT_CONFIG_ENTRY,  
    DEFAULT_MUSIC_ASSISTANT_CONFIG_ENTRY, 
)
from .mistral_client import MistralClient

_MISTRAL_ID_RE = re.compile(r"^[A-Za-z0-9]{9}$")

def _gen_mistral_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(9))

def _normalize_outgoing_tool_id(orig_id: str | None, id_map: Dict[str, str]) -> str:
    if orig_id is None: orig_id = ""
    if _MISTRAL_ID_RE.match(orig_id): return orig_id
    if orig_id in id_map: return id_map[orig_id]
    new_id = _gen_mistral_id()
    while new_id in id_map.values(): new_id = _gen_mistral_id()
    id_map[orig_id] = new_id
    return new_id

def _format_tool(tool: llm.Tool, serializer: Callable[[Any], Any] | None) -> dict:
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

def _convert_chat_content(content: conversation.Content, id_map: Dict[str, str]) -> list[dict]:
    if isinstance(content, conversation.ToolResultContent):
        return [{
            "role": "tool",
            "tool_call_id": _normalize_outgoing_tool_id(content.tool_call_id, id_map),
            "name": content.tool_name,
            "content": json.dumps(content.tool_result),
        }]
    if isinstance(content, conversation.AssistantContent):
        msg: dict[str, Any] = {"role": "assistant"}
        if content.content: msg["content"] = content.content
        if content.tool_calls:
            msg["tool_calls"] = [{
                "id": _normalize_outgoing_tool_id(tc.id, id_map),
                "type": "function",
                "function": {"name": tc.tool_name, "arguments": json.dumps(tc.tool_args)},
            } for tc in content.tool_calls]
        return [msg]
    return [{"role": content.role, "content": content.content}] if content.content else []

def _build_messages(chat_content: Iterable[conversation.Content], id_map: Dict[str, str]) -> list[dict]:
    messages: list[dict] = []
    for content in chat_content:
        messages.extend(_convert_chat_content(content, id_map))
    return messages

async def _transform_stream(
    stream: AsyncIterator[dict[str, Any]],
    id_map: Dict[str, str],
) -> AsyncIterator[conversation.AssistantContentDeltaDict]:
    tool_call_buffers: dict[int, dict[str, Any]] = {}
    async for chunk in stream:
        for choice in chunk.get("choices", []):
            delta = choice.get("delta") or {}
            if "content" in delta and delta["content"]:
                yield conversation.AssistantContentDeltaDict(content=delta["content"])
            if "tool_calls" in delta:
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    buf = tool_call_buffers.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"): buf["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"): buf["name"] = fn["name"]
                    if fn.get("arguments"): buf["arguments"] += fn["arguments"]
            if choice.get("finish_reason") == "tool_calls":
                inputs = []
                for idx in sorted(tool_call_buffers):
                    buf = tool_call_buffers[idx]
                    try: args = json.loads(buf["arguments"])
                    except: args = {}
                    int_id = next((k for k, v in id_map.items() if v == buf["id"]), secrets.token_hex(8))
                    id_map[int_id] = buf["id"]
                    inputs.append(llm.ToolInput(tool_name=buf["name"], tool_args=args, id=int_id))
                tool_call_buffers.clear()
                yield conversation.AssistantContentDeltaDict(tool_calls=inputs)

class MistralBaseLLMEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(entry.domain, subentry.subentry_id)},
            name=entry.title or DEFAULT_NAME,
            manufacturer="Mistral AI",
            model=subentry.data.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL),
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    def _get_music_assistant_config_entry_id(self, hass: HomeAssistant) -> str | None:
        """Get the config_entry_id for Music Assistant integration."""
        # Einfach direkt nutzen - kein extra import nötig!
        return self._options().get(
            CONF_MUSIC_ASSISTANT_CONFIG_ENTRY, 
            DEFAULT_MUSIC_ASSISTANT_CONFIG_ENTRY
        )

    @property
    def client(self) -> MistralClient:
        return self.entry.runtime_data

    def _options(self):
        return self.subentry.data or {}

    async def _add_assistant_content(self, chat_log: conversation.ChatLog, content: conversation.AssistantContent):
        """Add assistant content to chat log."""
        chat_log.content.append(content)
    
    async def _add_tool_content(self, chat_log: conversation.ChatLog, content: conversation.ToolResultContent):
        """Add tool result content to chat log."""
        chat_log.content.append(content)

    async def _async_handle_chat_log(
        self,
        hass: HomeAssistant,
        chat_log: conversation.ChatLog,
        structure_prompt: str | None = None,
        use_streaming: bool = True,
    ) -> conversation.AssistantContent:
        """Handle chat log and process tool calls."""
        options = self._options()
        id_map: Dict[str, str] = {}
        
        VOICE_BOX = options.get(CONF_DEFAULT_MEDIA_PLAYER, DEFAULT_VOICE_BOX)
        CURRENT_MODEL = options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
    
        state = hass.states.get(VOICE_BOX)
        friendly_name = state.name if state else "dem Standard-Lautsprecher"
    
        instruction = (
            f" Deine Standard-Ausgabe für Musik ist {friendly_name} ({VOICE_BOX}). "
            " Nutze für Musik-Befehle immer diesen Player."
        )
    
        for iteration in range(MAX_TOOL_ITERATIONS):
            messages = _build_messages(chat_log.content, id_map)
            full_system_prompt = (structure_prompt + instruction) if structure_prompt else instruction
            messages.insert(0, {"role": "system", "content": full_system_prompt})
    
            # Build tools list
            tools = []
            if chat_log.llm_api and chat_log.llm_api.tools:
                tools = [_format_tool(t, chat_log.llm_api.custom_serializer) for t in chat_log.llm_api.tools]
            
            # Add Music Assistant tools (only if not already present)
            music_tool_names = {"music_assistant.search", "music_assistant.play_media"}
            existing_tool_names = {t.name for t in (chat_log.llm_api.tools if chat_log.llm_api else [])}
            
            if not music_tool_names.intersection(existing_tool_names):
                tools.extend([
                    {
                        "type": "function",
                        "function": {
                            "name": "music_assistant.search",
                            "description": "Suche nach Musik.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "Suchbegriff"},
                                    "limit": {"type": "integer", "default": 1}
                                },
                                "required": ["name"]
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "music_assistant.play_media",
                            "description": "Spielt Musik ab.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "entity_id": {"type": "string", "description": "Player ID"},
                                    "media_id": {"type": "string", "description": "Media ID"},
                                    "media_type": {"type": "string", "description": "track/album"}
                                },
                                "required": ["media_id", "media_type"]
                            }
                        }
                    }
                ])
    
            # Prepare API payload
            payload = {
                "model": CURRENT_MODEL,
                "messages": messages,
                "tools": tools,
                "stream": use_streaming,
            }
    
            # Get response from Mistral
            assistant_content = None
            if use_streaming:
                stream = self.client.chat_stream(payload)
                content_text = ""
                tool_calls = []
                async for delta in _transform_stream(stream, id_map):
                    if delta.get("content"): 
                        content_text += delta["content"]
                    if delta.get("tool_calls"): 
                        tool_calls.extend(delta["tool_calls"])
                
                assistant_content = conversation.AssistantContent(
                    content=content_text, 
                    tool_calls=tool_calls, 
                    agent_id=self.unique_id
                )
            else:
                response = await self.client.chat(payload)
                msg = response.get("choices", [{}])[0].get("message", {})
                tcs = []
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        try: 
                            args = json.loads(tc["function"]["arguments"])
                        except (json.JSONDecodeError, KeyError, TypeError) as e:
                            LOGGER.warning(f"Failed to parse tool arguments: {e}")
                            args = {}
                        tcs.append(llm.ToolInput(
                            tool_name=tc["function"]["name"], 
                            tool_args=args, 
                            id=tc["id"]
                        ))
                assistant_content = conversation.AssistantContent(
                    content=msg.get("content"), 
                    tool_calls=tcs, 
                    agent_id=self.unique_id
                )
    
            if not assistant_content: 
                break
    
            # No tool calls → Return response directly
            if not assistant_content.tool_calls:
                await self._add_assistant_content(chat_log, assistant_content)
                return assistant_content
    
            # ============================================================
            # Separate Music Assistant tools from standard tools
            # ============================================================
            
            music_tools = []
            standard_tools = []
            
            for tool in assistant_content.tool_calls:
                if tool.tool_name.startswith("music_assistant"):
                    music_tools.append(tool)
                else:
                    standard_tools.append(tool)
            
            # ============================================================
            # Process Music Assistant tools
            # ============================================================
            
            if music_tools:
                # Add assistant content with ONLY music tools
                await self._add_assistant_content(chat_log, conversation.AssistantContent(
                    content=assistant_content.content,
                    tool_calls=music_tools,
                    agent_id=self.unique_id
                ))
                
                # Get Music Assistant config_entry_id
                ma_config_entry_id = self._get_music_assistant_config_entry_id(hass)
                
                # Execute each music tool individually
                for tool in music_tools:
                    try:
                        service = tool.tool_name.split(".")[1]
                        args = dict(tool.tool_args)
                        eid = args.pop("entity_id", VOICE_BOX)
                        
                        # Add config_entry_id ONLY if we have it and service needs it
                        if ma_config_entry_id and service in ["search", "get_library"]:
                            args["config_entry_id"] = ma_config_entry_id
                        
                        # Filter arguments based on service
                        if service == "play_media":
                            args = {k: v for k, v in args.items() if k in ["media_id", "media_type"]}
                        elif service == "search":
                            allowed = ["name", "limit", "media_type", "artist"]
                            if ma_config_entry_id:
                                allowed.append("config_entry_id")
                            args = {k: v for k, v in args.items() if k in allowed}
                        elif service == "get_library":
                            allowed = ["media_type", "limit", "offset", "order_by"]
                            if ma_config_entry_id:
                                allowed.append("config_entry_id")
                            args = {k: v for k, v in args.items() if k in allowed}
                        
                        # Call the service - play_media doesn't return response!
                        if service == "play_media":
                            await hass.services.async_call(
                                "music_assistant", 
                                service, 
                                args,
                                target={"entity_id": eid},
                                blocking=True
                            )
                            res = {"status": "success", "message": "Playback started"}
                        else:
                            res = await hass.services.async_call(
                                "music_assistant", 
                                service, 
                                args,
                                blocking=True, 
                                return_response=True
                            )

                        # Add tool result to chat log
                        await self._add_tool_content(chat_log, conversation.ToolResultContent(
                            tool_call_id=tool.id, 
                            tool_name=tool.tool_name, 
                            tool_result=res or {"status": "success"},
                            agent_id=self.unique_id
                        ))
                        
                    except Exception as e:
                        LOGGER.error(f"Music Assistant tool '{tool.tool_name}' failed: {e}")
                        await self._add_tool_content(chat_log, conversation.ToolResultContent(
                            tool_call_id=tool.id, 
                            tool_name=tool.tool_name, 
                            tool_result={"error": str(e)},
                            agent_id=self.unique_id
                        ))
            
            # ============================================================
            # Process standard Home Assistant tools
            # ============================================================
            
            if standard_tools:
                # Add assistant content with standard tools
                await self._add_assistant_content(chat_log, conversation.AssistantContent(
                    content=assistant_content.content if not music_tools else "",
                    tool_calls=standard_tools,
                    agent_id=self.unique_id
                ))
                
                # Execute standard tools via llm_api
                if chat_log.llm_api and hasattr(chat_log.llm_api, 'async_call_tool'):
                    for tool in standard_tools:
                        try:
                            result = await chat_log.llm_api.async_call_tool(tool)
                            await self._add_tool_content(chat_log, conversation.ToolResultContent(
                                tool_call_id=tool.id,
                                tool_name=tool.tool_name,
                                tool_result=result,
                                agent_id=self.unique_id
                            ))
                        except Exception as e:
                            LOGGER.error(f"Standard tool '{tool.tool_name}' failed: {e}")
                            await self._add_tool_content(chat_log, conversation.ToolResultContent(
                                tool_call_id=tool.id,
                                tool_name=tool.tool_name,
                                tool_result={"error": str(e)},
                                agent_id=self.unique_id
                            ))
                    
                    # Nach Ausführung: continue für nächste Iteration
                    continue
                else:
                    # Kein llm_api? Dann return
                    return assistant_content
            
            # ============================================================
            # Continue loop if we processed music tools
            # ============================================================
            
            if music_tools:
                continue
            
            # No tools were processed
            await self._add_assistant_content(chat_log, assistant_content)
            return assistant_content
    
        # ============================================================
        # Max iterations reached - return gracefully
        # ============================================================
        
        LOGGER.warning(f"Max tool iterations ({MAX_TOOL_ITERATIONS}) reached")
        
        # Return last assistant content if available
        if assistant_content:
            return assistant_content
        
        # Fallback: Return error message
        return conversation.AssistantContent(
            content="Entschuldigung, ich konnte die Anfrage nicht vollständig verarbeiten.",
            tool_calls=[],
            agent_id=self.unique_id
        )
