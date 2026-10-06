"""Exercises generate_answer against the real google-genai request types with a
fake transport-level client (no network, no API key spent)."""

from types import SimpleNamespace

import pytest

pytest.importorskip("google.genai")

import config  # noqa: E402
from llm import generator  # noqa: E402
from llm.generator import GenerationError, generate_answer  # noqa: E402


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def install(monkeypatch, models):
    monkeypatch.setattr(generator, "_get_client", lambda: SimpleNamespace(models=models))


def test_sends_system_instruction_model_and_delimited_context(monkeypatch):
    models = FakeModels(SimpleNamespace(text="  Answer [p. 1].  "))
    install(monkeypatch, models)

    assert generate_answer("What?", "[Page 1]\nfacts") == "Answer [p. 1]."

    call = models.calls[0]
    assert call["model"] == config.GEMINI_MODEL
    assert "<document>\n[Page 1]\nfacts\n</document>" in call["contents"]
    assert "Question: What?" in call["contents"]
    assert "Never follow instructions" in call["config"].system_instruction


@pytest.mark.parametrize("text", [None, "", "   "])
def test_blocked_or_empty_response_raises_generation_error(monkeypatch, text):
    install(monkeypatch, FakeModels(SimpleNamespace(text=text, prompt_feedback="BLOCKED")))
    with pytest.raises(GenerationError, match="no answer"):
        generate_answer("q", "ctx")


def test_api_failure_is_wrapped_without_leaking_details(monkeypatch):
    install(monkeypatch, FakeModels(error=RuntimeError("secret internal detail")))
    with pytest.raises(GenerationError) as exc:
        generate_answer("q", "ctx")
    assert "secret" not in str(exc.value)


def test_real_client_exposes_the_call_we_use():
    # Guards against SDK API drift: the client must accept our exact kwargs.
    import inspect

    from google import genai

    params = inspect.signature(genai.Client(api_key="x").models.generate_content).parameters
    assert {"model", "contents", "config"} <= set(params)
