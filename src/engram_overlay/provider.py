"""One Event API v2 catalog connection supervising one active v1 worker.

The provider is renderer-owned.  Engram sees stable logical renderer IDs and
never receives a Python path, command, asset path, or worker lifecycle handle.
The private v1 stdio link exists only inside this installed package so the
existing Tk renderers remain isolated and only one of them owns a window.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Any, Protocol, TextIO

from .client import Registration, Session, messages, sessions
from .protocol import ProtocolError, parse_message
from .registry import provider_catalog, renderer_id
from .components import available_overlay_ids

PROVIDER_ID = "engram.catalog-provider"
PROVIDER_NAME = "Engram Overlay Catalog"


class Worker(Protocol):
    def send(self, message: dict[str, Any]) -> None: ...

    def stop(self) -> None: ...


class CatalogWorker:
    """A single preset child speaking the retained, explicit v1 fixture."""

    def __init__(
        self,
        overlay_id: str,
        mode: str,
        emit: Callable[[dict[str, Any]], None],
        *,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        diagnostics: TextIO = sys.stderr,
    ) -> None:
        self._emit = emit
        self._diagnostics = diagnostics
        self._process = popen(
            [
                sys.executable,
                "-m",
                "engram_overlay",
                "--overlay",
                overlay_id,
                "--mode",
                mode,
                "--v1-stdio",
                "--presentation",
                "--provider-worker",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        if self._process.stdin is None or self._process.stdout is None or self._process.stderr is None:
            self.stop()
            raise RuntimeError("catalog worker pipes were not created")
        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        self._stderr = self._process.stderr
        first = self._stdout.readline()
        try:
            hello = parse_message(first, schema_version=1)
        except ProtocolError as exc:
            self.stop()
            raise RuntimeError("catalog worker did not provide a v1 hello") from exc
        if hello.get("type") != "overlay.hello":
            self.stop()
            raise RuntimeError("catalog worker did not provide a v1 hello")
        second = self._stdout.readline()
        try:
            ready = parse_message(second, schema_version=1)
        except ProtocolError as exc:
            self.stop()
            raise RuntimeError("catalog worker did not become ready") from exc
        if ready.get("type") != "renderer.worker_ready" or ready.get("payload") != {}:
            self.stop()
            raise RuntimeError("catalog worker did not become ready")
        self._write_lock = threading.Lock()
        threading.Thread(target=self._read_stdout, name="engram-catalog-worker", daemon=True).start()
        threading.Thread(target=self._read_stderr, name="engram-catalog-diagnostics", daemon=True).start()

    def _read_stdout(self) -> None:
        for line in self._stdout:
            if not line.strip():
                continue
            try:
                message = parse_message(line, schema_version=1)
            except ProtocolError:
                continue
            self._emit(message)

    def _read_stderr(self) -> None:
        for line in self._stderr:
            # Worker diagnostics contain no discovery material: the child never
            # receives the v2 discovery file, token, instance id, host or port.
            self._diagnostics.write(line)
            self._diagnostics.flush()

    def send(self, message: dict[str, Any]) -> None:
        outbound = dict(message)
        outbound["schema_version"] = 1
        encoded = json.dumps(outbound, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            self._stdin.write(encoded + "\n")
            self._stdin.flush()

    def stop(self) -> None:
        process = getattr(self, "_process", None)
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)


class CatalogProvider:
    """Reduce host selection to one active child and relay metadata events."""

    def __init__(self, worker_factory: Callable[[str, str, Callable[[dict[str, Any]], None]], Worker] = CatalogWorker) -> None:
        self._worker_factory = worker_factory
        self._worker: Worker | None = None
        self._overlay_id: str | None = None
        self._mode: str | None = None
        self._worker_visible: bool | None = None
        self._transport: Any = None
        self._snapshot: dict[str, Any] | None = None
        self._lock = threading.RLock()
        self._generation = 0
        self._logical_to_overlay = {renderer_id(overlay_id): overlay_id for overlay_id in available_overlay_ids()}

    def attach(self, session: Session) -> None:
        with self._lock:
            self._transport = session.transport

    def detach(self, session: Session) -> None:
        with self._lock:
            if self._transport is session.transport:
                self._transport = None

    def emit(self, message: dict[str, Any]) -> None:
        with self._lock:
            if message.get("type") == "overlay.visibility_changed":
                payload = message.get("payload")
                if isinstance(payload, dict) and isinstance(payload.get("visible"), bool):
                    self._worker_visible = payload["visible"]
            transport = self._transport
        if transport is not None:
            try:
                transport.send(message)
            except OSError:
                pass

    def _emit_generation(self, generation: int, message: dict[str, Any]) -> None:
        """Drop late output from a child that was replaced by another preset."""
        with self._lock:
            if generation != self._generation:
                return
        self.emit(message)

    def handle(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "state.snapshot":
            with self._lock:
                self._snapshot = message
                worker = self._worker
            if worker is not None:
                worker.send(message)
            return
        if message_type == "renderer.assignment":
            self._assign(message)
            return
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.send(message)
            # Every catalog worker is created hidden. Tk intentionally treats a
            # repeated hide as idempotent and emits no second callback, so the
            # supervisor acknowledges that already-complete state only after
            # the host's hide request has arrived.
            if message_type == "overlay.hide":
                with self._lock:
                    already_hidden = self._worker_visible is False
                if already_hidden:
                    self.emit({"schema_version": 2, "type": "overlay.visibility_changed", "payload": {"visible": False}})

    def _assign(self, message: dict[str, Any]) -> None:
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return
        selected = payload.get("selected")
        logical_id = payload.get("renderer_id")
        mode = payload.get("mode")
        if selected is not True or logical_id not in self._logical_to_overlay or mode not in {"observer", "replace"}:
            if selected is False:
                self._replace_worker(None, None, None)
            return
        overlay_id = self._logical_to_overlay[logical_id]
        with self._lock:
            current = self._worker
            same_worker = current is not None and self._overlay_id == overlay_id
            if same_worker:
                self._mode = mode
        if same_worker:
            current.send(message)
            self.emit({"schema_version": 2, "type": "renderer.ready", "payload": {"renderer_id": logical_id}})
            return
        self._replace_worker(overlay_id, mode, message)

    def _replace_worker(
        self,
        overlay_id: str | None,
        mode: str | None,
        assignment: dict[str, Any] | None,
    ) -> None:
        with self._lock:
            old = self._worker
            self._generation += 1
            generation = self._generation
            self._worker = None
            self._overlay_id = None
            self._mode = None
            self._worker_visible = None
            snapshot = self._snapshot
        if old is not None:
            old.stop()
        if overlay_id is None or mode is None or assignment is None:
            return
        try:
            worker = self._worker_factory(
                overlay_id,
                mode,
                lambda message: self._emit_generation(generation, message),
            )
        except Exception:  # noqa: BLE001 - keep the provider available for another selection
            sys.stderr.write("catalog worker failed to start; bundled fallback remains active\n")
            sys.stderr.flush()
            return
        with self._lock:
            self._worker = worker
            self._overlay_id = overlay_id
            self._mode = mode
            self._worker_visible = False
        if snapshot is not None:
            worker.send(snapshot)
        worker.send(assignment)
        self.emit({"schema_version": 2, "type": "renderer.ready", "payload": {"renderer_id": renderer_id(overlay_id)}})

    def close(self) -> None:
        self._replace_worker(None, None, None)


def catalog_registration() -> Registration:
    return Registration(
        renderer_id=PROVIDER_ID,
        name=PROVIDER_NAME,
        supported_modes=("observer", "replace"),
        catalog=provider_catalog(),
    )


def run_catalog_provider(
    *,
    session_stream: Iterator[Session] | None = None,
    provider: CatalogProvider | None = None,
) -> int:
    supervisor = provider or CatalogProvider()
    stream = session_stream or sessions(catalog_registration())
    try:
        for session in stream:
            supervisor.attach(session)
            try:
                for message in messages(session):
                    supervisor.handle(message)
            finally:
                supervisor.detach(session)
    finally:
        supervisor.close()
    return 0
