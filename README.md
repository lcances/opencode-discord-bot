# OpenCode Discord Bot

A lightweight Python bot that bridges Discord channels to [OpenCode](https://opencode.ai) AI sessions. Users can start an OpenCode session from Discord, send messages, and receive AI responses — all through chat.

## How It Works

```
Discord User  ──▶  Discord Bot  ──▶  opencode serve (HTTP API)
                        ◀──               ◀──
                   (response)         (AI response)
```

1. The bot spawns an `opencode serve` process in the background
2. Users type `!start` in a Discord channel to create an OpenCode session
3. Every message in that channel is forwarded to the OpenCode session via `POST /session/:id/message`
4. The AI response is posted back to the Discord channel
5. `!stop` ends the session

## Prerequisites

- Python 3.11+
- [OpenCode CLI](https://opencode.ai) installed and configured
- A Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy config and fill in your values
cp config.yaml.example config.yaml
# Edit config.yaml — set your Discord bot token at minimum

# Run the bot
python main.py
```

## Configuration

| Key | Description | Default |
|-----|-------------|---------|
| `discord.token` | Discord bot token (required) | — |
| `discord.allowed_channels` | List of channel names to operate in (empty = all) | `[]` |
| `discord.prefix` | Command prefix | `!` |
| `opencode.hostname` | OpenCode server bind address | `127.0.0.1` |
| `opencode.port` | OpenCode server port | `4096` |
| `opencode.working_directory` | Directory where `opencode serve` runs | `.` |
| `api.enabled` | Enable the internal HTTP API server | `false` |
| `api.host` | API server bind address | `127.0.0.1` |
| `api.port` | API server port | `8080` |
| `api.secret_key` | Bearer token for API authentication | `""` |

## Commands

| Command | Description |
|---------|-------------|
| `!start [title]` | Start a new OpenCode session in the current channel |
| `!stop` | End the active session in the current channel |
| `!status` | Show all active sessions across channels |

## Programmatic API

When `api.enabled` is `true`, the bot starts an internal HTTP server alongside Discord. This lets you programmatically create channels, bind them to OpenCode sessions, and send prompts — all without any Discord user interaction.

### Endpoints

#### `GET /api/health`

Public health check (no auth required).

```bash
curl http://localhost:8080/api/health
# {"ok": true}
```

#### `POST /api/trigger`

Create a Discord channel, start an OpenCode session, send a prompt, and post the AI response into the new channel.

**Headers:**
- `Authorization: Bearer <secret_key>` (required if `api.secret_key` is set)
- `Content-Type: application/json`

**Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `channel_name` | string | ✅ | Name of the Discord text channel to create |
| `prompt` | string | ✅ | Initial message to send to OpenCode |
| `category` | string | ❌ | Category name (created if it doesn't exist) |

**Example with curl:**

```bash
curl -X POST http://localhost:8080/api/trigger \
  -H "Authorization: Bearer CHANGE_ME" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_name": "bug-investigation-42",
    "prompt": "Investigate the null pointer exception in src/auth.py line 87",
    "category": "AI Sessions"
  }'
```

**Response:**

```json
{
  "channel_id": 1234567890,
  "channel_name": "bug-investigation-42",
  "session_id": "abc123..."
}
```

**Example with Python:**

```python
import requests

resp = requests.post(
    "http://localhost:8080/api/trigger",
    headers={"Authorization": "Bearer CHANGE_ME"},
    json={
        "channel_name": "review-pr-99",
        "prompt": "Review the changes in PR #99 and summarize the key issues.",
        "category": "Code Reviews",
    },
)
print(resp.json())
```

**Error responses:**

| Status | Reason |
|--------|--------|
| 400 | Missing or invalid `channel_name` / `prompt` |
| 401 | Missing `Authorization` header |
| 403 | Invalid API key |
| 503 | Discord bot not ready yet |

### Trigger Script

A convenience script `trigger.py` is included for automation. It reads a prompt from a markdown file, names the channel after today's date, and calls the API.

```bash
# Basic usage
python trigger.py prompts/daily.md

# With auth and category
python trigger.py prompts/daily.md --key MY_SECRET --category "Daily Reports"

# Using environment variables
export API_URL=http://localhost:8080
export API_SECRET_KEY=MY_SECRET
python trigger.py prompts/daily.md
```

| Argument | Description | Default |
|----------|-------------|---------|
| `prompt_file` | Path to a markdown file used as the prompt (positional, required) | — |
| `--url` | Base URL of the API server | `$API_URL` or `http://127.0.0.1:8080` |
| `--key` | Bearer token for auth | `$API_SECRET_KEY` or empty |
| `--category` | Discord category to place the channel in | none |

## Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → Bot
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Copy the bot token into `config.yaml`
5. Invite the bot to your server with the OAuth2 URL Generator:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Read Message History`, `View Channels`, `Manage Channels`

## Architecture

```
opencode_discord_bot/
├── main.py                 # Entry point, config loading, lifecycle
├── config.yaml.example     # Configuration template
├── requirements.txt        # Python dependencies
└── src/
    ├── __init__.py
    ├── opencode_client.py  # HTTP client for opencode serve API
    ├── discord_bot.py      # Discord bot with commands and message relay
    └── api_server.py       # Internal HTTP API for programmatic triggers
```

- **`OpenCodeClient`** — Manages the `opencode serve` subprocess and wraps the REST API (sessions, messages, health)
- **`OpenCodeBot`** — Discord bot that maps channels to OpenCode sessions and relays messages bidirectionally. Exposes `create_session_channel()` for programmatic use.
- **`ApiServer`** — Lightweight `aiohttp.web` server exposing `POST /api/trigger` to create channels + sessions without Discord user interaction
- **`main.py`** — Wires everything together with graceful shutdown

## License

MIT
