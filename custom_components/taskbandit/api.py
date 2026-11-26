"""Small async client for the TaskBandit Home Assistant API."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from .const import (
    API_PATH,
    REQUEST_TIMEOUT,
    SCOPE_CHORES,
    SCOPE_PRESENCE,
    SCOPE_READ,
    SCOPE_ROUTINES,
)


class TaskBanditError(Exception):
    """Base error for TaskBandit API calls."""


class TaskBanditConnectionError(TaskBanditError):
    """The server could not be reached."""


class TaskBanditAuthError(TaskBanditError):
    """The token is missing, wrong or revoked (401)."""


class TaskBanditApiError(TaskBanditError):
    """The server answered with an error."""

    def __init__(self, status: int, code: str | None, message: str | None) -> None:
        super().__init__(message or code or f"HTTP {status}")
        self.status = status
        self.code = code


class TaskBanditScopeError(TaskBanditApiError):
    """The token lacks the scope this call needs (403 token_scope)."""

    def __init__(self, scope: str, message: str | None = None) -> None:
        super().__init__(403, "token_scope", message)
        self.scope = scope


class TaskBanditFeatureDisabledError(TaskBanditApiError):
    """A package feature is off (403 package_feature_disabled)."""


class TaskBanditPresenceDisabledError(TaskBanditApiError):
    """The household has presence turned off (409 presence_disabled)."""


def normalize_url(url: str, default_scheme: str = "https") -> str:
    """Return the server address without a trailing slash, with a scheme."""
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = f"{default_scheme}://{url}"
    if url.endswith(API_PATH):
        url = url[: -len(API_PATH)]
    return url


def _member(member_id: str | None) -> dict[str, str]:
    """The body naming who did something; empty when nobody is known."""
    return {"memberId": member_id} if member_id else {}


def _error_details(data: Any) -> tuple[str | None, str | None, str | None]:
    """Pull code, message and scope out of an error body."""
    if not isinstance(data, dict):
        return None, None, None
    code = data.get("code")
    message = data.get("message")
    error = data.get("error")
    if isinstance(error, dict):
        code = code or error.get("code")
        message = message or error.get("message")
    if isinstance(message, list):
        message = "; ".join(str(part) for part in message)
    scope = data.get("scope") or data.get("requiredScope")
    return (
        code if isinstance(code, str) else None,
        message if isinstance(message, str) else None,
        scope if isinstance(scope, str) else None,
    )


def _outcome(data: Any) -> str:
    if isinstance(data, dict) and isinstance(data.get("outcome"), str):
        return data["outcome"]
    return "unknown"


class TaskBanditClient:
    """Client for `<server>/api/integrations/home-assistant`."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session = session
        self.server_url = normalize_url(url)
        self._token = token

    async def _request(
        self, method: str, path: str, scope: str, payload: Any | None = None
    ) -> Any:
        url = f"{self.server_url}{API_PATH}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, url, json=payload, headers=headers
                ) as resp:
                    status = resp.status
                    text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TaskBanditConnectionError(
                f"Could not reach TaskBandit at {self.server_url}: {err}"
            ) from err

        data: Any = None
        if text:
            try:
                data = json.loads(text)
            except ValueError:
                data = None

        if status == 401:
            raise TaskBanditAuthError("TaskBandit rejected the token")
        if status >= 400:
            code, message, body_scope = _error_details(data)
            if status == 403 and code == "token_scope":
                raise TaskBanditScopeError(body_scope or scope, message)
            if status == 403 and code == "package_feature_disabled":
                raise TaskBanditFeatureDisabledError(status, code, message)
            if status == 409 and code == "presence_disabled":
                raise TaskBanditPresenceDisabledError(status, code, message)
            raise TaskBanditApiError(status, code, message)
        return data

    async def get_state(self) -> dict[str, Any]:
        """Return the household snapshot."""
        data = await self._request("GET", "/state", SCOPE_READ)
        if not isinstance(data, dict):
            raise TaskBanditApiError(200, None, "Unexpected response from /state")
        return data

    async def complete_chore(self, chore_id: str, member_id: str | None = None) -> str:
        """Complete a chore (done by `member_id` if it is unassigned) and return the outcome."""
        return _outcome(
            await self._request(
                "POST", f"/chores/{chore_id}/complete", SCOPE_CHORES, _member(member_id)
            )
        )

    async def start_chore(self, chore_id: str, member_id: str | None = None) -> str:
        """Start a chore (claimed by `member_id` if it is unassigned) and return the outcome."""
        return _outcome(
            await self._request(
                "POST", f"/chores/{chore_id}/start", SCOPE_CHORES, _member(member_id)
            )
        )

    async def assign_chore(self, chore_id: str, member_id: str) -> str:
        """Assign a chore to a member and return the outcome."""
        return _outcome(
            await self._request(
                "POST",
                f"/chores/{chore_id}/assign",
                SCOPE_CHORES,
                {"memberId": member_id},
            )
        )

    async def run_routine(self, routine_id: str, member_id: str | None = None) -> dict[str, Any]:
        """Run a routine (for `member_id`, if given) and return the run."""
        data = await self._request(
            "POST", f"/routines/{routine_id}/run", SCOPE_ROUTINES, _member(member_id)
        )
        return data if isinstance(data, dict) else {}

    async def set_presence(self, members: list[dict[str, Any]]) -> None:
        """Report who is home."""
        await self._request("PUT", "/presence", SCOPE_PRESENCE, {"members": members})

    async def set_webhook(self, url: str) -> dict[str, Any]:
        """Create or replace the household's Home Assistant webhook."""
        data = await self._request("PUT", "/webhook", SCOPE_READ, {"url": url})
        if not isinstance(data, dict) or not isinstance(data.get("secret"), str):
            raise TaskBanditApiError(200, None, "Unexpected response from PUT /webhook")
        return data

    async def delete_webhook(self) -> None:
        """Remove the household's Home Assistant webhook."""
        await self._request("DELETE", "/webhook", SCOPE_READ)
