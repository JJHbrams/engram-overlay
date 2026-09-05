"""Finding and authenticating to Engram's Event API v2 host.

Engram no longer starts renderers. It publishes a loopback JSONL server and drops
a discovery file for the current user; a renderer reads it, connects, and
registers itself. Everything about the host can change between runs -- port,
token and instance id are all regenerated on each start -- so nothing here is
cached beyond a single connection attempt.

The token authenticates this user to their own Engram. It must never reach argv,
configuration, logs, errors, or telemetry, so :class:`Discovery` deliberately
hides it from ``repr`` and this module never logs a raw payload.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 2
DISCOVERY_FILE = "overlay-event-api-v2.json"
# The host expects the first line within two seconds of the socket opening.
REGISTER_TIMEOUT_S = 2.0
LOOPBACK = "127.0.0.1"


class DiscoveryError(RuntimeError):
    """The discovery file is absent, unreadable, or does not describe a v2 host."""


@dataclass(frozen=True)
class Discovery:
    """Where this user's Engram is listening, and the secret to get in."""

    host: str
    port: int
    instance_id: str
    token: str = field(repr=False)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.host}:{self.port} instance={self.instance_id}"


def discovery_path() -> Path:
    return Path.home() / ".engram" / DISCOVERY_FILE


def read_discovery(path: Path | None = None) -> Discovery:
    """Read the current host's address and credentials.

    Raises :class:`DiscoveryError` for every failure, including a missing file, so
    a caller's reconnect loop has one thing to catch.
    """
    path = path or discovery_path()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DiscoveryError(f"no discovery file at {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"unreadable discovery file: {exc}") from exc
    if not isinstance(document, dict):
        raise DiscoveryError("discovery must be a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise DiscoveryError(f"unsupported discovery schema {document.get('schema_version')!r}")

    host = document.get("host")
    port = document.get("port")
    instance_id = document.get("instance_id")
    token = document.get("token")
    if host != LOOPBACK:
        # The contract fixes this; anything else means the file is not Engram's.
        raise DiscoveryError(f"discovery host must be {LOOPBACK}")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise DiscoveryError("discovery port must be a TCP port number")
    for name, value in (("instance_id", instance_id), ("token", token)):
        if not isinstance(value, str) or not value:
            raise DiscoveryError(f"discovery {name} must be a non-empty string")
    return Discovery(host=host, port=port, instance_id=instance_id, token=token)


def register_message(
    discovery: Discovery,
    *,
    renderer_id: str,
    name: str,
    supported_modes: tuple[str, ...],
    capabilities: tuple[str, ...] = (),
) -> dict[str, object]:
    """The first line a renderer sends, carrying the discovery credentials."""
    payload: dict[str, object] = {
        "token": discovery.token,
        "instance_id": discovery.instance_id,
        "renderer_id": renderer_id,
        "name": name,
        "supported_modes": list(supported_modes),
    }
    if capabilities:
        payload["capabilities"] = list(capabilities)
    return {"schema_version": SCHEMA_VERSION, "type": "overlay.register", "payload": payload}


def backoff_delays(
    first_s: float = 0.5, ceiling_s: float = 30.0
) -> Iterator[float]:
    """Bounded exponential backoff, restarted by the caller on a good connection.

    Engram may not be running at all -- a renderer starts with the session and
    waits -- so this settles at a ceiling rather than giving up.
    """
    delay = first_s
    while True:
        yield delay
        delay = min(delay * 2, ceiling_s)
