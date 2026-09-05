"""Connecting a renderer to Engram's Event API v2 host and staying connected.

A v2 renderer owns its own process. Engram may not be running when it starts, may
restart under it, and regenerates its port, token and instance id every time, so
the connection is a loop rather than an event: read discovery, connect, register,
consume until the socket ends, wait, repeat.

The loop only ever hands the caller a live, registered session. Everything about
failing and retrying stays here.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from .discovery import (
    SCHEMA_VERSION,
    Discovery,
    DiscoveryError,
    backoff_delays,
    read_discovery,
    register_message,
)
from .protocol import JsonlTransport

CONNECT_TIMEOUT_S = 2.0
# A session has to last this long to count as good. Registering and dropping
# immediately is a flap, not a success, and resetting the backoff on it turns
# the loop into a spin that hammers the host.
STABLE_SESSION_S = 5.0


@dataclass(frozen=True)
class Registration:
    """What this renderer tells Engram about itself."""

    renderer_id: str
    name: str
    supported_modes: tuple[str, ...] = ("observer", "replace")
    capabilities: tuple[str, ...] = ()


class Session:
    """One registered connection. Closing it ends the socket."""

    def __init__(self, sock: socket.socket, discovery: Discovery) -> None:
        self._socket = sock
        self.discovery = discovery
        # A text file pair over the socket lets the v1 transport carry v2 lines
        # unchanged: the framing was never what differed between the versions.
        self._reader = sock.makefile("r", encoding="utf-8", newline="\n")
        self._writer = sock.makefile("w", encoding="utf-8", newline="\n")
        self.transport = JsonlTransport(
            self._reader, self._writer, _NullDiagnostics(), schema_version=SCHEMA_VERSION
        )

    def close(self) -> None:
        for closer in (self._reader.close, self._writer.close, self._socket.close):
            try:
                closer()
            except OSError:
                pass


class _NullDiagnostics:
    """Swallows transport diagnostics.

    The v1 transport wrote parse errors to stderr. Over a socket those lines could
    quote an inbound payload, and a payload is the one place a token could appear,
    so nothing from the wire is echoed anywhere.
    """

    def write(self, _message: str) -> int:
        return 0

    def flush(self) -> None:
        return None


def connect_once(
    registration: Registration,
    *,
    discovery_path: Path | None = None,
) -> Session:
    """Read discovery, open the socket, and register. Raises on any failure."""
    discovery = read_discovery(discovery_path)
    sock = socket.create_connection((discovery.host, discovery.port), timeout=CONNECT_TIMEOUT_S)
    # makefile() requires a blocking socket: a file object built over one that
    # still carries a timeout reads from an inconsistent buffer and can miss the
    # welcome entirely. The connect deadline has already done its job by here, and
    # the host's own registration deadline is met by sending immediately.
    sock.settimeout(None)
    session = Session(sock, discovery)
    try:
        session.transport.send(
            register_message(
                discovery,
                renderer_id=registration.renderer_id,
                name=registration.name,
                supported_modes=registration.supported_modes,
                capabilities=registration.capabilities,
            )
        )
    except OSError:
        session.close()
        raise
    return session


def sessions(
    registration: Registration,
    *,
    discovery_path: Path | None = None,
    sleep: Callable[[float], None] | None = None,
    should_continue: Callable[[], bool] | None = None,
    on_wait: Callable[[float, str], None] | None = None,
) -> Iterator[Session]:
    """Yield each registered session, reconnecting with backoff between them.

    The backoff restarts after a session that actually registered, so a host
    restart reconnects promptly while an absent host is retried patiently.
    """
    sleep = sleep or time.sleep
    should_continue = should_continue or (lambda: True)
    delays = backoff_delays()
    while should_continue():
        try:
            session = connect_once(registration, discovery_path=discovery_path)
        except (DiscoveryError, OSError) as exc:
            delay = next(delays)
            if on_wait is not None:
                # Only the reason, never the payload that produced it.
                on_wait(delay, type(exc).__name__)
            sleep(delay)
            continue
        started = time.monotonic()
        try:
            yield session
        finally:
            session.close()
        if time.monotonic() - started >= STABLE_SESSION_S:
            delays = backoff_delays()
        else:
            delay = next(delays)
            if on_wait is not None:
                on_wait(delay, "SessionFlapped")
            sleep(delay)


def messages(session: Session) -> Iterator[dict[str, Any]]:
    """Host events for one session, ending when the socket does."""
    try:
        yield from session.transport.messages()
    except OSError:
        return
