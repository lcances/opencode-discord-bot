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

## Commands

| Command | Description |
|---------|-------------|
| `!start [title]` | Start a new OpenCode session in the current channel |
| `!stop` | End the active session in the current channel |
| `!status` | Show all active sessions across channels |

## Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → Bot
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Copy the bot token into `config.yaml`
5. Invite the bot to your server with the OAuth2 URL Generator:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Read Message History`, `View Channels`

## Architecture

```
opencode_discord_bot/
├── main.py                 # Entry point, config loading, lifecycle
├── config.yaml.example     # Configuration template
├── requirements.txt        # Python dependencies
└── src/
    ├── __init__.py
    ├── opencode_client.py  # HTTP client for opencode serve API
    └── discord_bot.py      # Discord bot with commands and message relay
```

- **`OpenCodeClient`** — Manages the `opencode serve` subprocess and wraps the REST API (sessions, messages, health)
- **`OpenCodeBot`** — Discord bot that maps channels to OpenCode sessions and relays messages bidirectionally
- **`main.py`** — Wires everything together with graceful shutdown

## License

MIT
