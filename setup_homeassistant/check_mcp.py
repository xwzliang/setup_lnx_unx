#!/usr/bin/env python3
"""Verify the Home Assistant MCP connection and list tools without calling them."""

import argparse
from contextlib import closing
from getpass import getpass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
import json
import os
import sys
from time import monotonic
from urllib.parse import urlsplit

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26")
TIMEOUT = 10
MAX_RESPONSE = 4 * 1024 * 1024


class CheckError(Exception):
    pass


def rpc_response(response, identifier):
    content_type = response.headers.get_content_type()
    if content_type == "application/json":
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise CheckError("MCP response exceeded the size limit.")
        return json.loads(body)
    if content_type != "text/event-stream":
        raise CheckError("Expected a JSON or event-stream response from MCP.")

    deadline = monotonic() + TIMEOUT
    remaining = MAX_RESPONSE
    event = []
    while remaining > 0 and monotonic() < deadline:
        line = response.readline(remaining + 1)
        if not line:
            break
        remaining -= len(line)
        if remaining < 0:
            break
        line = line.rstrip(b"\r\n")
        if line.startswith(b"data:"):
            event.append(line[5:].removeprefix(b" "))
        elif not line and event:
            message = json.loads(b"\n".join(event))
            if isinstance(message, dict) and message.get("id") == identifier:
                return message
            event.clear()
    raise CheckError("The MCP event stream ended without a matching response.")


class MCPCheck:
    def __init__(self, url, token):
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or not parsed.path
                or parsed.username is not None or parsed.fragment):
            raise CheckError("Use the HTTP or HTTPS MCP endpoint URL from Home Assistant.")
        self.connection = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        self.host = parsed.hostname
        self.port = parsed.port
        self.path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

    def send(self, method, params=None, identifier=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if identifier is not None:
            message["id"] = identifier
        try:
            with closing(self.connection(self.host, self.port, timeout=TIMEOUT)) as conn:
                conn.request("POST", self.path, json.dumps(message), self.headers)
                with conn.getresponse() as response:
                    if response.status != (202 if identifier is None else 200):
                        raise CheckError(f"{method} returned HTTP {response.status}.")
                    if identifier is None:
                        return None
                    if method == "initialize" and (session := response.getheader("MCP-Session-Id")):
                        if any(not 0x21 <= ord(char) <= 0x7E for char in session):
                            raise CheckError("MCP returned an invalid session ID.")
                        self.headers["MCP-Session-Id"] = session
                    reply = rpc_response(response, identifier)
        except (OSError, HTTPException, ValueError):
            raise CheckError(f"{method} failed to receive a valid MCP response.") from None
        if not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0" or reply.get("id") != identifier:
            raise CheckError(f"{method} returned a mismatched JSON-RPC response.")
        if "error" in reply:
            raise CheckError(f"{method} returned a JSON-RPC error.")
        if not isinstance(reply.get("result"), dict):
            raise CheckError(f"{method} did not return a result.")
        return reply["result"]

    def list_tools(self):
        try:
            result = self.send("initialize", {
                "protocolVersion": PROTOCOLS[0],
                "capabilities": {},
                "clientInfo": {"name": "home-assistant-health-check", "version": "1"},
            }, identifier=1)
            protocol = result.get("protocolVersion")
            if protocol not in PROTOCOLS:
                raise CheckError("MCP negotiated an unsupported protocol version.")
            self.headers["MCP-Protocol-Version"] = protocol
            self.send("notifications/initialized")

            count = 0
            cursor = None
            seen = set()
            while True:
                params = {"cursor": cursor} if cursor is not None else {}
                page = self.send("tools/list", params, identifier=len(seen) + 2)
                tools = page.get("tools")
                if not isinstance(tools, list) or any(
                        not isinstance(tool, dict) or not isinstance(tool.get("name"), str) for tool in tools):
                    raise CheckError("tools/list returned an invalid tool list.")
                count += len(tools)
                cursor = page.get("nextCursor")
                if cursor is None:
                    return protocol, count
                if not isinstance(cursor, str) or not cursor or cursor in seen:
                    raise CheckError("tools/list returned an invalid pagination cursor.")
                seen.add(cursor)
        finally:
            if "MCP-Session-Id" in self.headers:
                try:
                    with closing(self.connection(self.host, self.port, timeout=TIMEOUT)) as conn:
                        conn.request("DELETE", self.path, headers=self.headers)
                        conn.getresponse().close()
                except (OSError, HTTPException):
                    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Home Assistant MCP endpoint URL")
    parser.add_argument("--token-stdin", action="store_true", help="read an existing access token from stdin")
    args = parser.parse_args()
    token = sys.stdin.read().strip() if args.token_stdin else os.environ.get("HA_TOKEN", "").strip()
    if not token and not args.token_stdin and sys.stdin.isatty():
        token = getpass("Home Assistant access token: ").strip()
    if not token or not token.isascii() or any(char.isspace() for char in token):
        parser.error("Use HA_TOKEN, --token-stdin, or the interactive prompt to supply an access token.")
    try:
        protocol, count = MCPCheck(args.url, token).list_tools()
    except (CheckError, ValueError) as error:
        sys.exit(str(error) if isinstance(error, CheckError) else "Invalid MCP endpoint URL.")
    print(f"Home Assistant MCP is reachable. Protocol {protocol}, {count} tools listed.")


if __name__ == "__main__":
    main()
