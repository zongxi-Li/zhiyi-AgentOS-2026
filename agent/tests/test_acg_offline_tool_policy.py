from app.execution.tool_calls import network_tools_enabled
from packs.legal.agents.statute import StatuteAgent


def test_legal_statute_agent_declares_web_capability_but_honors_offline_gate():
    assert set(StatuteAgent().profile.allowed_tools) == {
        "web_search",
        "knowledge_search",
        "current_datetime",
    }
    assert network_tools_enabled({"webSearchEnabled": False}) is False
