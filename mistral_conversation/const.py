# Modified by Louis Rokitta
"""Constants for the Mistral AI Conversation integration."""

from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.helpers import llm
import logging

DOMAIN = "mistral_ai_api"
LOGGER: logging.Logger = logging.getLogger(__package__)

DEFAULT_CONVERSATION_NAME = "Mistral Conversation"
DEFAULT_AI_TASK_NAME = "Mistral AI Task"
DEFAULT_NAME = "Mistral Conversation"

CONF_CHAT_MODEL = "chat_model"
CONF_FILENAMES = "filenames"
CONF_MAX_TOKENS = "max_tokens"
CONF_PROMPT = "prompt"
CONF_REASONING_EFFORT = "reasoning_effort"
CONF_RECOMMENDED = "recommended"
CONF_TEMPERATURE = "temperature"
CONF_TOP_P = "top_p"

RECOMMENDED_CHAT_MODEL = "mistral-large-latest"
RECOMMENDED_MAX_TOKENS = 4096
RECOMMENDED_REASONING_EFFORT = "medium"
RECOMMENDED_TEMPERATURE = 0.7
RECOMMENDED_TOP_P = 0.9
DEFAULT_SYSTEM_PROMPT = (
    "You are TARS, a smart home AI assistant inspired by the robot from Interstellar.\n"
    "Your humor setting is at 75%. You are witty, sarcastic, and occasionally dry — "
    "but always helpful and reliable when it counts.\n"
    "You assist the user with their Home Assistant smart home. "
    "When controlling devices, call the appropriate tools. "
    "Do not make up device names or services; only use what is available.\n"
    "If the user asks something unrelated to the smart home, "
    "answer it normally but keep your characteristic TARS attitude.\n"
    "Keep your answers brief and to the point — like a good robot should. "
    "No unnecessary monologues, unless the user asks for it.\n"
    "When something goes wrong, respond with dry humor instead of boring error messages.\n"
    "Always respond in the same language as the user."
)
MAX_TOOL_ITERATIONS = 10

UNSUPPORTED_MODELS: list[str] = []
WEB_SEARCH_MODELS: list[str] = []

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_RECOMMENDED: True,
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}
RECOMMENDED_AI_TASK_OPTIONS = {
    CONF_RECOMMENDED: True,
}
