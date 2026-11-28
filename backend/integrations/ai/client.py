"""A provider-neutral "ask a model for JSON" client.

Partiu does not tie a feature to one AI vendor. A feature reads its own block of
environment variables (``AI_SUGGESTIONS_*`` today, ``AI_EMAIL_*`` later) and gets
back an :class:`AiConfig`; :func:`complete_json` sends one question and returns
the answer as a dict that already matches the JSON schema it was given.

Two adapters cover every provider:

* ``anthropic`` — Claude, through the official ``anthropic`` SDK, with
  structured outputs (``output_config.format``) so the answer is valid JSON by
  construction.
* the OpenAI chat-completions shape — ``openai``, ``ollama`` and
  ``openai-compatible`` (OpenRouter, Groq, Mistral, Gemini, LM Studio, vLLM…).
  ``openai`` and ``ollama`` only differ in the default address. The answer is
  asked for with a ``json_schema`` response format, and the result is parsed
  and checked here, because not every server enforces the schema.

Nothing here retries a bad answer or second-guesses its content: the caller
decides what an answer may contain (see ``suggestions/service.py``).
"""

import json
import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

PROVIDERS = ("anthropic", "openai", "ollama", "openai-compatible")

# Only Claude gets a default model: for every other provider the right model is
# whatever that account or server has, and guessing one would fail confusingly.
_DEFAULT_MODELS = {"anthropic": "claude-haiku-5-5"}
_DEFAULT_BASE_URLS = {"openai": "https://api.openai.com/v1"}


class AiNotConfiguredError(Exception):
    """The feature's AI provider is not set up (or is set up wrongly)."""


class AiUnreachableError(Exception):
    """The provider could not be reached, refused the key, or rate-limited us."""


class AiBadAnswerError(Exception):
    """The provider answered, but not with what was asked for."""


@dataclass(frozen=True)
class AiConfig:
    provider: str
    model: str
    api_key: str
    base_url: str
    timeout: float
    effort: str


def config_from_env(prefix: str) -> AiConfig | None:
    """Read ``{prefix}_PROVIDER`` and friends; ``None`` when the feature is off.

    An unknown provider, or a provider missing what it cannot work without, is
    logged and treated as off rather than raising at import time: one bad
    variable must not stop the app from starting.
    """
    provider = os.getenv(f"{prefix}_PROVIDER", "").strip().lower()
    if not provider:
        return None
    if provider not in PROVIDERS:
        logger.error("%s_PROVIDER=%r is not one of %s; AI is off", prefix, provider, PROVIDERS)
        return None
    model = os.getenv(f"{prefix}_MODEL", "").strip() or _DEFAULT_MODELS.get(provider, "")
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", "").strip() or _DEFAULT_BASE_URLS.get(provider, "")
    missing = []
    if not model:
        missing.append(f"{prefix}_MODEL")
    if provider in ("anthropic", "openai") and not api_key:
        missing.append(f"{prefix}_API_KEY")
    if provider in ("ollama", "openai-compatible") and not base_url:
        missing.append(f"{prefix}_BASE_URL")
    if missing:
        logger.error("%s_PROVIDER=%s needs %s; AI is off", prefix, provider, ", ".join(missing))
        return None
    try:
        timeout = float(os.getenv(f"{prefix}_TIMEOUT", "60"))
    except ValueError:
        timeout = 60.0
    return AiConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        effort=os.getenv(f"{prefix}_EFFORT", "").strip().lower(),
    )


def complete_json(
    config: AiConfig, *, system: str, user: str, schema: dict, max_tokens: int = 4000
) -> dict:
    """Ask once; return the answer parsed as JSON (an object)."""
    if config.provider == "anthropic":
        return _anthropic(config, system, user, schema, max_tokens)
    return _openai_compatible(config, system, user, schema, max_tokens)


def _anthropic(config: AiConfig, system: str, user: str, schema: dict, max_tokens: int) -> dict:
    import anthropic

    client = anthropic.Anthropic(
        api_key=config.api_key,
        base_url=config.base_url or None,
        timeout=config.timeout,
        max_retries=1,
    )
    output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
    if config.effort:
        output_config["effort"] = config.effort
    try:
        response = client.messages.create(
            model=config.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,  # ty: ignore[invalid-argument-type]
        )
    except anthropic.AuthenticationError as e:
        raise AiUnreachableError("The AI provider refused the API key") from e
    except anthropic.BadRequestError as e:
        # A wrong model name or an unsupported option is configuration, not
        # something the traveller can fix by pressing the button again.
        raise AiNotConfiguredError(f"The AI provider rejected the request: {e.message}") from e
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.APIStatusError) as e:
        raise AiUnreachableError(f"The AI provider is unavailable: {e}") from e

    if response.stop_reason == "refusal":
        raise AiBadAnswerError("The model declined to answer")
    if response.stop_reason == "max_tokens":
        raise AiBadAnswerError("The answer was cut off")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return _parse_object(text)


def _openai_compatible(
    config: AiConfig, system: str, user: str, schema: dict, max_tokens: int
) -> dict:
    base = config.base_url.rstrip("/")
    # Ollama serves the OpenAI shape under /v1; let people paste the server
    # address they already know.
    if config.provider == "ollama" and not base.endswith("/v1"):
        base += "/v1"
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    body = {
        "model": config.model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema, "strict": True},
        },
    }
    try:
        response = httpx.post(
            f"{base}/chat/completions", json=body, headers=headers, timeout=config.timeout
        )
        if response.status_code == 400:
            # Some compatible servers know JSON mode but not schemas.
            body["response_format"] = {"type": "json_object"}
            response = httpx.post(
                f"{base}/chat/completions", json=body, headers=headers, timeout=config.timeout
            )
    except httpx.HTTPError as e:
        raise AiUnreachableError(f"The AI provider is unavailable: {e}") from e
    if response.status_code in (401, 403):
        raise AiUnreachableError("The AI provider refused the API key")
    if response.status_code == 404:
        raise AiNotConfiguredError("The AI provider does not know this model or address")
    if response.status_code >= 400:
        raise AiUnreachableError(f"The AI provider answered {response.status_code}")
    try:
        choice = response.json()["choices"][0]
        text = choice["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise AiBadAnswerError("The AI provider's answer had an unexpected shape") from e
    if choice.get("finish_reason") == "length":
        raise AiBadAnswerError("The answer was cut off")
    return _parse_object(text)


def _parse_object(text: str) -> dict:
    text = text.strip()
    # Tolerate a fenced block from servers that only do loose JSON mode.
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :] if "{" in text else text
    try:
        data = json.loads(text)
    except ValueError as e:
        raise AiBadAnswerError("The answer was not JSON") from e
    if not isinstance(data, dict):
        raise AiBadAnswerError("The answer was not a JSON object")
    return data
