"""
OpenCode HTTP Client

Manages a local `opencode serve` process and communicates with it
via the REST API documented at https://opencode.ai/docs/server/.
"""

import asyncio
import logging
import signal
from dataclasses import dataclass, field

import aiohttp

log = logging.getLogger(__name__)


@dataclass
class OpenCodeClient:
    """Thin async wrapper around the opencode serve HTTP API."""

    hostname: str = "127.0.0.1"
    port: int = 4096
    working_directory: str = "."
    username: str | None = None
    password: str | None = None

    _process: asyncio.subprocess.Process | None = field(
        default=None, init=False, repr=False
    )
    _http: aiohttp.ClientSession | None = field(
        default=None, init=False, repr=False
    )

    # ------------------------------------------------------------------ #
    #  URL / auth helpers
    # ------------------------------------------------------------------ #

    @property
    def base_url(self) -> str:
        return f"http://{self.hostname}:{self.port}"

    @property
    def _auth(self) -> aiohttp.BasicAuth | None:
        if self.username and self.password:
            return aiohttp.BasicAuth(self.username, self.password)
        return None

    @property
    def http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                base_url=self.base_url,
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return self._http

    # ------------------------------------------------------------------ #
    #  Process lifecycle
    # ------------------------------------------------------------------ #

    async def start_server(self) -> None:
        """Spawn `opencode serve` as a background subprocess."""
        if self._process is not None:
            log.warning("OpenCode server already running (pid %s)", self._process.pid)
            return

        cmd = [
            "opencode",
            "serve",
            "--hostname",
            self.hostname,
            "--port",
            str(self.port),
        ]
        log.info("Starting: %s  (cwd=%s)", " ".join(cmd), self.working_directory)

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("OpenCode server started (pid %s)", self._process.pid)

        # Wait for the server to become healthy
        await self._wait_healthy()

    async def _wait_healthy(self, retries: int = 30, delay: float = 1.0) -> None:
        """Poll /global/health until the server responds."""
        for attempt in range(1, retries + 1):
            try:
                data = await self.health()
                if data.get("healthy"):
                    log.info("OpenCode server healthy (attempt %d)", attempt)
                    return
            except (aiohttp.ClientError, ConnectionError, OSError):
                pass
            await asyncio.sleep(delay)

        raise RuntimeError(
            f"OpenCode server did not become healthy after {retries} attempts"
        )

    async def stop_server(self) -> None:
        """Gracefully terminate the opencode serve process."""
        if self._process is None:
            return

        log.info("Stopping OpenCode server (pid %s)", self._process.pid)
        try:
            self._process.send_signal(signal.SIGTERM)
            await asyncio.wait_for(self._process.wait(), timeout=10)
        except asyncio.TimeoutError:
            log.warning("Force-killing OpenCode server")
            self._process.kill()
            await self._process.wait()
        finally:
            self._process = None

        if self._http and not self._http.closed:
            await self._http.close()
            self._http = None

    # ------------------------------------------------------------------ #
    #  Global
    # ------------------------------------------------------------------ #

    async def health(self) -> dict:
        """GET /global/health"""
        async with self.http.get("/global/health") as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------ #
    #  Sessions
    # ------------------------------------------------------------------ #

    async def create_session(self, title: str | None = None) -> dict:
        """POST /session — create a new session.

        Returns the full Session object.
        """
        body: dict = {}
        if title:
            body["title"] = title
        async with self.http.post("/session", json=body) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def list_sessions(self) -> list[dict]:
        """GET /session"""
        async with self.http.get("/session") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_session(self, session_id: str) -> dict:
        """GET /session/:id"""
        async with self.http.get(f"/session/{session_id}") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def delete_session(self, session_id: str) -> bool:
        """DELETE /session/:id"""
        async with self.http.delete(f"/session/{session_id}") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def abort_session(self, session_id: str) -> bool:
        """POST /session/:id/abort"""
        async with self.http.post(f"/session/{session_id}/abort") as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------ #
    #  Messages
    # ------------------------------------------------------------------ #

    async def send_message(
        self,
        session_id: str,
        content: str,
        *,
        model: str | None = None,
        agent: str | None = None,
    ) -> dict:
        """POST /session/:id/message — send a message and wait for the response.

        The body uses the ``parts`` field to carry user text.
        Returns ``{ info: Message, parts: Part[] }``.
        """
        body: dict = {
            "parts": [{"type": "text", "text": content}],
        }
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent

        async with self.http.post(
            f"/session/{session_id}/message", json=body
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def send_message_async(
        self,
        session_id: str,
        content: str,
        *,
        model: str | None = None,
        agent: str | None = None,
    ) -> None:
        """POST /session/:id/prompt_async — fire-and-forget message."""
        body: dict = {
            "parts": [{"type": "text", "text": content}],
        }
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent

        async with self.http.post(
            f"/session/{session_id}/prompt_async", json=body
        ) as resp:
            resp.raise_for_status()

    async def list_messages(
        self, session_id: str, *, limit: int | None = None
    ) -> list[dict]:
        """GET /session/:id/message"""
        params: dict = {}
        if limit is not None:
            params["limit"] = limit
        async with self.http.get(
            f"/session/{session_id}/message", params=params
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_message(self, session_id: str, message_id: str) -> dict:
        """GET /session/:id/message/:messageID"""
        async with self.http.get(
            f"/session/{session_id}/message/{message_id}"
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def extract_text(response: dict) -> str:
        """Pull plain-text content out of a message response.

        The response shape is ``{ info: Message, parts: Part[] }``.
        Parts can be text, tool-call, tool-result, etc.
        We concatenate only the text parts.
        """
        parts = response.get("parts", [])
        texts: list[str] = []
        for part in parts:
            if part.get("type") == "text":
                texts.append(part.get("text", ""))
        return "\n".join(texts).strip() or "(no text in response)"
