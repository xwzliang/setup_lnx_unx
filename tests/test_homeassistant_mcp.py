"""Check the Home Assistant diagnostic against simulated MCP HTTP responses."""

from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup_homeassistant"))
try:
    import check_mcp
finally:
    sys.path.pop(0)


def response(payload=None, *, status=200, content_type="application/json", session=None):
    if content_type == "text/event-stream":
        body = b": keepalive\n\ndata: {\"method\":\"notifications/message\"}\n\n"
        body += b"event: message\ndata: " + json.dumps(payload).encode() + b"\n\n"
    else:
        body = json.dumps(payload).encode()
    stream = BytesIO(body)
    stream.status = status
    stream.headers = Message()
    stream.headers["Content-Type"] = content_type
    if session is not None:
        stream.headers["MCP-Session-Id"] = session
    stream.getheader = stream.headers.get
    return stream


class MCPCheckTests(unittest.TestCase):
    def setUp(self):
        self.check = check_mcp.MCPCheck("http://ha.test:8123/api/mcp", "test-token")
        self.calls = []
        self.init = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}

    def run_with(self, *responses):
        with patch.object(self.check, "connection") as connect:
            connect.return_value.getresponse.side_effect = responses
            connect.return_value.request.side_effect = (
                lambda method, path, body=None, headers=None: self.calls.append(
                    (method, path, json.loads(body) if body else None, headers.copy()))
            )
            return self.check.list_tools()

    def test_negotiates_session_and_lists_all_tools_from_json_and_sse(self):
        first = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "first"}], "nextCursor": "next"}}
        second = {"jsonrpc": "2.0", "id": 3, "result": {"tools": [{"name": "second"}]}}
        self.assertEqual(self.run_with(
            response(self.init, session="session"),
            response(status=202),
            response(first, content_type="text/event-stream"),
            response(second),
            response(status=204),
        ), ("2025-06-18", 2))
        self.assertEqual([body["method"] for method, _, body, _ in self.calls if method == "POST"],
                         ["initialize", "notifications/initialized", "tools/list", "tools/list"])
        self.assertNotIn("id", self.calls[1][2])
        self.assertEqual(self.calls[3][2]["params"], {"cursor": "next"})
        self.assertEqual(self.calls[-1][0], "DELETE")
        for _, path, _, headers in self.calls[1:]:
            self.assertEqual(path, "/api/mcp")
            self.assertEqual(headers["MCP-Session-Id"], "session")
            self.assertEqual(headers["MCP-Protocol-Version"], "2025-06-18")

    def test_rpc_error_fails_check_and_closes_the_session(self):
        error = {"jsonrpc": "2.0", "id": 2, "error": {"code": -32603, "message": "server error"}}
        with self.assertRaisesRegex(check_mcp.CheckError, "tools/list returned a JSON-RPC error"):
            self.run_with(response(self.init, session="session"), response(status=202),
                          response(error), response(status=204))
        self.assertEqual(self.calls[-1][0], "DELETE")


if __name__ == "__main__":
    unittest.main()
