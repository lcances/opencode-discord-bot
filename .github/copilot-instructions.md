# Copilot Instructions — opencode-discord-bot

## Architecture

Two-component async Python bot bridging Discord ↔ OpenCode AI sessions over HTTP:

```
main.py (entrypoint, config, lifecycle)
└── src/
    ├── opencode_client.py  — OpenCodeClient: manages `opencode serve` subprocess + REST API wrapper (aiohttp)
    └── discord_bot.py      — OpenCodeBot(commands.Bot): Discord commands + message relay
```

**Data flow:** Discord message → `OpenCodeBot.on_message` → `OpenCodeClient.send_message(session_id, text)` → `POST /session/:id/message` → extract text parts from response → chunk & send back to Discord channel.

**Session model:** Each Discord channel maps to one OpenCode session (`_sessions: dict[int, str]` — channel_id → session_id). Sessions are created with `!start` and destroyed with `!stop`. All sessions are cleaned up on shutdown.

## Key Patterns

- **Fully async** — all I/O uses `asyncio`/`aiohttp`/`discord.py` async APIs. Never use blocking calls.
- **`OpenCodeClient` is a `@dataclass`** with lazy `aiohttp.ClientSession` creation via the `http` property. It spawns `opencode serve` as a subprocess and polls `/global/health` until ready.
- **Message chunking** — `chunk_message()` in `discord_bot.py` splits responses at `DISCORD_MAX_LEN = 2000` chars, preferring newline boundaries.
- **Channel allowlisting** — `allowed_channels` config filters by channel *name* (not ID). Empty list = all channels allowed.
- **Two server modes** — Bot either spawns `opencode serve` itself, or connects to an external one when `EXTERNAL_OPENCODE` env var is set (used in Docker via `start.sh`).

## Configuration

Config is loaded from `config.yaml` (YAML, not env vars). See `config.yaml.example` for the schema. The `discord.token` field is required. Config is a flat dict passed through `main.py` — `config["discord"]` and `config["opencode"]` sections map directly to constructor kwargs.

## Running

```bash
# Local development
cp config.yaml.example config.yaml  # fill in discord.token
uv sync                             # project uses uv (see pyproject.toml)
python main.py --debug              # --debug enables DEBUG logging

# Docker
docker-compose up -d --build        # uses start.sh which sets EXTERNAL_OPENCODE=1
```

## Dependencies

Python 3.11+ required. Three runtime deps only: `discord.py`, `aiohttp`, `pyyaml`. Defined in both `pyproject.toml` (uv/pip) and `requirements.txt` (Docker). Keep them in sync.

## Docker

`Dockerfile` is based on `ghcr.io/anomalyco/opencode` (Alpine + opencode CLI). `start.sh` starts `opencode serve` in background, polls health, then runs `main.py` with `EXTERNAL_OPENCODE=1` so the bot doesn't spawn a second server process.

## Conventions

- Logging via `logging.getLogger(__name__)` — no print statements.
- Type hints on all function signatures (Python 3.11+ syntax: `list[str]`, `str | None`).
- OpenCode REST responses use `{ info: Message, parts: Part[] }` shape — use `OpenCodeClient.extract_text()` to pull text parts.
- No tests exist yet. No linter/formatter config. No CI pipeline.
