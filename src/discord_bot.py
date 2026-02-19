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

        log.info(
            "Bot initialized (prefix=%r, allowed_channels=%s)",
            command_prefix,
            self.allowed_channels or "<all>",
        )

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
            log.debug("Unknown command from %s: %s", ctx.author, ctx.message.content)
            return  # silently ignore unknown commands
        log.error("Command error in #%s: %s", ctx.channel, error, exc_info=error)
        await ctx.send(f"⚠️ Error: {error}")

    # ------------------------------------------------------------------ #
    #  Commands
    # ------------------------------------------------------------------ #

    def _register_commands(self) -> None:
        @self.command(name="start")
        async def cmd_start(ctx: commands.Context, *, title: str = "") -> None:
            """Start an OpenCode session for this channel."""
            log.info(
                "!start invoked by %s in #%s (title=%r)",
                ctx.author, ctx.channel.name, title,
            )
            if not self._channel_allowed(ctx.channel):
                log.info("!start denied — #%s not in allowed channels", ctx.channel.name)
                return

            if ctx.channel.id in self._sessions:
                log.info(
                    "!start rejected — session already active in #%s (session=%s)",
                    ctx.channel.name,
                    self._sessions[ctx.channel.id][:8],
                )
                await ctx.send("\u26a0\ufe0f A session is already active in this channel. "
                               "Use `!stop` first to end it.")
                return

            session_title = title or f"discord-{ctx.channel.name}"
            log.debug("Creating OpenCode session with title=%r", session_title)
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
            log.info("!stop invoked by %s in #%s", ctx.author, ctx.channel.name)
            if not self._channel_allowed(ctx.channel):
                log.info("!stop denied — #%s not in allowed channels", ctx.channel.name)
                return

            session_id = self._sessions.pop(ctx.channel.id, None)
            if session_id is None:
                log.info("!stop — no active session in #%s", ctx.channel.name)
                await ctx.send("ℹ️ No active session in this channel.")
                return

            log.info("Stopping session %s in #%s", session_id[:8], ctx.channel.name)
            try:
                await self.opencode.delete_session(session_id)
                log.info("Session %s deleted successfully", session_id[:8])
            except Exception as exc:
                log.warning("Failed to delete session %s: %s", session_id, exc)

            await ctx.send("🛑 Session ended.")

        @self.command(name="status")
        async def cmd_status(ctx: commands.Context) -> None:
            """Show active sessions."""
            log.info("!status invoked by %s in #%s", ctx.author, ctx.channel.name)
            if not self._channel_allowed(ctx.channel):
                log.info("!status denied — #%s not in allowed channels", ctx.channel.name)
                return

            if not self._sessions:
                log.debug("No active sessions to report")
                await ctx.send("ℹ️ No active sessions.")
                return

            log.debug("Reporting %d active session(s)", len(self._sessions))

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
            log.debug(
                "Ignoring message in #%s — channel not allowed",
                message.channel.name,
            )
            return

        # Only relay if there's an active session for this channel
        session_id = self._sessions.get(message.channel.id)
        if session_id is None:
            log.debug(
                "Ignoring message in #%s — no active session",
                message.channel.name,
            )
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
        log.debug(
            "Relaying message to session %s (full length=%d)",
            session_id[:8],
            len(user_text),
        )

        async with message.channel.typing():
            try:
                response = await self.opencode.send_message(session_id, user_text)
                reply_text = OpenCodeClient.extract_text(response)
                log.debug(
                    "Received response from session %s (length=%d)",
                    session_id[:8],
                    len(reply_text),
                )
            except Exception as exc:
                log.error("OpenCode request failed: %s", exc, exc_info=True)
                await message.channel.send(f"⚠️ OpenCode error: {exc}")
                return

        # Send the response, chunked if necessary
        chunks = chunk_message(reply_text)
        if len(chunks) > 1:
            log.debug(
                "Sending response in %d chunks to #%s",
                len(chunks),
                message.channel.name,
            )
        for chunk in chunks:
            await message.channel.send(chunk)

    # ------------------------------------------------------------------ #
    #  Programmatic API
    # ------------------------------------------------------------------ #

    async def create_session_channel(
        self,
        channel_name: str,
        prompt: str,
        *,
        category: str | None = None,
    ) -> dict:
        """Programmatically create a Discord channel, bind it to an OpenCode
        session, send *prompt* to OpenCode, and post the AI response.

        This requires the bot to be fully ready (guild cache populated).

        Parameters
        ----------
        channel_name:
            Name of the new Discord text channel.
        prompt:
            The initial message to send to OpenCode.
        category:
            Optional category name. If it exists, the channel is created under
            it; if it doesn't, a new category is created.

        Returns
        -------
        dict with ``channel_id``, ``channel_name``, and ``session_id``.
        """
        if not self.is_ready():
            raise RuntimeError("Bot is not ready yet")

        guild = self._get_guild()
        log.info(
            "create_session_channel: name=%s, category=%s, guild=%s",
            channel_name, category, guild.name,
        )

        # Resolve or create category
        discord_category: discord.CategoryChannel | None = None
        if category:
            discord_category = discord.utils.get(guild.categories, name=category)
            if discord_category is None:
                log.info("Creating category '%s' in guild '%s'", category, guild.name)
                discord_category = await guild.create_category(category)
            else:
                log.debug("Using existing category '%s' (id=%s)", category, discord_category.id)

        # Create the text channel
        channel = await guild.create_text_channel(
            name=channel_name,
            category=discord_category,
        )
        log.info("Created channel #%s (id=%s)", channel.name, channel.id)

        # Create an OpenCode session
        log.debug("Creating OpenCode session for #%s", channel.name)
        session = await self.opencode.create_session(title=f"discord-{channel.name}")
        session_id = session.get("id") or session.get("ID")
        self._sessions[channel.id] = session_id
        log.info("Session %s bound to #%s", session_id, channel.name)

        # Send the prompt and post the response
        log.debug("Sending initial prompt to session %s (length=%d)", session_id[:8], len(prompt))
        try:
            response = await self.opencode.send_message(session_id, prompt)
            reply_text = OpenCodeClient.extract_text(response)
            log.debug(
                "Received initial response from session %s (length=%d)",
                session_id[:8],
                len(reply_text),
            )
        except Exception as exc:
            log.error("OpenCode request failed: %s", exc, exc_info=True)
            await channel.send(f"⚠️ OpenCode error: {exc}")
            return {
                "channel_id": channel.id,
                "channel_name": channel.name,
                "session_id": session_id,
                "error": str(exc),
            }

        for chunk in chunk_message(reply_text):
            await channel.send(chunk)

        log.info(
            "create_session_channel completed: #%s → session %s",
            channel.name,
            session_id[:8],
        )
        return {
            "channel_id": channel.id,
            "channel_name": channel.name,
            "session_id": session_id,
        }

    # ------------------------------------------------------------------ #
    #  Cleanup
    # ------------------------------------------------------------------ #

    async def cleanup_sessions(self) -> None:
        """Delete all active OpenCode sessions (called on shutdown)."""
        count = len(self._sessions)
        if count == 0:
            log.info("No active sessions to clean up")
            return
        log.info("Cleaning up %d active session(s) …", count)
        for ch_id, session_id in list(self._sessions.items()):
            try:
                await self.opencode.delete_session(session_id)
                log.info("Cleaned up session %s", session_id)
            except Exception as exc:
                log.warning("Failed to cleanup session %s: %s", session_id, exc)
        self._sessions.clear()
        log.info("Session cleanup complete")

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _get_guild(self) -> discord.Guild:
        """Return the first (and assumed only) guild the bot is in."""
        if not self.guilds:
            raise RuntimeError("Bot is not in any guild")
        return self.guilds[0]

    def _channel_allowed(self, channel: discord.abc.GuildChannel) -> bool:
        """Return True if the bot should operate in this channel."""
        if not self.allowed_channels:
            return True  # no filter → allow all
        allowed = channel.name in self.allowed_channels
        if not allowed:
            log.debug(
                "Channel #%s not in allowed set %s",
                channel.name,
                self.allowed_channels,
            )
        return allowed
