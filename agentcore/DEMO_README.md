# AgentCore – local demo without Azure

This setup runs the platform entirely on one Windows machine with **no Azure
services**. It is meant for client demos; production deployments keep using
Key Vault, Entra ID SSO, Azure Managed Redis and Blob storage.

## Start / stop

```powershell
cd <repo>\agentcore
.\start-demo.ps1        # starts PostgreSQL, Redis, backend, frontend and opens the browser
.\stop-demo.ps1         # stops everything
```

| Component  | URL / location                                  |
|------------|-------------------------------------------------|
| UI         | http://localhost:3000                            |
| API docs   | http://127.0.0.1:7860/docs                       |
| Model service | http://127.0.0.1:8001/health (OpenAI-compatible LLM/embeddings proxy) |
| PostgreSQL | 127.0.0.1:5433 (data in `.local\pgdata`)         |
| Redis      | 127.0.0.1:6379 (no persistence)                  |

Login with the local admin from `.env`:

```
AGENTCORE_SUPERUSER=admin@demo.local
AGENTCORE_SUPERUSER_PASSWORD=Demo@12345
```

The user is created (or its password/role refreshed) every time the backend
starts, so changing the values in `.env` and restarting is enough to rotate
the demo credentials.

## What was changed to make Azure optional

Configuration (`.env.demo` → `.env`):

- `AGENTCORE_KEY_VAULT_URL` empty → Key Vault loading is skipped; secrets come
  from `.env`.
- `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` empty → the frontend starts without
  MSAL and the login page shows username/password only. The `/api/azure/sso`
  endpoint still exists but is unused.
- `REDIS_ENTRA_SCOPE` empty → the Redis client connects without Entra ID
  tokens (optional `REDIS_PASSWORD`). `REDIS_CLUSTER_ENABLED=false` for a
  standalone server.
- `STORAGE_TYPE=local` → uploaded files are stored on disk instead of Blob
  storage.
- `LTM_ENABLED=false` → long-term-memory jobs (Pinecone/Neo4j) are off.

Code (all backwards compatible; Azure paths are untouched when configured):

- `services/cache/redis_client.py`, `services/cache/service.py` – Entra
  credential provider is optional; plain Redis auth is supported.
- `services/auth/permissions.py` – permissions fall back to the database when
  the Redis cache is unavailable, so login never depends on Redis.
- `services/utils.py` – `ensure_local_superuser()` bootstraps a root user from
  `AGENTCORE_SUPERUSER` / `AGENTCORE_SUPERUSER_PASSWORD`.
- `src/frontend/src/index.tsx`, `authConfig.js`, `pages/LoginPage` – MSAL is
  only initialised when SSO is configured; the SSO button is hidden otherwise.

Fresh-database fixes (unrelated to Azure, but required to boot on an empty
PostgreSQL; production databases are unaffected):

- `services/database/service.py` – the tables created from the SQLModel
  metadata are now committed. SQLAlchemy 2.x rolled them back on connection
  close, so Alembic ran against an empty schema and failed.
- `alembic/versions/fdf483318169_merge_all_alembic_heads.py` – removed the
  dangling revision `n8m7l6k5j4h3` (no such migration file exists); Alembic
  could not even load the revision map.
- `services/utils.py` – `ensure_default_roles_and_permissions()` seeds the
  system roles/permissions from `ROLE_PERMISSIONS` when the `role` table is
  empty. On a fresh database Alembic is stamped to head (the history cannot be
  replayed from scratch), so the data-seeding migrations never run.
- `services/database/service.py` – tables are created with
  `metadata.create_all` so foreign keys declared with `use_alter=True` are
  emitted (per-table creation skipped them, leaving a permanent model/DB
  diff). The Alembic "auto-fix" loop that reacted to that diff by running
  downgrade/upgrade cycles on every start (dropping columns and their data)
  is now opt-in via `AGENTCORE_MIGRATION_AUTOFIX=true`.

## Re-enabling Azure

Fill the Azure variables back in (`AGENTCORE_KEY_VAULT_URL` and the
`AGENTCORE_KEY_VAULT_*_SECRET_NAME` names, `AZURE_CLIENT_ID`,
`AZURE_TENANT_ID`, `REDIS_ENTRA_SCOPE`, `STORAGE_TYPE=azure`, …) and remove
`AGENTCORE_SUPERUSER*`. No code changes are needed.

## Demo agent: Email-to-Quote Underwriting

`demo/underwriting/Email_to_Quote_Underwriting_Agent.json` is an importable
agent (Group Medical Insurance): broker email + PDF attachments → document
intelligence → field-level validation → underwriting decision → configurable
rating → quote PDF and broker email. Sample submissions (one clean, one with
deliberate discrepancies) are in `demo/underwriting/samples`. See
`demo/underwriting/README.md` for import and run steps.

## Model microservice

`start-demo.ps1` also starts `src/services/model-service` (port 8001). The
backend proxies the Model Registry and all chat/embedding calls to it. To run
agents against a real LLM, open the Model Registry in the UI and add a model
with its provider API key (OpenAI, Anthropic, Google, Groq, Azure OpenAI or any
OpenAI-compatible endpoint).

Without Azure Key Vault the service stores provider API keys Fernet-encrypted in
`src/services/model-service/.secrets/model-service-secrets.json`, using
`MODEL_SERVICE_ENCRYPTION_KEY` from `.env`. Keep that key stable, otherwise
stored provider keys can no longer be decrypted. Changes made for this:

- `app/utils/local_secrets.py` (new): Key-Vault-compatible local store.
- `app/services/registry_service.py`: uses the local store when
  `MODEL_SERVICE_KEY_VAULT_URL` is empty.
- `app/main.py`: Key Vault is no longer mandatory at startup.
- `app/services/redis_client.py`: plain Redis without Entra ID (rate limiter).

## Limitations in demo mode

- Only the model microservice is part of the demo stack. MCP, guardrails,
  Pinecone and graph-RAG services are not started, so features depending on
  them are unavailable.
- Features that are inherently Azure/Microsoft-bound (SharePoint, Outlook,
  Teams, Azure AI Search, Document Intelligence, Key Vault-backed variables)
  are visible in the UI but will not work.
- Password-reset e-mails need SMTP; `AGENTCORE_ALLOW_DIRECT_PASSWORD_RESET=true`
  lets users reset passwords directly from the UI instead.

## Manual setup (if the scripts cannot be used)

```powershell
# backend
cd src\backend
python -m pip install uv
python -m uv sync --frozen --no-dev
.\.venv\Scripts\python.exe -m uvicorn agentcore.main:create_app --factory --host 127.0.0.1 --port 7860 --loop asyncio:SelectorEventLoop
# (--loop asyncio:SelectorEventLoop is required on Windows: psycopg's async driver cannot run on the default Proactor loop)

# model-service (run from the repo root so it reads the shared .env)
cd src\services\model-service
python -m uv sync --frozen --no-dev
cd ..\..\..
.\src\services\model-service\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir src\services\model-service --host 127.0.0.1 --port 8001 --loop asyncio:SelectorEventLoop

# frontend
cd src\frontend
npm install
npm start
```
