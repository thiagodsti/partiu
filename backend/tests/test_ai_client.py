"""Tests for the provider-neutral AI client (backend/integrations/ai/client.py)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.integrations.ai import client as ai
from backend.integrations.ai.client import (
    AiBadAnswerError,
    AiConfig,
    AiNotConfiguredError,
    AiUnreachableError,
    complete_json,
    config_from_env,
)

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


def _env(monkeypatch, **values):
    for key in ("PROVIDER", "MODEL", "API_KEY", "BASE_URL", "TIMEOUT", "EFFORT"):
        monkeypatch.delenv(f"T_{key}", raising=False)
    for key, value in values.items():
        monkeypatch.setenv(f"T_{key}", value)


class TestConfigFromEnv:
    def test_unset_is_off(self, monkeypatch):
        _env(monkeypatch)
        assert config_from_env("T") is None

    def test_anthropic_defaults_to_haiku(self, monkeypatch):
        _env(monkeypatch, PROVIDER="anthropic", API_KEY="k")
        config = config_from_env("T")
        assert config is not None and config.model == "claude-haiku-5-5"

    def test_an_unknown_provider_is_off(self, monkeypatch):
        _env(monkeypatch, PROVIDER="skynet", API_KEY="k", MODEL="m")
        assert config_from_env("T") is None

    @pytest.mark.parametrize(
        "values",
        [
            {"PROVIDER": "anthropic"},  # no key
            {"PROVIDER": "openai", "API_KEY": "k"},  # no model
            {"PROVIDER": "ollama", "MODEL": "qwen3:14b"},  # no address
            {"PROVIDER": "openai-compatible", "MODEL": "m", "API_KEY": "k"},  # no address
        ],
    )
    def test_a_provider_missing_what_it_needs_is_off(self, monkeypatch, values):
        _env(monkeypatch, **values)
        assert config_from_env("T") is None

    def test_ollama_needs_no_key(self, monkeypatch):
        _env(monkeypatch, PROVIDER="ollama", MODEL="qwen3:14b", BASE_URL="http://box:11434")
        config = config_from_env("T")
        assert config is not None and config.api_key == ""

    def test_openai_gets_its_address_filled_in(self, monkeypatch):
        _env(monkeypatch, PROVIDER="OpenAI", MODEL="gpt-x", API_KEY="k")
        config = config_from_env("T")
        assert config is not None and config.base_url == "https://api.openai.com/v1"


def _config(
    provider: str = "anthropic", *, api_key: str = "k", base_url: str = "", effort: str = ""
) -> AiConfig:
    return AiConfig(
        provider=provider, model="m", api_key=api_key, base_url=base_url, timeout=5.0, effort=effort
    )


class TestAnthropic:
    def _reply(self, text='{"a": 1}', stop="end_turn"):
        return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])

    def test_asks_for_the_schema_and_returns_the_object(self):
        fake = MagicMock()
        fake.return_value.messages.create.return_value = self._reply()
        with patch("anthropic.Anthropic", fake):
            assert complete_json(_config(effort="low"), system="s", user="u", schema=SCHEMA) == {
                "a": 1
            }
        kwargs = fake.return_value.messages.create.call_args.kwargs
        assert kwargs["output_config"] == {
            "format": {"type": "json_schema", "schema": SCHEMA},
            "effort": "low",
        }
        assert kwargs["system"] == "s" and kwargs["messages"] == [{"role": "user", "content": "u"}]

    def test_a_refusal_is_a_bad_answer(self):
        fake = MagicMock()
        fake.return_value.messages.create.return_value = self._reply(stop="refusal")
        with patch("anthropic.Anthropic", fake), pytest.raises(AiBadAnswerError):
            complete_json(_config(), system="s", user="u", schema=SCHEMA)

    def test_a_rejected_key_is_unreachable(self):
        import anthropic
        import httpx2

        fake = MagicMock()
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        fake.return_value.messages.create.side_effect = anthropic.AuthenticationError(
            "bad key", response=httpx2.Response(401, request=request), body=None
        )
        with patch("anthropic.Anthropic", fake), pytest.raises(AiUnreachableError):
            complete_json(_config(), system="s", user="u", schema=SCHEMA)


class TestOpenAiCompatible:
    def _response(self, status=200, content='{"a": 2}', finish="stop"):
        return httpx.Response(
            status,
            json={"choices": [{"message": {"content": content}, "finish_reason": finish}]},
            request=httpx.Request("POST", "http://x"),
        )

    def test_ollama_is_served_under_v1_without_a_key(self):
        config = _config("ollama", api_key="", base_url="http://box:11434")
        with patch.object(ai.httpx, "post", return_value=self._response()) as post:
            assert complete_json(config, system="s", user="u", schema=SCHEMA) == {"a": 2}
        url = post.call_args.args[0]
        assert url == "http://box:11434/v1/chat/completions"
        assert "Authorization" not in post.call_args.kwargs["headers"]
        assert post.call_args.kwargs["json"]["response_format"]["type"] == "json_schema"

    def test_falls_back_to_json_mode_when_schemas_are_refused(self):
        config = _config("openai-compatible", base_url="https://router.example/v1")
        replies = [self._response(400, content=""), self._response()]
        with patch.object(ai.httpx, "post", side_effect=replies) as post:
            assert complete_json(config, system="s", user="u", schema=SCHEMA) == {"a": 2}
        assert post.call_args.kwargs["json"]["response_format"] == {"type": "json_object"}
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer k"

    def test_a_fenced_answer_is_still_read(self):
        config = _config("openai", base_url="https://api.openai.com/v1")
        with patch.object(
            ai.httpx, "post", return_value=self._response(content='```json\n{"a": 3}\n```')
        ):
            assert complete_json(config, system="s", user="u", schema=SCHEMA) == {"a": 3}

    @pytest.mark.parametrize(
        ("status", "error"),
        [(401, AiUnreachableError), (404, AiNotConfiguredError), (500, AiUnreachableError)],
    )
    def test_http_errors(self, status, error):
        config = _config("openai", base_url="https://api.openai.com/v1")
        with (
            patch.object(ai.httpx, "post", return_value=self._response(status)),
            pytest.raises(error),
        ):
            complete_json(config, system="s", user="u", schema=SCHEMA)

    def test_a_cut_off_or_non_json_answer_is_bad(self):
        config = _config("openai", base_url="https://api.openai.com/v1")
        with patch.object(ai.httpx, "post", return_value=self._response(finish="length")):
            with pytest.raises(AiBadAnswerError):
                complete_json(config, system="s", user="u", schema=SCHEMA)
        with patch.object(ai.httpx, "post", return_value=self._response(content="sure! here")):
            with pytest.raises(AiBadAnswerError):
                complete_json(config, system="s", user="u", schema=SCHEMA)

    def test_content_that_is_not_text_is_a_bad_answer(self):
        config = _config("openai", base_url="https://api.openai.com/v1")
        parts = [{"type": "text", "text": '{"a": 1}'}]
        with patch.object(ai.httpx, "post", return_value=self._response(content=parts)):
            with pytest.raises(AiBadAnswerError):
                complete_json(config, system="s", user="u", schema=SCHEMA)

    def test_unreachable_server(self):
        config = _config("ollama", api_key="", base_url="http://box:11434")
        with patch.object(ai.httpx, "post", side_effect=httpx.ConnectError("no route")):
            with pytest.raises(AiUnreachableError):
                complete_json(config, system="s", user="u", schema=SCHEMA)
