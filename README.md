 Mistral AI for Home Assistant

This custom integration brings Mistral AI chat capabilities into Home Assistant, replacing the OpenAI conversation backend with the Mistral Chat API. It provides a Conversation agent (voice/chat) and AI Task entities (structured JSON output), streaming responses, tool-call passthrough, token tracking, and advanced configuration options.

---

## Highlights / Features

- Uses the Mistral Chat API for replies and tool/function calls.
- Streaming responses (SSE) for faster, lower-latency conversation streaming.
- Works with Home Assistant Conversation (voice, chat, automations).
- AI Task support: request structured JSON output that can be used in automations.
- Tool-call passthrough: Home Assistant LLM tools (and custom tools) are forwarded to Mistral as functions.
- Music integration helpers: default media player selection and automatic Music Assistant tool inclusion when needed.
- UI-configurable model selection (with recommended defaults) and advanced settings for `max_tokens`, `temperature`, `top_p`, and `reasoning_effort`.
- API key validation during setup (invalid credentials produce an auth error).
- Granular error handling (auth failures, rate limits, timeouts).
- Token usage tracking and dynamic model display in device info.
- Provides a synchronous service for one-off prompts and optional file injection.
- No image generation — the Mistral API currently does not provide an image generation endpoint.

---

## Quick Links

- Repository: https://github.com/ThomasBergholdWieser/homeassistant-mistral
- Mistral API docs: https://docs.mistral.ai/api/
- Home Assistant developer docs: https://developers.home-assistant.io/

---

## Requirements

- Home Assistant (tested from 2025.12)
- A Mistral API key (create/get one on the Mistral console)
- Internet access from your Home Assistant instance
- The integration's runtime dependency: httpx (declared in manifest)

---

## Installation

1. Clone or download this repository.
2. Create the folder `custom_components/mistral_ai_api` in your Home Assistant configuration directory.
3. Copy the files from this repository into that folder.
4. Restart Home Assistant.
5. Add the integration in the UI: Configuration → Integrations → Add Integration → "Mistral AI Conversation".

---

## Entities Created

- conversation.mistral_ai... — Conversation agent entity (voice / chat)
- ai_task.mistral_ai_task... — AI Task entity for structured JSON responses
- device entries are created per subentry; device info shows the model in use

---

## Services

### mistral_ai_api.generate_content

Send a one-off prompt to a configured Mistral config entry and get the synchronous textual response.

Service schema:
- config_entry (required) — config entry selector for `mistral_ai_api`
- prompt (required) — the text prompt to send
- filenames (optional) — list of local file paths to attach to the prompt (must be allowed by allowlist_external_dirs)

Example usage:

```yaml
service: mistral_ai_api.generate_content
data:
  config_entry: "YOUR_CONFIG_ENTRY_ID"
  prompt: >
    Give me a short morning briefing for today.
  filenames:
    - "/config/notes/today.txt"
```

The service returns a response with `response.text` in the service response.

---

## Conversation (Conversation Agent)

- The integration registers a Conversation agent compatible with Home Assistant's conversation framework.
- The agent supports streaming (`_attr_supports_streaming = True`) so you get partial responses as SSE chunks.
- If configured to enable the Home Assistant LLM APIs, the agent advertises control features (tools integration).

Example automation calling the conversation agent:

```yaml
alias: "Ask Mistral for temperature"
trigger:
  - platform: state
    entity_id: sensor.living_room_temperature
action:
  - service: conversation.process
    data:
      agent_id: "conversation.mistral_ai"
      text: >
        The current temperature in the living room is {{ states('sensor.living_room_temperature') }} °C.
        Any suggestions?
```

---

## AI Task (Structured Output)

- AI Task entities implement structured data generation (generate_data) and use the Mistral API to produce results.
- If you provide a JSON schema for the task, the integration will instruct Mistral to return strictly-valid JSON matching the schema and will parse it into Home Assistant objects.
- If Mistral returns invalid JSON when a schema is required, the task errors out with an explanatory Home AssistantError.

---

## New / Notable Configuration Options

Configuration is done via the integration UI when adding a conversation or AI Task subentry. There is a "Recommended model settings" toggle; when checked, the integration uses the recommended presets. If you uncheck it you can set advanced options.

Available options and defaults:

- recommended (bool)
  - When true, recommended defaults are used for model & parameters. Defaults to true.
- chat_model (string)
  - The Mistral model to use. Dropdown includes:
    - mistral-large-latest (recommended)
    - mistral-medium-latest
    - mistral-small-latest
    - open-mistral-7b
    - open-mixtral-8x7b
    - open-mixtral-8x22b
    - pixtral-12b-latest
  - Default (recommended): `mistral-large-latest`.
- max_tokens (integer)
  - Maximum tokens to allow in the response. Recommended default: 4096.
