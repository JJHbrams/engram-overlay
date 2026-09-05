"""Discovery, registration and the reconnect loop, against a stub host.

Never against a live Engram: a renderer has to be provable without a running
host, and the interesting cases -- absent file, dead port, refused registration
-- cannot be produced from one.
"""

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from engram_overlay.client import Registration, connect_once, sessions
from engram_overlay.discovery import (
    Discovery,
    DiscoveryError,
    backoff_delays,
    read_discovery,
    register_message,
)

TOKEN = "stub-token-not-a-real-credential"
INSTANCE = "stub-instance"

WELCOME = {
    "schema_version": 2,
    "type": "engram.welcome",
    "display_hint": "idle",
    "payload": {
        "selected_schema_version": 2,
        "mode": "replace",
        "content_policy": "metadata_only",
        "host_instance_id": INSTANCE,
    },
}
SNAPSHOT = {"schema_version": 2, "type": "state.snapshot", "display_hint": "idle", "payload": {}}


class StubHost:
    """A loopback server that accepts a registration and replies like Engram."""

    def __init__(self, replies=None, accept=True):
        self.replies = [WELCOME, SNAPSHOT] if replies is None else replies
        self.accept = accept
        self.registered = []
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(2)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with conn:
                # A makefile holds the connection open past conn.close(), so every
                # file object is closed explicitly or the client never sees EOF.
                reader = conn.makefile("r", encoding="utf-8", newline="\n")
                try:
                    first = reader.readline()
                    if not first:
                        continue
                    self.registered.append(json.loads(first))
                    if not self.accept:
                        continue
                    writer = conn.makefile("w", encoding="utf-8", newline="\n")
                    try:
                        for reply in self.replies:
                            writer.write(json.dumps(reply) + "\n")
                        writer.flush()
                    finally:
                        writer.close()
                finally:
                    reader.close()

    def discovery_file(self):
        return write_discovery(port=self.port)

    def close(self):
        self._server.close()


def write_discovery(**overrides):
    document = {
        "schema_version": 2,
        "host": "127.0.0.1",
        "port": 49152,
        "instance_id": INSTANCE,
        "token": TOKEN,
    }
    document.update(overrides)
    path = Path(tempfile.mkdtemp()) / "overlay-event-api-v2.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class DiscoveryTests(unittest.TestCase):
    def test_a_valid_file_is_read(self) -> None:
        found = read_discovery(write_discovery())
        self.assertEqual((found.host, found.port, found.instance_id), ("127.0.0.1", 49152, INSTANCE))
        self.assertEqual(found.token, TOKEN)

    def test_the_token_stays_out_of_repr_and_str(self) -> None:
        """The contract forbids the token reaching logs, and repr is how it leaks."""
        found = read_discovery(write_discovery())
        self.assertNotIn(TOKEN, repr(found))
        self.assertNotIn(TOKEN, str(found))

    def test_a_missing_file_is_a_discovery_error(self) -> None:
        with self.assertRaises(DiscoveryError):
            read_discovery(Path(tempfile.mkdtemp()) / "absent.json")

    def test_a_non_loopback_host_is_refused(self) -> None:
        for host in ("0.0.0.0", "10.0.0.5", "localhost"):
            with self.subTest(host=host), self.assertRaises(DiscoveryError):
                read_discovery(write_discovery(host=host))

    def test_a_bad_port_is_refused(self) -> None:
        for port in (0, -1, 70000, "49152", True):
            with self.subTest(port=port), self.assertRaises(DiscoveryError):
                read_discovery(write_discovery(port=port))

    def test_a_v1_or_unknown_schema_is_refused(self) -> None:
        for version in (1, 3, None, "2"):
            with self.subTest(version=version), self.assertRaises(DiscoveryError):
                read_discovery(write_discovery(schema_version=version))

    def test_empty_credentials_are_refused(self) -> None:
        for field in ("token", "instance_id"):
            with self.subTest(field=field), self.assertRaises(DiscoveryError):
                read_discovery(write_discovery(**{field: ""}))

    def test_broken_json_is_a_discovery_error(self) -> None:
        path = Path(tempfile.mkdtemp()) / "d.json"
        path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(DiscoveryError):
            read_discovery(path)


class RegisterMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.discovery = Discovery("127.0.0.1", 49152, INSTANCE, TOKEN)

    def test_it_carries_exactly_the_required_fields(self) -> None:
        message = register_message(
            self.discovery, renderer_id="a.b", name="B", supported_modes=("observer",)
        )
        self.assertEqual(message["schema_version"], 2)
        self.assertEqual(message["type"], "overlay.register")
        self.assertEqual(
            set(message["payload"]),
            {"token", "instance_id", "renderer_id", "name", "supported_modes"},
        )

    def test_capabilities_are_omitted_when_empty(self) -> None:
        """The field is optional, and the host rejects extra fields."""
        message = register_message(
            self.discovery, renderer_id="a.b", name="B", supported_modes=("replace",)
        )
        self.assertNotIn("capabilities", message["payload"])

    def test_capabilities_are_included_when_given(self) -> None:
        message = register_message(
            self.discovery,
            renderer_id="a.b",
            name="B",
            supported_modes=("replace",),
            capabilities=("overlay.presentation",),
        )
        self.assertEqual(message["payload"]["capabilities"], ["overlay.presentation"])


class BackoffTests(unittest.TestCase):
    def test_it_doubles_then_settles_at_the_ceiling(self) -> None:
        delays = backoff_delays(first_s=0.5, ceiling_s=8.0)
        self.assertEqual([next(delays) for _ in range(7)], [0.5, 1.0, 2.0, 4.0, 8.0, 8.0, 8.0])


class ConnectTests(unittest.TestCase):
    def registration(self):
        return Registration(
            renderer_id="engram.stub", name="Stub", capabilities=("overlay.presentation",)
        )

    def test_it_registers_then_receives_the_welcome(self) -> None:
        host = StubHost()
        self.addCleanup(host.close)
        session = connect_once(self.registration(), discovery_path=host.discovery_file())
        self.addCleanup(session.close)
        first = next(session.transport.messages())
        self.assertEqual(first["type"], "engram.welcome")
        self.assertEqual(host.registered[0]["payload"]["renderer_id"], "engram.stub")
        self.assertEqual(host.registered[0]["payload"]["token"], TOKEN)

    def test_a_dead_port_raises_rather_than_hanging(self) -> None:
        host = StubHost()
        port = host.port
        host.close()
        with self.assertRaises(OSError):
            connect_once(self.registration(), discovery_path=write_discovery(port=port))

    def test_a_refused_registration_yields_no_events(self) -> None:
        host = StubHost(accept=False)
        self.addCleanup(host.close)
        session = connect_once(self.registration(), discovery_path=host.discovery_file())
        self.addCleanup(session.close)
        self.assertEqual(list(session.transport.messages()), [])

    def test_the_loop_waits_instead_of_raising_when_there_is_no_host(self) -> None:
        """Engram may start long after the renderer; that is the normal case."""
        waited = []
        attempts = {"n": 0}

        def counting_continue():
            attempts["n"] += 1
            return attempts["n"] <= 3

        loop = sessions(
            self.registration(),
            discovery_path=Path(tempfile.mkdtemp()) / "absent.json",
            sleep=waited.append,
            should_continue=counting_continue,
        )
        self.assertEqual(list(loop), [])
        self.assertEqual(waited, [0.5, 1.0, 2.0])

    def test_the_loop_yields_a_session_once_a_host_is_there(self) -> None:
        host = StubHost()
        self.addCleanup(host.close)
        served = []
        loop = sessions(
            self.registration(),
            discovery_path=host.discovery_file(),
            sleep=served.append,
            should_continue=lambda: True,
        )
        session = next(loop)
        self.assertEqual(next(session.transport.messages())["type"], "engram.welcome")
        self.assertEqual(served, [])
        loop.close()

    def test_the_reason_reaches_the_caller_without_the_payload(self) -> None:
        """A wait may be reported; the credentials that caused it may not."""
        notes = []
        attempts = {"n": 0}

        def once():
            attempts["n"] += 1
            return attempts["n"] <= 1

        list(
            sessions(
                self.registration(),
                discovery_path=Path(tempfile.mkdtemp()) / "absent.json",
                sleep=lambda _delay: None,
                should_continue=once,
                on_wait=lambda delay, reason: notes.append((delay, reason)),
            )
        )
        self.assertEqual(notes, [(0.5, "DiscoveryError")])


if __name__ == "__main__":
    unittest.main()
