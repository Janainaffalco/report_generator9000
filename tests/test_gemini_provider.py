from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from report_generator9000.events import Event
from report_generator9000.gemini_provider import (
    DEFAULT_GEMINI_FALLBACK_MODEL,
    DEFAULT_GEMINI_MODEL,
    GeminiProseProvider,
    GeminiProviderError,
    GeminiSettings,
)
from report_generator9000.prose import (
    ProseConfig,
    ProseRequest,
    ProviderPageText,
)


class _RaisingModels:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        raise self.error


class _BothFailModels:
    def __init__(self, primary_error: Exception, fallback_error: Exception) -> None:
        self.primary_error = primary_error
        self.fallback_error = fallback_error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise self.primary_error
        raise self.fallback_error


class _Models:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


class _Client:
    def __init__(self, response: object) -> None:
        self.models = _Models(response)


class _FallbackModels:
    def __init__(self, fallback_response: object) -> None:
        self.fallback_response = fallback_response
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            error = RuntimeError("overloaded")
            error.code = 503
            error.status = "UNAVAILABLE"
            raise error
        return self.fallback_response


def _request() -> ProseRequest:
    return ProseRequest(
        site_text=(
            ProviderPageText(
                source_id="page-1",
                text="A Acme fabrica componentes industriais.",
            ),
            ProviderPageText(
                source_id="page-2",
                text="O site apresenta serviços de engenharia.",
            ),
        )
    )


def _settings() -> GeminiSettings:
    return GeminiSettings(api_key="test-key")


def test_provider_uses_structured_output_and_preserves_exact_citations() -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(finish_reason=SimpleNamespace(value="STOP"))
        ],
        parsed=None,
        text=json.dumps(
            {
                "company_description": {
                    "value": "A Acme fabrica componentes industriais.",
                    "citations": [
                        {
                            "source_id": "page-1",
                            "excerpt": (
                                "A Acme fabrica componentes industriais."
                            ),
                        }
                    ],
                },
                "briefing_objective": {
                    "value": (
                        "O site apresenta os serviços de engenharia."
                    ),
                    "citations": [
                        {
                            "source_id": "page-2",
                            "excerpt": (
                                "O site apresenta serviços de engenharia."
                            ),
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
    )
    client = _Client(response)
    provider = GeminiProseProvider(_settings(), client=client)

    result = provider.generate(
        _request(),
        ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
    )

    assert result.company_description.grounded is True
    assert result.company_description.citations[0].source_id == "page-1"
    assert result.briefing_objective.citations[0].excerpt == (
        "O site apresenta serviços de engenharia."
    )
    call = client.models.calls[0]
    assert call["model"] == DEFAULT_GEMINI_MODEL
    assert "FONTE page-1" in str(call["contents"])
    assert "FONTE page-2" in str(call["contents"])
    config = call["config"]
    assert config.max_output_tokens == 700
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["additionalProperties"] is False
    assert config.thinking_config.thinking_level.value == "LOW"
    assert config.tools is None


def test_system_instruction_contains_briefing_one_shot_example() -> None:
    from report_generator9000.gemini_provider import _SYSTEM_INSTRUCTION

    normalized = " ".join(_SYSTEM_INSTRUCTION.split())
    assert (
        "O responsável pela ARGEL Resistências Elétricas Ltda manifestou o "
        "interesse em desenvolver um site institucional com o objetivo de "
        "fortalecer a presença digital da empresa, apresentar sua trajetória "
        "e destacar seu portfólio de produtos."
    ) in normalized
    assert "não copie os fatos nem o nome da empresa" in normalized


@pytest.mark.parametrize("reason", ["MAX_TOKENS", "BUDGET_EXCEEDED"])
def test_provider_marks_budget_exhaustion(reason: str) -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(finish_reason=SimpleNamespace(value=reason))
        ],
        parsed=None,
        text=None,
    )
    provider = GeminiProseProvider(_settings(), client=_Client(response))

    result = provider.generate(
        _request(),
        ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=10),
    )

    assert result.output_budget_exhausted is True


def test_provider_falls_back_only_after_primary_overload() -> None:
    response = SimpleNamespace(
        candidates=[],
        parsed=None,
        text=json.dumps(
            {
                "company_description": {
                    "value": "A Acme fabrica componentes.",
                    "citations": [
                        {
                            "source_id": "page-1",
                            "excerpt": "A Acme fabrica componentes",
                        }
                    ],
                },
                "briefing_objective": {
                    "value": None,
                    "citations": [],
                },
            }
        ),
    )
    client = SimpleNamespace(models=_FallbackModels(response))
    provider = GeminiProseProvider(_settings(), client=client)

    result = provider.generate(
        _request(),
        ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
    )

    assert result.company_description.grounded is True
    assert [call["model"] for call in client.models.calls] == [
        DEFAULT_GEMINI_MODEL,
        DEFAULT_GEMINI_FALLBACK_MODEL,
    ]
    assert provider.last_model_used == DEFAULT_GEMINI_FALLBACK_MODEL


def test_invalid_structured_response_fails_closed() -> None:
    response = SimpleNamespace(
        candidates=[],
        parsed=None,
        text='{"company_description": "not a field"}',
    )
    provider = GeminiProseProvider(_settings(), client=_Client(response))

    with pytest.raises(
        GeminiProviderError, match="invalid structured response"
    ):
        provider.generate(
            _request(),
            ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
        )


def test_settings_load_dotenv_and_prefer_google_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "GEMINI_API_KEY=gemini-key",
                "GEMINI_MODEL=gemini-3.5-flash",
                "GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite",
                "GEMINI_OUTPUT_BUDGET=900",
                "GEMINI_TIMEOUT_SECONDS=45",
                "GEMINI_MAX_ATTEMPTS=4",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "deployment-key")

    settings = GeminiSettings.from_environment()

    assert settings.api_key == "deployment-key"
    assert settings.fallback_model == "gemini-3.5-flash-lite"
    assert settings.output_budget == 900
    assert settings.timeout_seconds == 45
    assert settings.max_attempts == 4