- temperature (float)
  - Sampling temperature to control creativity. Recommended default: 0.7.
- top_p (float)
  - Nucleus sampling parameter. Recommended default: 0.9.
- reasoning_effort (string)
  - If supported by the model, controls internal resource allocation / reasoning mode. Recommended default: `medium`.
- prompt (template)
  - System instructions / template instructing the assistant how to behave. Defaults to Home Assistant's default instructions or a system prompt appropriate for a voice assistant.
- llm_hass_api (list)
  - A list of Home Assistant LLM APIs (e.g., LLM_API_ASSIST). Select which HA LLM APIs the subentry exposes / accepts.
- default_media_player (entity selector) — NEW
  - Select a `media_player` entity that the conversation agent should use as the default output target for music commands (friendly name is injected into the system prompt).
  - If a media player entity is set here, the integration adds contextual instructions so Mistral will default to giving music/playback commands that target that player.
- music_assistant_config_entry (config entry id)
  - Optionally point to a Music Assistant configuration entry (if you use Music Assistant); the integration includes helper function(s) to obtain that config entry id for tool calls (currently available to the entity options).
- filenames (service-level only)
  - When calling the `generate_content` service you can provide local file paths to attach their contents to the prompt (must be allowed by Home Assistant's allowlist_external_dirs).

Notes:
- If you keep "Recommended model settings" checked, the advanced model and parameter options are not required and recommended presets are used.
- Models in the drop-down allow custom values (you can type a model not in the provided list), but the integration may validate or reject unsupported models.

---

## Tools, Tool IDs and Streaming

- The integration converts Home Assistant LLM tools into Mistral "function" descriptors and passes them to Mistral with a controlled serializer.
- Tool call IDs are normalized to a Mistral-safe format (9-character alphanumeric IDs). A consistent ID mapping is kept for each chat session.
- Streaming responses are implemented by reading SSE chunks from the Mistral streaming endpoint and transforming them into Home Assistant assistant deltas.
- The integration will iterate tool-call attempts (up to a configurable number) to resolve tool results in chat logs.

---

## Music Assistant Integration

- If no Music Assistant tools are present in the LLM tools, the integration will automatically include helper tools for `music_assistant.search` and `music_assistant.play_media` so Mistral can produce music-related tool calls.
- Use the `default_media_player` setting to tell the assistant which player to use for playback commands; the integration injects a short instruction telling the assistant which player to address.

---

## Errors & Rate Limits

- API key validation: Mistral API key is validated by listing models during setup. Invalid API keys cause an authentication error and prevent enabling the integration.
- Network errors, timeouts, http status errors (401/429 etc.) are surfaced as appropriate Home Assistant config entry errors (ConfigEntryNotReady/ConfigEntryAuthFailed) or service errors.
- The integration contains safeguards and granular error handling for the common failure modes (auth, rate limits, and network timeouts).

---

## Behavior & Limitations

- No image generation support (Mistral does not currently offer an image generation API).
- Tool-call and LLM integrations rely on data passed to Mistral; make sure tools and their parameter schemas are correct.
- Streaming requires a stable external connection to Mistral for SSE.
- The component mirrors the official Home Assistant OpenAI Conversation integration architecture but targets Mistral.

---

## Examples

Synchronous service (generate_content):

```yaml
service: mistral_ai_api.generate_content
data:
  config_entry: "{{ state_attr('conversation.mistral_ai','config_entry_id') }}"
  prompt: >
    Provide a one-paragraph summary of events this morning.
```

Conversation usage (automation):

```yaml
alias: "Morning briefing with Mistral"
trigger:
  - platform: time
    at: "08:00:00"
action:
  - service: conversation.process
    data:
      agent_id: "conversation.mistral_ai"
      text: >
        Good morning. Give me a quick summary of what's important today.
```

AI Task example (structured JSON):

- Create an AI Task that requests:
  - a `structure` JSON schema from the AI Task platform
  - when executed, the assistant will be instructed to return JSON matching the schema and Home Assistant will parse it for use.

---

## Troubleshooting

- If entities do not appear after setup: ensure the integration is enabled in Integrations and check the config entry runtime logs.
- For authentication failures: re-check the API key in the integration options and ensure it has the proper scope on the Mistral console.
- If attached filenames cannot be read: ensure Home Assistant's `allowlist_external_dirs` includes the file paths and file permissions allow the HA process to read them.
- For streaming interruptions: check network connectivity and outbound access to api.mistral.ai.

---

## Development / Credits / License

- This component is based on the structure of Home Assistant's official OpenAI conversation integration but rewritten for Mistral.
- License: Apache License 2.0
- Code owner/author in manifest: @balloob (as recorded)
- See the repository for source and details: https://github.com/ThomasBergholdWieser/homeassistant-mistral
