import pytest

from backend.app.agents import concierge_agent


@pytest.fixture(autouse=True)
def _reset_concierge_state():
    concierge_agent._agent = None
    concierge_agent._deps = None
    concierge_agent._session_store.clear()
    yield
    concierge_agent._agent = None
    concierge_agent._deps = None
    concierge_agent._session_store.clear()


def test_get_concierge_agent_builds_singleton(monkeypatch):
    class FakeNL2SQL:
        pass

    class FakeBooking:
        pass

    fake_search = object()
    fake_agent = object()

    monkeypatch.setattr(concierge_agent, "get_search_service", lambda: fake_search)
    monkeypatch.setattr(concierge_agent, "NL2SQLService", FakeNL2SQL)
    monkeypatch.setattr(concierge_agent, "BookingService", FakeBooking)
    monkeypatch.setattr(concierge_agent, "_build_agent", lambda: fake_agent)

    agent_1, deps_1 = concierge_agent.get_concierge_agent()
    agent_2, deps_2 = concierge_agent.get_concierge_agent()

    assert agent_1 is fake_agent
    assert agent_2 is fake_agent
    assert deps_1 is deps_2
    assert isinstance(deps_1.nl2sql, FakeNL2SQL)
    assert isinstance(deps_1.booking, FakeBooking)
    assert deps_1.search is fake_search


def test_get_concierge_agent_search_unavailable(monkeypatch):
    class FakeNL2SQL:
        pass

    class FakeBooking:
        pass

    fake_agent = object()

    def _raise_search_error():
        raise RuntimeError("Redis unavailable")

    monkeypatch.setattr(concierge_agent, "get_search_service", _raise_search_error)
    monkeypatch.setattr(concierge_agent, "NL2SQLService", FakeNL2SQL)
    monkeypatch.setattr(concierge_agent, "BookingService", FakeBooking)
    monkeypatch.setattr(concierge_agent, "_build_agent", lambda: fake_agent)

    _, deps = concierge_agent.get_concierge_agent()

    assert isinstance(deps.nl2sql, FakeNL2SQL)
    assert isinstance(deps.booking, FakeBooking)
    assert deps.search is None


def test_clear_session_removes_only_target_user():
    concierge_agent._session_store["guest-1"] = ["m1"]
    concierge_agent._session_store["guest-2"] = ["m2"]

    concierge_agent.clear_session("guest-1")

    assert "guest-1" not in concierge_agent._session_store
    assert concierge_agent._session_store["guest-2"] == ["m2"]


@pytest.mark.asyncio
async def test_ask_concierge_initial_turn_uses_no_history(monkeypatch):
    run_calls = []
    fake_deps = object()

    class FakeResult:
        output = "Hello from concierge"

        def new_messages(self):
            return ["assistant-msg-1", "assistant-msg-2"]

    class FakeAgent:
        async def run(self, user_message, deps, message_history=None):
            run_calls.append((user_message, deps, message_history))
            return FakeResult()

    monkeypatch.setattr(
        concierge_agent,
        "get_concierge_agent",
        lambda: (FakeAgent(), fake_deps),
    )

    output = await concierge_agent.ask_concierge("Hi there", user_id="guest-a")

    assert output == "Hello from concierge"
    assert run_calls == [("Hi there", fake_deps, None)]
    assert concierge_agent._session_store["guest-a"] == ["assistant-msg-1", "assistant-msg-2"]


@pytest.mark.asyncio
async def test_ask_concierge_followup_appends_new_messages(monkeypatch):
    run_calls = []
    fake_deps = object()
    concierge_agent._session_store["guest-b"] = ["prior-msg"]

    class FakeResult:
        output = "Follow-up reply"

        def new_messages(self):
            return ["new-msg"]

    class FakeAgent:
        async def run(self, user_message, deps, message_history=None):
            run_calls.append((user_message, deps, message_history))
            return FakeResult()

    monkeypatch.setattr(
        concierge_agent,
        "get_concierge_agent",
        lambda: (FakeAgent(), fake_deps),
    )

    output = await concierge_agent.ask_concierge("Any pool timings?", user_id="guest-b")

    assert output == "Follow-up reply"
    assert run_calls == [
        ("Any pool timings?", fake_deps, ["prior-msg"]),
    ]
    assert concierge_agent._session_store["guest-b"] == ["prior-msg", "new-msg"]
