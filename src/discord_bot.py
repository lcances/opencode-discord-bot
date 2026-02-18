"""
Discord Bot

Bridges Discord channels to OpenCode sessions.
Each channel that starts a session gets its own OpenCode session ID.
Messages in that channel are forwarded to OpenCode and the response
is posted back.
"""

import logging
from typing import Any

import discord
from discord.ext import commands

from .opencode_client import OpenCodeClient

log = logging.getLogger(__name__)

# Discord limits messages to 2 000 characters.
DISCORD_MAX_LEN = 2000


def chunk_message(text: str, limit: int = DISCORD_MAX_LEN) -> list[str]:
    """Split a long message into chunks that fit Discord's limit.

    Tries to split on newlines first, then hard-wraps.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Try to find a newline to break on
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


class OpenCodeBot(commands.Bot):
    """A Discord bot that proxies messages to OpenCode sessions."""

    def __init__(
        self,
        opencode: OpenCodeClient,
        *,
        allowed_channels: list[str] | None = None,
        command_prefix: str = "!",
        **kwargs: Any,
    ):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=command_prefix,
            intents=intents,
            **kwargs,
        )

        self.opencode = opencode
        self.allowed_channels: set[str] = set(allowed_channels or [])

        # channel_id  ->  opencode session_id
        self._sessions: dict[int, str] = {}

        # Register commands
        self._register_commands()

    # ------------------------------------------------------------------ #
    #  Events
    # ------------------------------------------------------------------ #

    async def on_ready(self) -> None:
        log.info("Discord bot connected as %s (id=%s)", self.user, self.user.id)
        guilds = [g.name for g in self.guilds]
        log.info("Serving in guilds: %s", ", ".join(guilds))

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return  # silently ignore unknown commands
        log.error("Command error: %s", error, exc_info=error)
        await ctx.send(f"⚠️ Error: {error}")

    # ------------------------------------------------------------------ #
    #  Commands
    # ------------------------------------------------------------------ #

    def _register_commands(self) -> None:
        @self.command(name="start")
        async def cmd_start(ctx: commands.Context, *, title: str = "") -> None:
            """Start an OpenCode session for this channel."""
            if not self._channel_allowed(ctx.channel):
                return

            if ctx.channel.id in self._sessions:
                await ctx.send("⚠️ A session is already active in this channel. "
                               "Use `!stop` first to end it.")
                return

            session_title = title or f"discord-{ctx.channel.name}"
            async with ctx.typing():
                session = await self.opencode.create_session(title=session_title)

            session_id = session.get("id") or session.get("ID")
            self._sessions[ctx.channel.id] = session_id
            log.info(
                "Session created: %s for #%s", session_id, ctx.channel.name
            )
            await ctx.send(
                f"✅ OpenCode session started (`{session_id[:8]}…`).\n"
                f"Send messages normally — I'll forward them to OpenCode."
            )

        @self.command(name="stop")
        async def cmd_stop(ctx: commands.Context) -> None:
            """Stop the OpenCode session for this channel."""
            if not self._channel_allowed(ctx.channel):
                return

            session_id = self._sessions.pop(ctx.channel.id, None)
            if session_id is None:
                await ctx.send("ℹ️ No active session in this channel.")
                return

            try:
                await self.opencode.delete_session(session_id)
            except Exception as exc:
                log.warning("Failed to delete session %s: %s", session_id, exc)

            await ctx.send("🛑 Session ended.")

        @self.command(name="status")
        async def cmd_status(ctx: commands.Context) -> None:
            """Show active sessions."""
            if not self._channel_allowed(ctx.channel):
                return

            if not self._sessions:
                await ctx.send("ℹ️ No active sessions.")
                return

            lines = ["**Active sessions:**"]
            for ch_id, sid in self._sessions.items():
                channel = self.get_channel(ch_id)
                ch_name = channel.name if channel else str(ch_id)
                lines.append(f"• #{ch_name} → `{sid[:8]}…`")
            await ctx.send("\n".join(lines))

    # ------------------------------------------------------------------ #
    #  Message relay
    # ------------------------------------------------------------------ #

    async def on_message(self, message: discord.Message) -> None:
        # Let commands be processed first
        await self.process_commands(message)

        # Ignore bots, DMs, and command messages
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if message.content.startswith(self.command_prefix):
            return
        if not self._channel_allowed(message.channel):
            return

        # Only relay if there's an active session for this channel
        session_id = self._sessions.get(message.channel.id)
        if session_id is None:
            return

        user_text = message.content.strip()
        if not user_text:
            return

        log.info(
            "[#%s] %s: %s",
            message.channel.name,
            message.author.display_name,
            user_text[:80],
        )

        async with message.channel.typing():
            try:
                response = await self.opencode.send_message(session_id, user_text)
                reply_text = OpenCodeClient.extract_text(response)
            except Exception as exc:
                log.error("OpenCode request failed: %s", exc, exc_info=True)
                await message.channel.send(f"⚠️ OpenCode error: {exc}")
                return

        # Send the response, chunked if necessary
        for chunk in chunk_message(reply_text):
            await message.channel.send(chunk)

    # ------------------------------------------------------------------ #
    #  Cleanup
    # ------------------------------------------------------------------ #

    async def cleanup_sessions(self) -> None:
        """Delete all active OpenCode sessions (called on shutdown)."""
        for ch_id, session_id in list(self._sessions.items()):
            try:
                await self.opencode.delete_session(session_id)
                log.info("Cleaned up session %s", session_id)
            except Exception as exc:
                log.warning("Failed to cleanup session %s: %s", session_id, exc)
        self._sessions.clear()

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _channel_allowed(self, channel: discord.abc.GuildChannel) -> bool:
        """Return True if the bot should operate in this channel."""
        if not self.allowed_channels:
            return True  # no filter → allow all
        return channel.name in self.allowed_channels
