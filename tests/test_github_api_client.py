from __future__ import annotations

import unittest
from unittest.mock import patch

from gateway.github_api import GitHubApiClient, GitHubAppCredentials


class GitHubApiClientAuthTests(unittest.TestCase):
    def test_static_token_passthrough(self) -> None:
        client = GitHubApiClient(token="static-token")
        self.assertEqual(client._get_installation_token(), "static-token")

    def test_installation_token_is_cached_until_near_expiry(self) -> None:
        now = 1_700_000_000.0
        client = GitHubApiClient(
            app_credentials=GitHubAppCredentials(
                app_id="123",
                installation_id="456",
                private_key_pem="pem",
            ),
            clock=lambda: now,
        )

        calls: list[str] = []

        def fake_mint() -> tuple[str, float]:
            calls.append("mint")
            return ("install-token", now + 600)

        client._mint_installation_token = fake_mint  # type: ignore[method-assign]

        self.assertEqual(client._get_installation_token(), "install-token")
        self.assertEqual(client._get_installation_token(), "install-token")
        self.assertEqual(calls, ["mint"])

    def test_installation_token_refreshes_when_expiring_soon(self) -> None:
        current_time = 1_700_000_000.0
        client = GitHubApiClient(
            app_credentials=GitHubAppCredentials(
                app_id="123",
                installation_id="456",
                private_key_pem="pem",
            ),
            clock=lambda: current_time,
        )

        responses = iter(
            [
                ("first-token", current_time + 120),
                ("second-token", current_time + 600),
            ]
        )
        client._mint_installation_token = lambda: next(responses)  # type: ignore[method-assign]

        self.assertEqual(client._get_installation_token(), "first-token")
        current_time += 61
        self.assertEqual(client._get_installation_token(), "second-token")

    def test_build_app_jwt_uses_expected_claims(self) -> None:
        client = GitHubApiClient(
            app_credentials=GitHubAppCredentials(
                app_id="123",
                installation_id="456",
                private_key_pem="pem",
            ),
            clock=lambda: 1_700_000_000.0,
        )

        with patch("gateway.github_api_client.jwt.encode", return_value="signed-jwt") as encode:
            token = client._build_app_jwt()

        self.assertEqual(token, "signed-jwt")
        claims = encode.call_args.args[0]
        self.assertEqual(claims["iss"], "123")
        self.assertEqual(claims["iat"], 1_699_999_940)
        self.assertEqual(claims["exp"], 1_700_000_540)


if __name__ == "__main__":
    unittest.main()
