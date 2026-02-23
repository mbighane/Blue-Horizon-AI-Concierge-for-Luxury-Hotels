import importlib.util
import sys
import types
import uuid
from pathlib import Path


class _SessionState(dict):
    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        if name in self:
            del self[name]
        else:
            raise AttributeError(name)


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Column:
    def __init__(self, submit_send=False, submit_clear=False):
        self._submit_send = submit_send
        self._submit_clear = submit_clear

    def button(self, *args, **kwargs):
        return False

    def form_submit_button(self, label, **kwargs):
        if label == "Send":
            return self._submit_send
        if label == "Clear":
            return self._submit_clear
        return False


class _FakeStreamlitModule(types.ModuleType):
    def __init__(
        self,
        pending_query: str,
        *,
        submit_send: bool = True,
        submit_clear: bool = False,
        clear_history_button: bool = False,
    ):
        super().__init__("streamlit")
        self.session_state = _SessionState()
        self.sidebar = _Context()
        self._pending_query = pending_query
        self._submit_send = submit_send
        self._submit_clear = submit_clear
        self._clear_history_button = clear_history_button

    def set_page_config(self, **kwargs):
        return None

    def markdown(self, *args, **kwargs):
        return None

    def divider(self):
        return None

    def caption(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def rerun(self):
        return None

    def button(self, *args, **kwargs):
        if args and args[0] == "Clear History":
            return self._clear_history_button
        return False

    def expander(self, *args, **kwargs):
        return _Context()

    def columns(self, spec):
        if isinstance(spec, int):
            return [_Column() for _ in range(spec)]
        if spec == [5, 1]:
            return [
                _Column(submit_send=self._submit_send, submit_clear=False),
                _Column(submit_send=False, submit_clear=self._submit_clear),
            ]
        return [_Column() for _ in range(len(spec))]

    def form(self, *args, **kwargs):
        return _Context()

    def text_input(self, *args, **kwargs):
        return self._pending_query

    def spinner(self, *args, **kwargs):
        return _Context()


def _import_streamlit_page(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_streamlit_submission_sends_query_to_concierge(monkeypatch):
    query = "What is the cancellation policy?"
    fake_st = _FakeStreamlitModule(pending_query=query)
    post_calls = []

    class _Resp:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    def fake_get(url, timeout=2):
        return _Resp(200, payload={"status": "ok"})

    def fake_post(url, json=None, timeout=0):
        post_calls.append({"url": url, "json": json, "timeout": timeout})
        if url.endswith("/concierge/ask"):
            return _Resp(200, payload={"response": "Mock concierge reply"})
        return _Resp(204)

    requests_stub = types.SimpleNamespace(
        get=fake_get,
        post=fake_post,
        exceptions=types.SimpleNamespace(ConnectionError=Exception, Timeout=Exception),
    )

    page_path = Path(__file__).resolve().parents[2] / "frontend" / "pages" / "streamlit_app.py"
    temp_module_name = f"test_streamlit_app_{uuid.uuid4().hex}"

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setitem(sys.modules, "requests", requests_stub)

    try:
        module = _import_streamlit_page(temp_module_name, page_path)
    finally:
        sys.modules.pop(temp_module_name, None)

    assert module is not None
    concierge_calls = [c for c in post_calls if c["url"].endswith("/concierge/ask")]
    assert len(concierge_calls) == 1

    payload = concierge_calls[0]["json"]
    assert payload["message"] == query
    assert isinstance(payload["user_id"], str) and payload["user_id"].strip()


def test_streamlit_form_clear_calls_clear_endpoint_and_resets_history(monkeypatch):
    fake_st = _FakeStreamlitModule(
        pending_query="",
        submit_send=False,
        submit_clear=True,
    )
    fake_st.session_state["user_id"] = "user-abc"
    fake_st.session_state["concierge_history"] = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    post_calls = []

    class _Resp:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    def fake_get(url, timeout=2):
        return _Resp(200, payload={"status": "ok"})

    def fake_post(url, json=None, timeout=0):
        post_calls.append({"url": url, "json": json, "timeout": timeout})
        return _Resp(204)

    requests_stub = types.SimpleNamespace(
        get=fake_get,
        post=fake_post,
        exceptions=types.SimpleNamespace(ConnectionError=Exception, Timeout=Exception),
    )

    page_path = Path(__file__).resolve().parents[2] / "frontend" / "pages" / "streamlit_app.py"
    temp_module_name = f"test_streamlit_app_{uuid.uuid4().hex}"

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setitem(sys.modules, "requests", requests_stub)

    try:
        module = _import_streamlit_page(temp_module_name, page_path)
    finally:
        sys.modules.pop(temp_module_name, None)

    assert module is not None
    clear_calls = [c for c in post_calls if "/concierge/clear/" in c["url"]]
    assert len(clear_calls) == 1
    assert clear_calls[0]["url"].endswith("/concierge/clear/user-abc")
    assert fake_st.session_state["concierge_history"] == []
