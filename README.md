# token_lite_guard

> **Protect your AI budget. Monitor every token. Block the burn.**

A lightweight, single-command AI Gateway that sits between your AI tools (Cursor, AutoGPT, any AI agent) and LLM providers (OpenAI, Anthropic). It counts tokens in real-time and immediately blocks requests when your budget runs out.

![Dashboard Preview](https://placeholder.com/dashboard)

## ✨ Features

- 🛡️ **Budget Enforcement** — Hard stop when token budget is exhausted (HTTP 429)
- 🔑 **Virtual API Keys** — Issue multiple keys with individual budgets per agent/project
- 📊 **Live Dashboard** — Beautiful dark UI with real-time charts and usage stats
- 💰 **Cost Estimation** — USD cost estimates based on current OpenAI/Anthropic pricing
- ⚡ **Streaming Support** — Zero-lag proxying with SSE streaming
- 🔄 **Multi-Provider** — OpenAI and Anthropic, auto-detected from model name
- 💾 **Zero Dependencies** — SQLite only, no Docker/Redis/PostgreSQL needed
- 🪶 **Ultra Lightweight** — ~20MB RAM footprint

## 🚀 Quick Start

### 1. Install

```bash
# Clone the repo
git clone https://github.com/kisibongtoi772/token_lite_guard
cd token_lite_guard

# Install dependencies (using pip)
pip install -e .
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and add your real API key:
# OPENAI_API_KEY=sk-your-real-key-here
```

### 3. Run

```bash
python run.py
# Or after installing: token-lite-guard
```

### 4. Use

Open your dashboard: **http://localhost:8000**

Configure your AI tool:
```
Base URL: http://localhost:8000/v1
API Key:  tlg-xxxxxxxx  (create one in the dashboard)
```

## 📡 API Usage

### Create a Virtual Key (via dashboard or API)

```bash
curl -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{
    "name": "cursor-dev",
    "budget_tokens": 100000,
    "provider": "openai"
  }'
```

Response:
```json
{
  "id": 1,
  "name": "cursor-dev",
  "key_hash": "tlg-aBcDeFgHiJkL...",
  "budget_tokens": 100000,
  "used_tokens": 0,
  "remaining_tokens": 100000,
  "is_active": true
}
```

### Configure Cursor / VS Code AI

In Cursor settings:
- **OpenAI Base URL**: `http://localhost:8000/v1`
- **API Key**: `tlg-your-virtual-key`

### When Budget Is Exhausted

```json
HTTP 429 Too Many Requests
{
  "error": {
    "message": "Budget exhausted. Key 'cursor-dev' has used 100000/100000 tokens.",
    "type": "token_lite_guard_error",
    "code": "budget_exceeded"
  }
}
```

## 🏗️ Architecture

```
[Cursor / Agent / AI Tool]
        │ http://localhost:8000/v1
        ▼
┌──────────────────────────────────┐
│         token_lite_guard         │
│                                  │
│  1. Extract Virtual Key          │
│  2. Check Budget → 429 if empty  │
│  3. Inject Real API Key          │
│  4. Forward + Stream Response    │
│  5. Count Tokens (background)    │
│  6. Deduct from Budget           │
└──────────────────────────────────┘
        │ https://api.openai.com/v1
        ▼
[Real LLM Provider]
```

## 🗄️ Project Structure

```
token_lite_guard/
├── src/token_lite_guard/
│   ├── main.py           # FastAPI app + lifespan
│   ├── config.py         # Settings from .env
│   ├── database.py       # SQLite + SQLModel setup
│   ├── models.py         # ORM models (VirtualKey, UsageLog, Pricing)
│   ├── proxy/
│   │   ├── router.py     # /v1/* intercept + budget check
│   │   ├── forwarder.py  # HTTP streaming proxy
│   │   └── token_counter.py  # tiktoken integration
│   ├── api/
│   │   ├── keys.py       # Virtual key CRUD
│   │   └── stats.py      # Analytics endpoints
│   └── static/
│       ├── index.html    # Dashboard SPA
│       ├── app.js        # Vanilla JS
│       └── style.css     # Glassmorphism dark theme
├── run.py                # Quick start: `python run.py`
├── pyproject.toml
└── .env.example
```

## 🔧 Configuration

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Your real OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Your real Anthropic API key |
| `PORT` | `8000` | Server port |
| `DB_PATH` | `./data/token_guard.db` | SQLite database path |
| `DEFAULT_BUDGET_TOKENS` | `100000` | Default budget for new keys |

## 📊 Dashboard

Access the management dashboard at **http://localhost:8000**:

- **Overview cards** — Total tokens, estimated cost, active keys, requests today
- **Usage chart** — Daily token consumption (7/14/30 day view)
- **Model breakdown** — Which models consume the most
- **Keys manager** — Create, edit, pause, reset virtual keys
- **Activity log** — Real-time request log with latency and cost

## 🛡️ License

MIT — Free to use and modify.
