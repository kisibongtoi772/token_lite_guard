# token_lite_guard

A lightweight, local AI Gateway that enforces token budgets for AI agents and development tools.

It acts as a transparent reverse proxy between your AI tools (Cursor, Continue, AutoGPT, LangChain agents, etc.) and LLM providers (OpenAI, Anthropic, Google, and others). Each incoming request is authenticated against a virtual API key, checked against its configured token budget, forwarded to the real provider, and logged — all in a single process with no external dependencies.

---

## Contents

- [Features](#features)
- [Supported Providers](#supported-providers)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Server](#running-the-server)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Dashboard](#dashboard)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Budget enforcement** — Hard stop (HTTP 429) when a virtual key's token budget is exhausted
- **Virtual API keys** — Issue multiple `tlg-` prefixed keys, each with its own budget and provider assignment
- **Multi-provider support** — 11 built-in providers; add any OpenAI-compatible endpoint as a custom provider
- **Streaming support** — Full SSE streaming passthrough with concurrent token counting
- **Cost estimation** — USD cost estimates based on a built-in pricing table for 40+ models
- **Management dashboard** — Web UI for key management, usage charts, provider status, and activity logs
- **Zero external dependencies** — SQLite only; no Docker, Redis, or PostgreSQL required
- **Auto-detection** — Provider inferred from model name when not specified explicitly

---

## Supported Providers

| Provider | Identifier | Auth Method | Notes |
|---|---|---|---|
| OpenAI | `openai` | Bearer token | gpt-4o, o1, o3, gpt-3.5-turbo |
| Anthropic | `anthropic` | x-api-key | claude-3-5-sonnet, claude-3-opus |
| Google Gemini | `google` | Bearer token | gemini-1.5-pro, gemini-2.0-flash |
| Mistral AI | `mistral` | Bearer token | mistral-large, codestral |
| Groq | `groq` | Bearer token | llama-3.3-70b, gemma2-9b |
| Together AI | `together` | Bearer token | Open model hosting |
| DeepSeek | `deepseek` | Bearer token | deepseek-chat, deepseek-reasoner |
| Cohere | `cohere` | Bearer token | command-r-plus, command-r |
| Azure OpenAI | `azure` | api-key header | Requires endpoint + API version |
| Ollama | `ollama` | None | Local inference, no key required |
| LM Studio | `lmstudio` | None | Local server, no key required |
| **Custom** | any slug | Configurable | Any OpenAI-compatible endpoint |

---

## Requirements

- Python 3.10 or later
- pip

No Docker, Redis, PostgreSQL, or Node.js required.

---

## Installation

```bash
git clone https://github.com/kisibongtoi772/token_lite_guard
cd token_lite_guard
pip3 install -e .
```

---

## Configuration

Copy the template and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` and configure at minimum one provider:

```ini
# Server settings
PORT=8000

# Add your real API keys — leave others blank
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...

# Default token budget for new virtual keys (0 = unlimited)
DEFAULT_BUDGET_TOKENS=100000
```

A full reference of all available environment variables is provided in [`.env.example`](.env.example).

---

## Running the Server

```bash
python3 run.py
```

Or, if installed as a package:

```bash
token-lite-guard
```

On startup, the server prints a summary of which providers are configured and the dashboard URL.

---

## Usage

### 1. Create a virtual key

Open the dashboard at `http://localhost:8000`, navigate to **Virtual Keys**, and click **New Key**.

Alternatively, use the API directly:

```bash
curl -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{
    "name": "cursor-workspace",
    "provider": "openai",
    "budget_tokens": 200000
  }'
```

Response:

```json
{
  "id": 1,
  "name": "cursor-workspace",
  "key_hash": "tlg-aBcDeFgH...",
  "provider": "openai",
  "budget_tokens": 200000,
  "used_tokens": 0,
  "remaining_tokens": 200000,
  "is_active": true
}
```

### 2. Configure your AI tool

Point your tool's API base URL at the gateway and use the virtual key as the API key:

| Setting | Value |
|---|---|
| Base URL | `http://localhost:8000/v1` |
| API Key | `tlg-aBcDeFgH...` (your virtual key) |

**Cursor**: Settings → Models → API Key and Base URL

**Continue (VS Code)**: In `config.json`, set `apiBase: "http://localhost:8000/v1"` and `apiKey: "tlg-..."`

**OpenAI SDK**:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="tlg-your-virtual-key",
)
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
```

**LangChain**:
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="tlg-your-virtual-key",
    model="gpt-4o",
)
```

### 3. Budget exhaustion

When a key has consumed its full budget, the gateway returns:

```
HTTP 429 Too Many Requests
```

```json
{
  "error": {
    "message": "Budget exhausted. Key 'cursor-workspace' has consumed 200,000 of 200,000 tokens.",
    "type": "token_lite_guard_error",
    "code": "budget_exceeded"
  }
}
```

### 4. Using a custom provider

To add a provider not in the built-in list (e.g., a vLLM server, LiteLLM proxy, or custom deployment):

1. Go to **Dashboard → Providers → Add Provider**
2. Fill in the identifier slug, base URL, and authentication settings
3. Create a virtual key that targets your custom provider by name
4. Send requests with that key; they will be forwarded to your endpoint

---

## API Reference

Interactive API documentation is available at `http://localhost:8000/api/docs` when the server is running.

### Virtual Keys

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/keys` | Create a virtual key |
| `GET` | `/api/keys` | List all virtual keys |
| `GET` | `/api/keys/{id}` | Get a virtual key |
| `PUT` | `/api/keys/{id}` | Update name, budget, or status |
| `POST` | `/api/keys/{id}/reset` | Reset used token counter to zero |
| `DELETE` | `/api/keys/{id}` | Delete a virtual key |

### Providers

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/providers/builtin` | List built-in providers with configuration status |
| `POST` | `/api/providers` | Add a custom provider |
| `GET` | `/api/providers` | List custom providers |
| `GET` | `/api/providers/{id}` | Get a custom provider |
| `PUT` | `/api/providers/{id}` | Update a custom provider |
| `POST` | `/api/providers/{id}/test` | Test connectivity to a custom provider |
| `DELETE` | `/api/providers/{id}` | Delete a custom provider |

### Statistics

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/stats/overview` | Summary metrics for the dashboard |
| `GET` | `/api/stats/usage-chart` | Per-day token and cost data |
| `GET` | `/api/stats/by-model` | Usage breakdown by model |
| `GET` | `/api/stats/by-key` | Usage breakdown by virtual key |
| `GET` | `/api/stats/recent-logs` | Latest request log entries |

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/docs` | Swagger UI |
| `GET` | `/api/redoc` | ReDoc UI |

---

## Dashboard

Access the dashboard at `http://localhost:8000` after starting the server.

**Overview tab** — Summary statistics, daily token consumption chart (7/14/30 day views), top models by usage, and a live activity preview. Refreshes automatically every 15 seconds.

**Virtual Keys tab** — Full key management: create, edit, activate/deactivate, reset budget, and delete keys. Copy key values to clipboard by clicking the key display.

**Providers tab** — View the configuration status of all built-in providers; add, edit, test, and delete custom providers.

**Activity tab** — Complete request log with status, model, provider, token counts, estimated cost, latency, and timestamp.

---

## Architecture

```
[AI Tool / Agent]
    |
    | Authorization: Bearer tlg-xxxxxxxx
    v
+------------------------------------------+
|            token_lite_guard               |
|                                          |
|  1. Extract virtual key from header      |
|  2. Validate key against SQLite DB       |
|  3. Check remaining token budget         |
|     -> HTTP 429 if exhausted             |
|  4. Resolve provider (built-in/custom)   |
|  5. Inject real API key                  |
|  6. Forward request (with streaming)     |
|  7. Count output tokens from SSE stream  |
|  8. Deduct tokens from budget (async)    |
|  9. Write usage log entry                |
+------------------------------------------+
    |
    | Real API key
    v
[LLM Provider — OpenAI / Anthropic / etc.]
```

Token counting uses the `tiktoken` library with the same algorithm as OpenAI's cookbook. For streaming responses, tokens are counted from SSE chunks in real time. For non-streaming responses, token counts are taken from the `usage` field in the response body.

Cost estimation uses an internal pricing table seeded at startup. Prices are approximate and may not reflect current provider rates.

---

## Project Structure

```
token_lite_guard/
├── src/
│   └── token_lite_guard/
│       ├── main.py              # FastAPI application factory and lifespan
│       ├── config.py            # Settings (pydantic-settings, .env support)
│       ├── database.py          # SQLite engine, session management
│       ├── models.py            # ORM models and default pricing table
│       ├── proxy/
│       │   ├── router.py        # /v1/* proxy — budget check and forwarding
│       │   ├── forwarder.py     # HTTP streaming and non-streaming client
│       │   └── token_counter.py # tiktoken-based counting and cost estimation
│       ├── api/
│       │   ├── keys.py          # Virtual key CRUD endpoints
│       │   ├── providers.py     # Provider management endpoints
│       │   └── stats.py         # Analytics and usage statistics
│       └── static/
│           ├── index.html       # Single-page dashboard
│           ├── app.js           # Dashboard JavaScript
│           └── style.css        # Dashboard styles
├── run.py                       # Quick-start: python3 run.py
├── pyproject.toml               # Project metadata and dependencies
├── .env.example                 # Configuration template
├── .gitignore
└── README.md
```

---

## Contributing

Contributions are welcome. Please open an issue to discuss significant changes before submitting a pull request.

When adding a new built-in provider:
1. Add its configuration to `BUILTIN_PROVIDERS` in `config.py`
2. Add its API key and base URL fields to the `Settings` class
3. Add `get_real_api_key` and `get_provider_base_url` entries
4. Add model pricing entries to `DEFAULT_PRICING` in `models.py`
5. Add provider prefix entries to `MODEL_PROVIDER_MAP` in `config.py`
6. Update `.env.example` with the new variables

---

## License

MIT License. See [LICENSE](LICENSE) for details.
