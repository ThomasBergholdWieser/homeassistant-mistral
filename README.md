# Mistral AI für Home Assistant

---

## 🇩🇪 Deutsch

### Was ist das?

Mit dieser Custom Component kannst du Mistral AI direkt in Home Assistant nutzen. Die Integration ist ein Umbau der offiziellen OpenAI-Integration.

### Was kann die Integration?

- Nutzt die [Mistral Chat API](https://docs.mistral.ai/api/) für Antworten und Steuerbefehle
- Funktioniert mit dem Home Assistant Conversation-Agent (Sprachsteuerung, Chat, Automationen)
- Unterstützt AI Tasks (strukturierte Ausgabe/JSON, Automationen, Datenverarbeitung)
- Auswahl des Mistral-Modells direkt über die Optionsoberfläche (nach Deaktivieren der empfohlenen Einstellungen)
- Tool-Calls und Home-Assistant-LLM-APIs werden an Mistral durchgeschleift, sodass z. B. `GetLiveContext` oder Intent-Tools funktionieren
- System-Prompt sorgt dafür, dass die KI sich auf Smart-Home-Kommandos konzentriert
- Keine Bildgenerierung (Mistral stellt keine Image-API bereit)

### Was brauchst du?

- Home Assistant (ab Version 2025.12 Core getestet)
- Einen Mistral API Key ([hier bekommst du einen](https://console.mistral.ai/command-center/api-keys))

### Installation

1. Lade dieses Repository herunter (oder klone es)
2. Lege den Ordner `custom_components/mistral_ai_api` in deinem Home Assistant `config`-Verzeichnis an
3. Kopiere alle Dateien aus diesem Repo in diesen Ordner
4. Starte Home Assistant neu

### Einrichtung & Nutzung

1. Füge die Integration über die Home Assistant UI hinzu ("Integration hinzufügen" > "Mistral AI Conversation").
2. Gib deinen API-Key ein. Danach findest du mindestens zwei Entitäten:
   - `conversation.mistral_ai…` – Conversation-Agent für Voice/Chat
   - `ai_task.mistral_ai_task…` – AI-Task-Entity für strukturierte Ausgaben
3. Unter „Konfigurieren“ kannst du die empfohlenen Einstellungen übernehmen oder (Haken entfernen) Modell, `max_tokens`, `temperature`, `top_p`, `reasoning_effort` usw. selbst setzen.

#### Beispiel-Workflows

**1. Conversation-Agent (`conversation.process`)**

```yaml
alias: "Frage Mistral nach Temperatur"
trigger:
  - platform: state
    entity_id: sensor.wohnzimmer_temperature
action:
  - service: conversation.process
    data:
      agent_id: "conversation.mistral_ai"
      text: >
        Die aktuelle Temperatur im Wohnzimmer beträgt {{ states('sensor.wohnzimmer_temperature') }} °C.
        Welche Idee hast du?
```

**2. Service `mistral_ai_api.generate_content` (synchroner Text)**  
Der Service liefert das Ergebnis sofort in `response.text`, wodurch du den Text z. B. an Notification-Dienste senden kannst:

```yaml
alias: "Mistral Service Beispiel"
mode: single
trigger:
  - platform: time
    at: "08:00:00"
action:
  - service: mistral_ai_api.generate_content
    data:
      config_entry: "{{ state_attr('conversation.mistral_ai','config_entry_id') }}"
      prompt: >
        Guten Morgen! Erstelle mir eine kurze To-do-Liste
        auf Basis der nächsten 12 Stunden Kalenderdaten.
  - service: notify.mobile_app_mein_handy
    data:
      message: "{{ response.text }}"
```

**3. AI Task (`ai_task.generate_data`) – strukturierte Ausgabe**  
Perfekt, wenn du JSON-Daten für weitere Automationen brauchst:

```yaml
alias: "Generiere Ideen für Automationen"
mode: single
trigger:
  - platform: time
    at: "21:00:00"
action:
  - service: ai_task.generate_data
    target:
      entity_id: ai_task.mistral_ai_task
    data:
      task_id: "abend_check"
      prompt: >
        Temperatur Wohnzimmer: {{ states('sensor.wohnzimmer_temperature') }} °C.
        Erstelle eine JSON-Liste mit Vorschlägen für Automationen heute Abend.
  - service: script.handle_ai_task_output
    data:
      payload: "{{ response.data }}"
```

> `response.text` bzw. `response.data` stehen nach dem Service-Aufruf zur Verfügung und können direkt in nachfolgenden Aktionen verwendet werden.

### Noch wichtig

- Die Integration ist stabil, aber Rückmeldungen sind immer willkommen!
- Bildgenerierung ist nicht möglich.
- Tool-Calls und Websuche außerhalb von Home Assistant sind aktuell nicht vorgesehen.
- **Technischer Hinweis:** Diese Komponente basiert auf der offiziellen OpenAI-Conversation-Integration, ist aber komplett auf Mistral umgebaut.

### Lizenz

Apache License 2.0

Teile dieses Codes basieren auf der offiziellen Home Assistant OpenAI-Integration (Apache License 2.0).

---

**Links:**
- [Mistral AI API Docs](https://docs.mistral.ai/api/)
- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [Official Home Assistant OpenAI-Integration (GitHub)](https://github.com/home-assistant/core/tree/dev/homeassistant/components/openai_conversation)

## 🇬🇧 English

### What is this?

This custom component lets you use Mistral AI in Home Assistant – for voice control, chatbots, or smart automations. It's a full rewrite of the official OpenAI integration, but everything runs on the Mistral API now.

### What does it do?

- Uses the [Mistral Chat API](https://docs.mistral.ai/api/) for smart replies and home control
- Works with Home Assistant Conversation (voice, chat, automations)
- You can pick the Mistral model right in the UI (e.g. `mistral-medium`, `mistral-large`)
- System prompt keeps the AI focused on smart home commands
- Conversation history is saved (if you want)
- No image generation (Mistral doesn't support it yet)

### What do you need?

- Home Assistant (tested from version 2024.5)
- A Mistral API key ([get one here](https://console.mistral.ai/))

### Installation

1. Download this repo (or clone it)
2. Create the folder `custom_components/mistral_ai_api` in your Home Assistant `config` directory
3. Copy all files from this repo into that folder
4. Restart Home Assistant

### Setup & Usage

1. Add the integration via the Home Assistant UI ("Add Integration" > "Mistral AI Conversation").
2. Enter your API key. Home Assistant creates at least two entities for you:
   - `conversation.mistral_ai…` – Conversation agent for voice/chat
   - `ai_task.mistral_ai_task…` – AI Task entity for structured output
3. In the options dialog you can stay with the recommended defaults or uncheck the box to set model, `max_tokens`, `temperature`, `top_p`, `reasoning_effort`, … yourself.

#### Example flows

**1. Conversation agent via `conversation.process`**

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

**2. `mistral_ai_api.generate_content` (synchronous text)**  
Returns `response.text`, so you can forward it directly, e.g. to a notification service:

```yaml
alias: "Daily briefing"
trigger:
  - platform: time
    at: "08:00:00"
action:
  - service: mistral_ai_api.generate_content
    data:
      config_entry: "{{ state_attr('conversation.mistral_ai','config_entry_id') }}"
      prompt: >
        Good morning! Summarize the next 12 hours of my calendar
        and list any reminders from Home Assistant.
  - service: notify.mobile_app_my_phone
    data:
      message: "{{ response.text }}"
```

**3. AI Task via `ai_task.generate_data`**  
Great for JSON output that you want to process further:

```yaml
alias: "AI task example"
mode: single
trigger:
  - platform: time
    at: "21:00:00"
action:
  - service: ai_task.generate_data
    target:
      entity_id: ai_task.mistral_ai_task
    data:
      task_id: "evening_check"
      prompt: >
        Temperature living room: {{ states('sensor.living_room_temperature') }} °C.
        Create a JSON list of possible automations for tonight.
  - service: script.handle_ai_task_output
    data:
      payload: "{{ response.data }}"
```

> `response.text` (generate_content) and `response.data` (ai_task) are available right after the service call and can be used in follow-up actions.

### Good to know

- The integration is stable, but feedback is always welcome!
- Image generation is currently not supported (Mistral offers no image API).
- Tool calls, HA intent tools and AI tasks are supported (same code paths as the OpenAI integration).
- Web search outside Home Assistant is not part of this integration right now.
- **Technical note:** This component mirrors the official OpenAI Conversation integration but calls the Mistral chat API instead.

### License

Apache License 2.0

Parts of this code are based on the official Home Assistant OpenAI integration (Apache License 2.0).

---

**Links:**
- [Mistral AI API Docs](https://docs.mistral.ai/api/)
- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [Official Home Assistant OpenAI-Integration (GitHub)](https://github.com/home-assistant/core/tree/dev/homeassistant/components/openai_conversation)