def test_missing_key_has_deployment_help(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(GeminiProviderError, match=r"\.env\.example"):
        GeminiSettings.from_environment()


def _gemini_call_events(events: list[Event]) -> list[Event]:
    return [event for event in events if event.name == "gemini_call"]


def test_primary_non_overload_failure_logs_real_status_code_message(
    recording_sink,
) -> None:
    error = RuntimeError("internal error")
    error.code = 500
    error.status = "INTERNAL"
    provider = GeminiProseProvider(
        _settings(), client=SimpleNamespace(models=_RaisingModels(error))
    )

    with pytest.raises(GeminiProviderError, match="Gemini request failed: RuntimeError"):
        provider.generate(
            _request(),
            ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
        )

    calls = _gemini_call_events(recording_sink.events)
    ends = [event for event in calls if event.kind == "operation_end"]
    assert len(ends) == 1
    end = ends[0]
    assert end.severity == "error"
    assert end.fields["error"] == "RuntimeError"
    assert end.fields["status"] == "INTERNAL"
    assert end.fields["code"] == 500
    assert end.fields["model"] == DEFAULT_GEMINI_MODEL
    failures = [
        event
        for event in recording_sink.events
        if event.name == "gemini_call_failed"
    ]
    assert len(failures) == 1
    assert failures[0].detail["message"] == "internal error"
    assert "message" not in failures[0].fields


def test_fallback_success_emits_warning_naming_both_models(
    recording_sink,
) -> None:
    response = SimpleNamespace(
        candidates=[],
        parsed=None,
        text=json.dumps(
            {
                "company_description": {
                    "value": "A Acme fabrica componentes.",
                    "citations": [
                        {
                            "source_id": "page-1",
                            "excerpt": "A Acme fabrica componentes",
                        }
                    ],
                },
                "briefing_objective": {"value": None, "citations": []},
            }
        ),
    )
    client = SimpleNamespace(models=_FallbackModels(response))
    provider = GeminiProseProvider(_settings(), client=client)

    provider.generate(
        _request(),
        ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
    )

    warnings = [
        event
        for event in recording_sink.events
        if event.name == "gemini_fallback_succeeded"
    ]
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.severity == "warning"
    assert warning.fields["primary_model"] == DEFAULT_GEMINI_MODEL
    assert warning.fields["fallback_model"] == DEFAULT_GEMINI_FALLBACK_MODEL

    calls = _gemini_call_events(recording_sink.events)
    ends = [event for event in calls if event.kind == "operation_end"]
    assert len(ends) == 2
    assert ends[0].severity == "error"
    assert ends[0].fields["model"] == DEFAULT_GEMINI_MODEL
    assert ends[1].severity == "info"
    assert ends[1].fields["model"] == DEFAULT_GEMINI_FALLBACK_MODEL


def test_fallback_also_fails_logs_two_distinguishable_operations(
    recording_sink,
) -> None:
    primary_error = RuntimeError("overloaded")
    primary_error.code = 503
    primary_error.status = "UNAVAILABLE"
    fallback_error = RuntimeError("fallback broke")
    fallback_error.code = 500
    fallback_error.status = "INTERNAL"
    client = SimpleNamespace(
        models=_BothFailModels(primary_error, fallback_error)
    )
    provider = GeminiProseProvider(_settings(), client=client)

    with pytest.raises(
        GeminiProviderError,
        match="both primary and fallback models: RuntimeError",
    ):
        provider.generate(
            _request(),
            ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
        )

    calls = _gemini_call_events(recording_sink.events)
    ends = [event for event in calls if event.kind == "operation_end"]
    assert len(ends) == 2
    assert ends[0].fields["model"] == DEFAULT_GEMINI_MODEL
    assert ends[0].fields["status"] == "UNAVAILABLE"
    assert ends[0].fields["code"] == 503
    assert ends[1].fields["model"] == DEFAULT_GEMINI_FALLBACK_MODEL
    assert ends[1].fields["status"] == "INTERNAL"
    assert ends[1].fields["code"] == 500
    failures = [
        event
        for event in recording_sink.events
        if event.name == "gemini_call_failed"
    ]
    assert len(failures) == 2
    assert failures[0].detail["message"] != failures[1].detail["message"]


def test_budget_exhausted_emits_warning_notice(recording_sink) -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(finish_reason=SimpleNamespace(value="MAX_TOKENS"))
        ],
        parsed=None,
        text=None,
    )
    provider = GeminiProseProvider(_settings(), client=_Client(response))

    result = provider.generate(
        _request(),
        ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=10),
    )

    assert result.output_budget_exhausted is True
    warnings = [
        event
        for event in recording_sink.events
        if event.name == "gemini_budget_exhausted"
    ]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert warnings[0].fields["model"] == DEFAULT_GEMINI_MODEL
    assert warnings[0].fields["output_budget"] == 10


