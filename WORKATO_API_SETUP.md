# Connecting to Workato (AIRO_API)

How to authenticate against Workato's Agentic API and, from there, chat with a
genie. Based on `docs.workato.com/en/workato-api/agent-studio` and
`docs.workato.com/en/agentic/agent-studio/chat-interface/headless-api`, plus
what we confirmed by hand on 2026-09-18.

## 1. Management API (Agentic API)

- **Base URL:** `https://workato.example.internal/api/agentic` — this is our
  workspace's data center. (`www.workato.com` and the regional
  `app.*.workato.com` hosts all returned `401 Token invalid` for this token —
  don't reuse those.)
- **Auth header:** `Authorization: Bearer <AIRO_API>` (token lives in `.env`,
  which is gitignored — never commit it).
- **Client helper:** [scripts/workato_client.py](scripts/workato_client.py)
  wraps the Agentic API plus the headless Genie chat API.

Useful endpoints:

| Purpose | Method + path |
|---|---|
| List genies | `GET /genies` |
| Get one genie | `GET /genies/:id` |
| List genie clients (workspace-wide) | `GET /genies/clients` |
| Create a genie client | `POST /genies/clients` |
| Attach a client to a genie | `POST /genies/:id/clients` |
| Detach a client | `DELETE /genies/:id/clients/:client_id` |
| Regenerate a client's key | `POST /genies/clients/:client_id/regenerate` |

Creating a client:

```json
POST /genies/clients
{ "client_name": "my-test-client", "auth": { "type": "api_key" } }
```

The response includes `"api_key"` — **this is shown only once**, at creation
(or regeneration). Save it immediately; there's no way to fetch it again
later.

Attaching a client to a genie:

```json
POST /genies/:genie_id/clients
{ "genie_client_id": "gincl-..." }
```

⚠️ Before creating a new client for a genie, check
`GET /genies/clients` and filter by `genie_ids` to see if one is already
attached. Regenerating an existing client's key invalidates it for whatever
is currently using it — prefer creating a new client instead of regenerating
someone else's.

### Local setup in this repo

Run:

```bash
python3 scripts/connect_workato_genie.py
```

By default this targets the non-production `ITSM support Genie_v2 copy`
(`gin-XXXXXXXXXXXXXXXXXXXX`), creates a fresh API-key client, immediately saves
the one-time key into `.env`, and attaches the client to the genie.

Current local connection, created on 2026-09-18:

- `WORKATO_GENIE_ID=gin-XXXXXXXXXXXXXXXXXXXX`
- `WORKATO_GENIE_CLIENT_ID=gincl-XXXXXXXXXXXXXXXXXXXX`
- `WORKATO_GENIE_API_KEY=<saved in .env only; never print or commit>`
- `WORKATO_GENIE_BASE_URL=https://genie-api.example.internal/api/v1`
- `WORKATO_IDP_USER_ID=<saved in .env; headless test identity, see §2>`

Override the target with `--genie-id` or `WORKATO_GENIE_ID` only after
confirming the genie is safe to message.

## 2. Chatting with a genie (Headless API)

Separate host and API version — **not** `/api/agentic`:

- **Base URL:** `https://genie-api.example.internal/api/v1`
- **Auth headers (API-key method):**
  - `Authorization: Bearer <genie_client_api_key>` (from step 1, not `AIRO_API`)
  - `X-IDP-User-Id: <idp_user_id>`

| Purpose | Method + path |
|---|---|
| Create a conversation | `POST /genies/:genie_id/chat/conversations` |
| Send a message | `POST /genies/:genie_id/chat/conversations/:conversation_id/messages` — body `{ "message": "...", "stream": true }`, response is a Server-Sent Events stream (`processing.started`, `agent.message`, `processing.finished`; the reply text is in the `message` field of `agent.message` data) |
| List conversations (Agentic API) | `GET /api/agentic/genies/:genie_id/conversations` |

### Quick start: say hello end-to-end

Everything is already configured in `.env` (`WORKATO_GENIE_ID`,
`WORKATO_GENIE_CLIENT_ID`, `WORKATO_GENIE_API_KEY`, `WORKATO_GENIE_BASE_URL`,
`WORKATO_IDP_USER_ID`). Minimal working example:

```python
import json, os, sys, requests
sys.path.insert(0, "scripts")
from dotenv import load_dotenv
load_dotenv(".env", override=True)
import workato_client as w

genie = os.environ["WORKATO_GENIE_ID"]
base = os.environ["WORKATO_GENIE_BASE_URL"]
H = {
    "Authorization": f"Bearer {os.environ['WORKATO_GENIE_API_KEY']}",
    "X-IDP-User-Id": os.environ["WORKATO_IDP_USER_ID"],
}

cid = w.create_conversation()["result"]["conversation_id"]
r = requests.post(
    f"{base}/genies/{genie}/chat/conversations/{cid}/messages",
    headers={**H, "Content-Type": "application/json",
             "Accept": "text/event-stream"},
    json={"message": "hello", "stream": True},
    stream=True, timeout=120,
)
for line in r.iter_lines(decode_unicode=True):
    if line and line.startswith("data:"):
        ev = json.loads(line[5:].strip())
        if ev.get("type") == "agent.message":
            print("genie:", ev["message"])
```

Expected reply (2026-09-19): "Hello TestUser! I can help with IT
troubleshooting or application access requests." — the genie greets "TestUser"
because `WORKATO_IDP_USER_ID` asserts the `headless.tester@example.com`
test identity (see below).

### Resolved (2026-09-19): `user_nonactive_or_missing`

`X-IDP-User-Id` must be a user already provisioned in Workato Identity for
this environment ("End users provisioned in Workato Identity through IAM API
or the Workato UI" — per the Headless API docs). Note this header is
documented on the **Headless API** page
(`docs.workato.com/en/agentic/agent-studio/chat-interface/headless-api#authentication`),
not on the Agent Studio management API page.

Gotchas:

- The header expects the opaque Workato Identity **user ID**, not an email —
  `user@example.com` was rejected with `user_nonactive_or_missing`.
- A workspace collaborator's user ID (from test-mode conversations) is also
  rejected: collaborator identities and Identity **end users** are separate
  pools. Only end users (Workspace admin → End users) work.
- Valid end-user IDs can be discovered read-only via
  `GET /api/agentic/genies/:genie_id/conversations` — look at
  `started_by.user_id` on conversations where `app_type` is `headless_api`.
  Do not brute-force guess IDs against the live auth endpoint.

Current working value (saved in `.env`): `WORKATO_IDP_USER_ID` = the dedicated
headless test identity `headless.tester@example.com`, discovered from an
existing headless conversation on this genie. Verified end-to-end
2026-09-19: create conversation + streamed message round-trip both succeed.

## Gotchas learned the hard way

- `https://workato.example.internal/airo` and `https://workato.example.internal/` are
  the **web UI**, not API endpoints — they return login-page HTML, not JSON,
  regardless of the auth header.
- Some genies in this workspace are live/production (e.g. "BT Genie" /
  `gin-AXxGpPnx-pR9A8w-B6`, `state: active`) and handle real IT tickets and
  access requests via Firefighter/Jira. Confirm before sending messages to an
  active production genie, and prefer genies with no existing client attached
  when creating test credentials, so you don't disturb another integration's
  setup.
