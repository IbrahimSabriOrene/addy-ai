"""Agent abstraction (Strategy pattern), copied from the orchestrator.

Every LLM node takes its behavior from an injected ``runner(prompt) -> str``
built from an ``AgentSpec`` (model, system prompt, effort, vision inputs) by
a factory. Adding or reassigning a model is a config change, not new
plumbing — and tests inject fake runners without calling the model SDK
or the network.

Vision note: intake and content-QA are vision calls. Real image inputs ride
in via ``build_vision_runner``; the fakes in tests are plain
``prompt -> str`` callables, so nodes stay agnostic to how frames reach the
model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

AgentRunner = Callable[[str], str]


def structured_agent(spec):
    from langchain_google_genai import ChatGoogleGenerativeAI
    from admaker.agents.schemas import RUNNER_SCHEMAS

    if not 1 <= spec.max_tokens <= 4096:
        raise ValueError("Agent token limit must be between 1 and 4096")
    llm = ChatGoogleGenerativeAI(model=spec.model, vertexai=False, max_output_tokens=spec.max_tokens,
                                temperature=0, timeout=60, max_retries=0)
    schema = RUNNER_SCHEMAS.get(spec.name)
    return (llm.with_structured_output(schema, method="json_schema") if schema else llm), schema


@dataclass(frozen=True)
class AgentSpec:
    name: str
    model: str
    system_prompt: str
    effort: str | None = None  # low | medium | high | xhigh | max
    max_tokens: int = 4096


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def build_agent_runner(spec: AgentSpec, *, account_id: str | None = None) -> AgentRunner:
    """Factory for a bounded Gemini text call; tests keep injecting fakes."""
    llm, schema = structured_agent(spec)

    def runner(prompt: str) -> str:
        from admaker.consent import require_ai_consent

        if account_id is None:
            raise PermissionError("Authenticated account is required for AI sharing")
        require_ai_consent(account_id)
        messages = [("system", spec.system_prompt), ("human", prompt)]
        result = llm.invoke(messages)
        return schema.model_validate(result).model_dump_json() if schema else _extract_text(result.content)

    return runner


def build_vision_runner(spec: AgentSpec, *, account_id: str | None = None) -> Callable[[str, str], str]:
    """Vision variant: ``runner(prompt, image_url) -> str``. Intake and
    content-QA use this. Wrapped down to a plain ``prompt -> str`` at the
    call site so node code never branches on vision vs. text."""
    llm, schema = structured_agent(spec)

    def runner(prompt: str, image_url: str) -> str:
        from admaker.consent import require_ai_consent

        if account_id is None:
            raise PermissionError("Authenticated account is required for AI sharing")
        require_ai_consent(account_id)
        human = {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
        messages = [("system", spec.system_prompt), human]
        result = llm.invoke(messages)
        return schema.model_validate(result).model_dump_json() if schema else _extract_text(result.content)

    return runner


def parse_json_verdict(text: str) -> dict:
    """Pull the first JSON object out of an agent reply.

    LLM gates (intake, QA) are prompted to answer with a JSON object; this
    tolerates surrounding prose and markdown fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = brace.group(0) if brace else None
    if candidate is None:
        raise ValueError(f"No JSON object found in agent reply: {text[:200]!r}")
    return json.loads(candidate)
