import sys
from types import SimpleNamespace

import pytest

from admaker.agents.spec import AgentSpec, build_agent_runner, build_vision_runner


def test_gemini_runners_recheck_consent_before_each_transfer(monkeypatch):
    calls = []
    llm = SimpleNamespace(invoke=lambda messages: calls.append(messages) or SimpleNamespace(content="ok"))
    monkeypatch.setitem(sys.modules, "langchain_google_genai", SimpleNamespace(ChatGoogleGenerativeAI=lambda **kwargs: llm))
    allowed = False

    def permission(account_id):
        assert account_id == "account"
        if not allowed:
            raise PermissionError("consent required")

    monkeypatch.setattr("admaker.consent.require_ai_consent", permission)
    spec = AgentSpec("test", "offline", "system")
    for builder, args in ((build_agent_runner, ("private prompt",)),
                          (build_vision_runner, ("private prompt", "https://private-image.test"))):
        with pytest.raises(PermissionError):
            builder(spec)(*args)
        runner = builder(spec, account_id="account")
        with pytest.raises(PermissionError):
            runner(*args)
        assert not calls
        allowed = True
        assert runner(*args) == "ok"
        assert len(calls) == 1
        allowed = False
        with pytest.raises(PermissionError):
            runner(*args)
        assert len(calls) == 1
        calls.clear()