def test_unparseable_response_puts_truncated_response_only_in_detail(
    recording_sink,
) -> None:
    long_text = "x" * 800
    response = SimpleNamespace(
        candidates=[],
        parsed=None,
        text=long_text,
    )
    provider = GeminiProseProvider(_settings(), client=_Client(response))

    with pytest.raises(
        GeminiProviderError, match="invalid structured response"
    ):
        provider.generate(
            _request(),
            ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
        )

    notices = [
        event
        for event in recording_sink.events
        if event.name == "gemini_response_unparseable"
    ]
    assert len(notices) == 1
    notice = notices[0]
    assert notice.severity == "error"
    excerpt = notice.detail["response_excerpt"]
    assert len(excerpt) <= 500
    assert excerpt == long_text[:500]
    assert "response_excerpt" not in notice.fields
    assert long_text not in str(notice.fields)


def test_model_used_logged_on_successful_call(recording_sink) -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(finish_reason=SimpleNamespace(value="STOP"))
        ],
        parsed=None,
        text=json.dumps(
            {
                "company_description": {
                    "value": "A Acme fabrica componentes.",
                    "citations": [
                        {
                            "source_id": "page-1",
                            "excerpt": "A Acme fabrica componentes.",
                        }
                    ],
                },
                "briefing_objective": {"value": None, "citations": []},
            }
        ),
    )
    provider = GeminiProseProvider(_settings(), client=_Client(response))

    provider.generate(
        _request(),
        ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
    )

    assert provider.last_model_used == DEFAULT_GEMINI_MODEL
    ends = [
        event
        for event in _gemini_call_events(recording_sink.events)
        if event.kind == "operation_end"
    ]
    assert len(ends) == 1
    assert ends[0].severity == "info"
    assert ends[0].fields["model"] == DEFAULT_GEMINI_MODEL


def test_successful_response_is_available_in_run_log_detail(
    recording_sink,
) -> None:
    response_text = json.dumps(
        {
            "company_description": {
                "value": "A Acme fabrica componentes.",
                "citations": [
                    {
                        "source_id": "page-1",
                        "excerpt": "A Acme fabrica componentes",
                    }
                ],
            },
            "briefing_objective": {
                "value": None,
                "citations": [],
            },
        },
        ensure_ascii=False,
    )
    response = SimpleNamespace(
        candidates=[],
        parsed=None,
        text=response_text,
    )
    provider = GeminiProseProvider(_settings(), client=_Client(response))

    provider.generate(
        _request(),
        ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
    )

    responses = [
        event
        for event in recording_sink.events
        if event.name == "gemini_response_received"
    ]
    assert len(responses) == 1
    assert responses[0].fields == {
        "model": DEFAULT_GEMINI_MODEL,
        "response_chars": len(response_text),
    }
    assert responses[0].detail["response"] == response_text


def test_prompt_content_never_appears_in_any_emitted_event(
    recording_sink,
) -> None:
    from report_generator9000.gemini_provider import _SYSTEM_INSTRUCTION

    long_text = "x" * 800
    response = SimpleNamespace(candidates=[], parsed=None, text=long_text)
    provider = GeminiProseProvider(_settings(), client=_Client(response))
    request = _request()
    source_texts = [page.text for page in request.site_text]

    with pytest.raises(GeminiProviderError):
        provider.generate(
            request,
            ProseConfig(model=DEFAULT_GEMINI_MODEL, output_budget=700),
        )

    for event in recording_sink.events:
        rendered_fields = str(event.fields)
        assert _SYSTEM_INSTRUCTION not in rendered_fields
        assert _SYSTEM_INSTRUCTION not in str(event.detail)
        for text in source_texts:
            assert text not in rendered_fields
            assert text not in str(event.detail)
