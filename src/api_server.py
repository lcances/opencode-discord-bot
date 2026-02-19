"""
Internal HTTP API Server

Provides a lightweight REST endpoint to programmatically create Discord
channels, bind them to OpenCode sessions, and send an initial prompt —
all without user interaction.

Endpoints
---------
POST /api/trigger
    Create a channel + session + send prompt.
    Body: { "channel_name": str, "prompt": str, "category"?: str }
    Returns: { "channel_id": int, "channel_name": str, "session_id": str }

GET  /api/health
    Returns { "ok": true } when the API server is running.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from .discord_bot import OpenCodeBot

log = logging.getLogger(__name__)


def _build_app(bot: OpenCodeBot, secret_key: str) -> web.Application:
    """Construct the aiohttp Application with routes and middleware."""

    @web.middleware
    async def auth_middleware(
        request: web.Request,
        handler: web.RequestHandler,
    ) -> web.StreamResponse:
        # Health endpoint is public
        if request.path == "/api/health":
            return await handler(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise web.HTTPUnauthorized(text="Missing Bearer token")

        token = auth_header.removeprefix("Bearer ").strip()
        if token != secret_key:
            raise web.HTTPForbidden(text="Invalid API key")

        return await handler(request)

    app = web.Application(middlewares=[auth_middleware])
    app["bot"] = bot

    app.router.add_get("/api/health", _handle_health)
    app.router.add_post("/api/trigger", _handle_trigger)

    return app


# ------------------------------------------------------------------ #
#  Handlers
# ------------------------------------------------------------------ #


async def _handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def _handle_trigger(request: web.Request) -> web.Response:
    bot: OpenCodeBot = request.app["bot"]

    if not bot.is_ready():
        raise web.HTTPServiceUnavailable(text="Discord bot is not ready yet")

    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    channel_name = body.get("channel_name")
    prompt = body.get("prompt")

    if not channel_name or not isinstance(channel_name, str):
        raise web.HTTPBadRequest(text="'channel_name' (string) is required")
    if not prompt or not isinstance(prompt, str):
        raise web.HTTPBadRequest(text="'prompt' (string) is required")

    category = body.get("category")

    log.info(
        "API trigger: channel_name=%s, category=%s, prompt=%s",
        channel_name,
        category,
        prompt[:80],
    )

    try:
        result = await bot.create_session_channel(
            channel_name=channel_name,
            prompt=prompt,
            category=category,
        )
    except RuntimeError as exc:
        raise web.HTTPServiceUnavailable(text=str(exc))
    except Exception as exc:
        log.error("Trigger failed: %s", exc, exc_info=True)
        raise web.HTTPInternalServerError(text=f"Internal error: {exc}")

    return web.json_response(result)


# ------------------------------------------------------------------ #
#  Server lifecycle
# ------------------------------------------------------------------ #


async def start_api_server(
    bot: OpenCodeBot,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    secret_key: str = "",
) -> web.AppRunner:
    """Start the API server and return the runner (for later cleanup).

    Parameters
    ----------
    bot:
        The Discord bot instance (must be started separately).
    host:
        Bind address for the HTTP server.
    port:
        Port for the HTTP server.
    secret_key:
        Bearer token required to call protected endpoints.

    Returns
    -------
    The ``web.AppRunner`` — caller is responsible for calling
    ``runner.cleanup()`` on shutdown.
    """
    if not secret_key:
        log.warning(
            "API server started WITHOUT a secret key — all requests are accepted. "
            "Set api.secret_key in config.yaml for production use."
        )

    app = _build_app(bot, secret_key)
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("API server listening on http://%s:%s", host, port)

    return runner
