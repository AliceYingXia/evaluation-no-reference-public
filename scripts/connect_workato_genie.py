"""Create and attach a Workato Genie headless API client.

This saves the one-time client API key directly to .env and never prints it.
The default target is the non-production ITSM support Genie copy used by this
evaluation workspace. Override with WORKATO_GENIE_ID if needed.
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from dotenv import load_dotenv

import workato_client as workato

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

DEFAULT_GENIE_ID = "gin-XXXXXXXXXXXXXXXXXXXX"
DEFAULT_CLIENT_NAME = "evaluation-no-reference-codex"


def _items(payload: Any, key: str) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get(key, payload.get("data", []))
    else:
        value = payload
    return value if isinstance(value, list) else []


def _data(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def _quote_env(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=@+-]+", value):
        return value
    return json.dumps(value)


def _upsert_env(path: Path, updates: Dict[str, str]) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    out = []

    for line in lines:
        key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            out.append(f"{key}={_quote_env(updates[key])}")
            seen.add(key)
        else:
            out.append(line)

    missing = [key for key in updates if key not in seen]
    if missing:
        if out and out[-1] != "":
            out.append("")
        out.append("# Workato Genie headless API")
        for key in missing:
            out.append(f"{key}={_quote_env(updates[key])}")

    path.write_text("\n".join(out) + "\n")


def _find_genie(genies: Iterable[Dict[str, Any]], genie_id: str) -> Dict[str, Any]:
    for genie in genies:
        if genie.get("id") == genie_id:
            return genie
    raise RuntimeError(f"Genie {genie_id} was not found")


def _is_attached(clients: Iterable[Dict[str, Any]], client_id: str, genie_id: str) -> bool:
    for client in clients:
        if client.get("client_id") == client_id:
            return genie_id in client.get("genie_ids", [])
    return False


def _create_client(client_name: str) -> Dict[str, str]:
    created = _data(workato.create_genie_client(client_name))
    client_id = created.get("client_id") or created.get("id")
    api_key = created.get("api_key")
    if not client_id or not api_key:
        keys = ", ".join(sorted(created.keys()))
        raise RuntimeError(f"Client creation response was missing client_id/api_key; keys: {keys}")
    return {"client_id": client_id, "api_key": api_key}


def main() -> None:
    load_dotenv(ENV_PATH)

    parser = argparse.ArgumentParser()
    parser.add_argument("--genie-id", default=os.environ.get("WORKATO_GENIE_ID", DEFAULT_GENIE_ID))
    parser.add_argument("--client-name", default=os.environ.get("WORKATO_GENIE_CLIENT_NAME"))
    args = parser.parse_args()

    genie_id = args.genie_id
    client_name = args.client_name or f"{DEFAULT_CLIENT_NAME}-{datetime.now(timezone.utc):%Y%m%d}"

    genies = _items(workato.list_genies(), "genies")
    genie = _find_genie(genies, genie_id)
    print(f"Target genie: {genie.get('name')} ({genie_id}), state={genie.get('state')}")

    existing_client_id = os.environ.get("WORKATO_GENIE_CLIENT_ID")
    existing_api_key = os.environ.get("WORKATO_GENIE_API_KEY")
    clients = _items(workato.list_genie_clients(), "clients")

    if existing_client_id and existing_api_key:
        client_id = existing_client_id
        print(f"Using existing client from .env: {client_id}")
    else:
        client = _create_client(client_name)
        client_id = client["client_id"]
        _upsert_env(
            ENV_PATH,
            {
                "WORKATO_GENIE_ID": genie_id,
                "WORKATO_GENIE_CLIENT_ID": client_id,
                "WORKATO_GENIE_API_KEY": client["api_key"],
                "WORKATO_GENIE_BASE_URL": os.environ.get("WORKATO_GENIE_BASE_URL", workato.GENIE_BASE_URL),
            },
        )
        print(f"Created client {client_id}; saved WORKATO_GENIE_API_KEY to .env (redacted).")

    if _is_attached(clients, client_id, genie_id):
        print("Client is already attached to target genie.")
    else:
        workato.attach_genie_client(genie_id, client_id)
        print("Attached client to target genie.")

    if os.environ.get("WORKATO_IDP_USER_ID"):
        print("WORKATO_IDP_USER_ID is set; headless chat can create conversations.")
    else:
        print(
            "Next required setting: add WORKATO_IDP_USER_ID for a Workato Identity end user "
            "(not an email, not a workspace collaborator ID). Find one via "
            "GET /api/agentic/genies/:id/conversations -> started_by.user_id on a "
            "conversation with app_type=headless_api. See WORKATO_API_SETUP.md."
        )


if __name__ == "__main__":
    main()
