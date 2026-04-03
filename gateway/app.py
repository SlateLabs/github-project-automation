"""HTTP entrypoint for the webhook gateway service."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from gateway.dedup import InMemoryDedupStore
from gateway.github_api import GitHubApiClient, load_repo_config, load_trust_policy
from gateway.service import GatewayService


def _json_log(fields: dict[str, Any]) -> None:
    print(json.dumps(fields, sort_keys=True), flush=True)


def build_service_from_env() -> GatewayService:
    webhook_secret = os.environ["GITHUB_WEBHOOK_SECRET"]
    github_token = os.environ["GITHUB_DISPATCH_TOKEN"]
    repo_config_path = os.environ.get("GPA_REPO_CONFIG_PATH", "config/repos.yml")
    trust_policy_path = os.environ.get("GPA_TRUST_POLICY_PATH", "config/trust-policy.yml")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    dedup_window_ms = int(os.environ.get("GPA_DEDUP_WINDOW_MS", "60000"))

    return GatewayService(
        webhook_secret=webhook_secret,
        github_client=GitHubApiClient(token=github_token, api_url=api_url),
        repo_config=load_repo_config(repo_config_path),
        trust_policy=load_trust_policy(trust_policy_path),
        dedup_store=InMemoryDedupStore(dedup_window_ms=dedup_window_ms),
        logger=_json_log,
    )


class GatewayApplication:
    def __init__(self, service: GatewayService) -> None:
        self.service = service

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
        if method == "GET" and path == "/healthz":
            return 200, {"ok": True}
        if method != "POST" or path != "/github/webhook":
            return 404, {"error": "not found"}

        result = self.service.handle_delivery(headers, body)
        return result.status_code, result.body


def create_handler(app: GatewayApplication):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._respond(*app.handle("GET", self.path, dict(self.headers.items()), b""))

        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            self._respond(*app.handle("POST", self.path, dict(self.headers.items()), body))

        def log_message(self, format: str, *args: object) -> None:
            return

        def _respond(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    service = build_service_from_env()
    app = GatewayApplication(service)
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), create_handler(app))
    _json_log({"event": "gateway-started", "port": port})
    server.serve_forever()


if __name__ == "__main__":
    main()

