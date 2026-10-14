import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from admaker.agents.spec import AgentSpec, build_agent_runner


def test_planner_validates_untrusted_output_without_retry(monkeypatch):
    calls = []
    response = {"video_prompt": "Slow orbit", "ad_copy": "Product", "captions": {"reels": "Explore"},
                "music_mood": "calm", "candidates": []}
    def model(**options):
        assert options["max_retries"] == 0 and options["timeout"] == 60
        def structured(schema, method):
            assert method == "json_schema"
            return SimpleNamespace(invoke=lambda messages: calls.append(messages) or response)
        return SimpleNamespace(with_structured_output=structured)
    monkeypatch.setitem(sys.modules, "langchain_google_genai", SimpleNamespace(ChatGoogleGenerativeAI=model))
    monkeypatch.setattr("admaker.consent.require_ai_consent", lambda account: None)
    runner = build_agent_runner(AgentSpec("style_planner", "gemini-fixture", "Creative plan"), account_id="fixture")
    assert json.loads(runner("Product details")) == response
    response["credits"] = 0
    with pytest.raises(ValidationError):
        runner("Product details")
    assert len(calls) == 2
    del response["credits"]
    response["video_prompt"] = "x" * 4001
    with pytest.raises(ValidationError):
        runner("Product details")
    assert len(calls) == 3
