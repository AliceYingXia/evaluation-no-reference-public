"""Reusable clients for Workato Agentic API and Genie headless chat."""

import os
from typing import Any, Dict

import requests

AGENTIC_BASE_URL = os.environ.get(
    "WORKATO_AGENTIC_BASE_URL",
    "https://workato.example.internal/api/agentic",
)
GENIE_BASE_URL = os.environ.get(
    "WORKATO_GENIE_BASE_URL",
    "https://genie-api.example.internal/api/v1",
)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set (check .env is loaded)")
    return value


def _airo_token() -> str:
    token = os.environ.get("AIRO_API")
    if not token:
        raise RuntimeError("AIRO_API is not set (check .env is loaded)")
    return token


def _agentic_base_url() -> str:
    return os.environ.get("WORKATO_AGENTIC_BASE_URL", AGENTIC_BASE_URL)


def _genie_base_url() -> str:
    return os.environ.get("WORKATO_GENIE_BASE_URL", GENIE_BASE_URL)


def _request(base_url: str, method: str, path: str, headers: Dict[str, str], **kwargs) -> requests.Response:
    url = f"{base_url}{path}"
    timeout = kwargs.pop("timeout", 60)
    extra_headers = kwargs.pop("headers", {})
    headers.update(extra_headers)
    resp = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


def request(method: str, path: str, **kwargs) -> requests.Response:
    """Call a Workato Agentic API path, e.g. request('GET', '/genies')."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {_airo_token()}"
    headers.setdefault("Accept", "application/json")
    return _request(_agentic_base_url(), method, path, headers, **kwargs)


def get(path: str, **kwargs) -> requests.Response:
    return request("GET", path, **kwargs)


def post(path: str, **kwargs) -> requests.Response:
    return request("POST", path, **kwargs)


def delete(path: str, **kwargs) -> requests.Response:
    return request("DELETE", path, **kwargs)


def list_genies() -> Any:
    return get("/genies").json()


def get_genie(genie_id: str) -> Any:
    return get(f"/genies/{genie_id}").json()


def list_genie_clients() -> Any:
    return get("/genies/clients").json()


def create_genie_client(client_name: str) -> Any:
    return post(
        "/genies/clients",
        json={"client_name": client_name, "auth": {"type": "api_key"}},
    ).json()


def attach_genie_client(genie_id: str, genie_client_id: str) -> Any:
    return post(
        f"/genies/{genie_id}/clients",
        json={"genie_client_id": genie_client_id},
    ).json()


def headless_request(method: str, path: str, **kwargs) -> requests.Response:
    """Call the Genie headless chat API using WORKATO_GENIE_API_KEY."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {_env('WORKATO_GENIE_API_KEY')}"
    headers["X-IDP-User-Id"] = _env("WORKATO_IDP_USER_ID")
    headers.setdefault("Accept", "application/json")
    return _request(_genie_base_url(), method, path, headers, **kwargs)


def create_conversation(genie_id: str | None = None) -> Any:
    genie_id = genie_id or _env("WORKATO_GENIE_ID")
    return headless_request("POST", f"/genies/{genie_id}/chat/conversations").json()


def send_message(
    conversation_id: str,
    message: str,
    genie_id: str | None = None,
    stream: bool = True,
) -> requests.Response:
    genie_id = genie_id or _env("WORKATO_GENIE_ID")
    return headless_request(
        "POST",
        f"/genies/{genie_id}/chat/conversations/{conversation_id}/messages",
        json={"message": message, "stream": stream},
        stream=stream,
        timeout=120,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    print(list_genies())
