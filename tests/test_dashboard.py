from __future__ import annotations

from agents.research_policy import MultiAgentResearchPolicy

import dashboard


class _Column:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _StreamlitStub:
    def __init__(self):
        self.messages = []

    def selectbox(self, *_args, **_kwargs):
        return "TEST"

    def columns(self, count):
        return tuple(_Column() for _ in range(count))

    def info(self, message):
        self.messages.append(message)

    def expander(self, *_args, **_kwargs):
        return _Column()

    def tabs(self, labels):
        return tuple(_Column() for _ in labels)

    def markdown(self, *_args, **_kwargs):
        pass

    def json(self, *_args, **_kwargs):
        pass


def test_agent_panel_handles_policy_decisions_without_agent_outputs(monkeypatch):
    monkeypatch.setattr(dashboard, "SYMBOLS", ("TEST",))
    monkeypatch.setattr(
        dashboard,
        "init_agents",
        lambda: {"TEST": MultiAgentResearchPolicy("TEST")},
    )
    results = dashboard.run_agent_pipeline({"TEST": {"price": 0.0}})
    streamlit = _StreamlitStub()
    monkeypatch.setattr(dashboard, "st", streamlit)

    assert results["TEST"][0] == {}
    assert results["TEST"][3].reasons == ("invalid_or_missing_price",)
    dashboard.render_agent_panel(results, {})

    assert streamlit.messages
    assert "invalid_or_missing_price" in streamlit.messages[0]
