from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from temvera.hindsight_adapter import HindsightSystem, HindsightUnavailable
from temvera.nl_workload import WorkloadTurn
from temvera.stdio_system import StdioSystem, WorkerUnavailable
from temvera.worker_errors import FatalWorkerError, check_fatal, redact, summarize

_WORKER = """
import json, sys
print(json.dumps({"ok": True, "ready": True}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request["op"] == "stop":
        print(json.dumps({"ok": True}), flush=True)
        break
    if request["op"] == "die":
        sys.stderr.write("boom: worker crashed\\n")
        sys.stderr.flush()
        sys.exit(3)
    print(json.dumps({"ok": False, "error": request.get("text", "")}), flush=True)
"""


def _turn(text: str) -> WorkloadTurn:
    from datetime import datetime, timezone

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return WorkloadTurn(event_id="e", recorded_at=now, text=text)


@pytest.fixture
def stdio(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text(_WORKER)
    system = StdioSystem(python=sys.executable, worker=str(script))
    yield system
    system.close()


def test_redact_masks_api_keys():
    assert "abcd" not in redact("Incorrect API key provided: sk-proj-abcd1234")
    assert "sk-<redacted>" in redact("key sk-proj-***...-PMA")


def test_auth_failures_are_fatal_and_others_are_not():
    with pytest.raises(FatalWorkerError):
        check_fatal("AuthenticationError: Error code: 401")
    check_fatal("RateLimitError: slow down")


def test_summarize_ranks_by_count_and_redacts():
    summary = summarize(["b", "a", "b", "token sk-proj-secretvalue"])
    assert summary[0] == {"message": "b", "count": 2}
    assert all("secretvalue" not in item["message"] for item in summary)


def test_stdio_worker_errors_are_kept_verbatim(stdio):
    stdio.ingest(_turn("ValueError: no data"))
    assert stdio.worker_errors == 1
    assert stdio.error_messages == ["ValueError: no data"]


def test_stdio_auth_error_stops_the_run(stdio):
    with pytest.raises(FatalWorkerError):
        stdio.ingest(_turn("AuthenticationError: Incorrect API key provided"))


def test_stdio_worker_death_reports_its_stderr(stdio):
    with pytest.raises(WorkerUnavailable, match="boom: worker crashed"):
        stdio._call({"op": "die"})


class _Daemon(BaseHTTPRequestHandler):
    body = b""

    def do_POST(self):  # noqa: N802
        self.send_response(500)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        return None


def _serve(body: bytes):
    handler = type("Handler", (_Daemon,), {"body": body})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_hindsight_records_server_error_bodies():
    server = _serve(json.dumps({"detail": "Fact extraction failed: timeout"}).encode())
    try:
        system = HindsightSystem(base_url=f"http://127.0.0.1:{server.server_port}")
        system.ingest(_turn("x"))
        assert system.worker_errors == 1
        assert "Fact extraction failed" in system.error_messages[0]
    finally:
        server.shutdown()


def test_hindsight_upstream_auth_failure_stops_the_run():
    body = b'{"detail": "AuthenticationError: Error code: 401 - invalid_api_key"}'
    server = _serve(body)
    try:
        system = HindsightSystem(base_url=f"http://127.0.0.1:{server.server_port}")
        with pytest.raises(FatalWorkerError):
            system.ingest(_turn("x"))
    finally:
        server.shutdown()


def test_hindsight_unreachable_daemon_is_not_an_empty_answer():
    server = _serve(b"")
    port = server.server_port
    server.shutdown()
    server.server_close()
    system = HindsightSystem(base_url=f"http://127.0.0.1:{port}", timeout=2)
    with pytest.raises(HindsightUnavailable):
        system.ingest(_turn("x"))
