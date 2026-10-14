from admaker.graph import build_graph, default_runners


def test_default_runners_bind_account_to_all_ai_calls(monkeypatch):
    accounts = []

    def builder(spec, *, account_id=None):
        accounts.append((spec.name, account_id))
        return lambda *args: "ok"

    monkeypatch.setattr("admaker.agents.spec.build_agent_runner", builder)
    monkeypatch.setattr("admaker.agents.spec.build_vision_runner", builder)
    runners = default_runners(account_id="owner")
    assert all(runner("text", "image") == "ok" for runner in runners.values())
    assert accounts == [("intake", "owner"), ("qa_content", "owner"), ("style_planner", "owner")]


def test_graph_forwards_bound_account(monkeypatch, tmp_path):
    from admaker.config import AdMakerConfig

    seen = []

    def runners(config, *, account_id=None):
        seen.append(account_id)
        return {name: lambda *args: "{}" for name in ("intake", "qa_content", "style_planner")}

    monkeypatch.setattr("admaker.graph.default_runners", runners)
    build_graph(account_id="owner", config=AdMakerConfig(asset_root=str(tmp_path)))
    assert seen == ["owner"]
