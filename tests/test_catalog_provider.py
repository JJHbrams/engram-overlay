import io
import json
import unittest
from contextlib import redirect_stderr

from engram_overlay.provider import CatalogProvider, CatalogWorker, catalog_registration
from engram_overlay.registry import OVERLAYS, provider_catalog, renderer_id


def event(message_type, **payload):
    return {"schema_version": 2, "type": message_type, "display_hint": "idle", "payload": payload}


class FakeWorker:
    def __init__(self, overlay_id, mode, emit):
        self.overlay_id = overlay_id
        self.mode = mode
        self.emit = emit
        self.sent = []
        self.stopped = 0

    def send(self, message):
        self.sent.append(message)

    def stop(self):
        self.stopped += 1


class FakeTransport:
    def __init__(self):
        self.sent = []

    def send(self, message):
        outbound = dict(message)
        outbound["schema_version"] = 2
        self.sent.append(outbound)


class CatalogContractTests(unittest.TestCase):
    def test_catalog_advertises_all_stable_ids_and_presentation(self):
        catalog = provider_catalog()
        self.assertEqual(len(catalog), 7)
        self.assertEqual(
            {item["renderer_id"] for item in catalog},
            {renderer_id(overlay_id) for overlay_id in OVERLAYS},
        )
        for item in catalog:
            with self.subTest(item=item["renderer_id"]):
                self.assertEqual(item["supported_modes"], ["observer", "replace"])
                self.assertIn("overlay.presentation", item["capabilities"])

    def test_registration_is_one_provider_with_the_bounded_catalog(self):
        registration = catalog_registration()
        self.assertEqual(registration.renderer_id, "engram.catalog-provider")
        self.assertEqual(registration.catalog, provider_catalog())
        self.assertLessEqual(len(registration.catalog), 32)


class CatalogProviderTests(unittest.TestCase):
    def setUp(self):
        self.workers = []

        def factory(overlay_id, mode, emit):
            worker = FakeWorker(overlay_id, mode, emit)
            self.workers.append(worker)
            return worker

        self.provider = CatalogProvider(factory)

    def tearDown(self):
        self.provider.close()

    def test_initial_three_message_sequence_starts_selected_item_snapshot_first(self):
        class Session:
            transport = FakeTransport()

        session = Session()
        self.provider.attach(session)
        self.provider.handle(event("engram.welcome", selected=True, mode="replace"))
        snapshot = event("state.snapshot", tool_category="search")
        self.provider.handle(snapshot)
        assignment = event(
            "renderer.assignment", selected=True, mode="replace", renderer_id="engram.rabbit-2d"
        )
        self.provider.handle(assignment)

        self.assertEqual([(worker.overlay_id, worker.mode) for worker in self.workers], [("rabbit-2d", "replace")])
        self.assertEqual(self.workers[0].sent, [snapshot, assignment])
        self.assertEqual(session.transport.sent, [{
            "schema_version": 2,
            "type": "renderer.ready",
            "payload": {"renderer_id": "engram.rabbit-2d"},
        }])

    def test_selection_switches_worker_but_same_item_reuses_it(self):
        self.provider.handle(event("renderer.assignment", selected=True, mode="observer", renderer_id="engram.xeyes"))
        first = self.workers[0]
        self.provider.handle(event("renderer.assignment", selected=True, mode="replace", renderer_id="engram.xeyes"))
        self.assertEqual(len(self.workers), 1)
        self.assertEqual(first.stopped, 0)

        self.provider.handle(event("renderer.assignment", selected=True, mode="replace", renderer_id="engram.robot-arm"))
        self.assertEqual(first.stopped, 1)
        self.assertEqual(self.workers[1].overlay_id, "robot-arm")

    def test_unselected_assignment_stops_the_active_item(self):
        self.provider.handle(event("renderer.assignment", selected=True, mode="replace", renderer_id="engram.xeyes"))
        worker = self.workers[0]
        self.provider.handle(event("renderer.assignment", selected=False, mode="observer"))
        self.assertEqual(worker.stopped, 1)

    def test_worker_start_failure_sends_no_ready_and_keeps_provider_alive(self):
        provider = CatalogProvider(lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))

        class Session:
            transport = FakeTransport()

        session = Session()
        provider.attach(session)
        with redirect_stderr(io.StringIO()):
            provider.handle(event("renderer.assignment", selected=True, mode="replace", renderer_id="engram.xeyes"))
        self.assertEqual(session.transport.sent, [])
        provider.handle(event("engram.welcome", selected=True, mode="observer"))
        provider.close()

    def test_worker_output_uses_the_current_v2_session(self):
        class Session:
            transport = FakeTransport()

        session = Session()
        self.provider.attach(session)
        self.provider.handle(event("renderer.assignment", selected=True, mode="replace", renderer_id="engram.xeyes"))
        self.workers[0].emit({"schema_version": 1, "type": "overlay.visibility_changed", "payload": {"visible": False}})
        self.assertEqual(session.transport.sent[-1]["schema_version"], 2)
        self.assertEqual(session.transport.sent[-1]["type"], "overlay.visibility_changed")

    def test_initial_already_hidden_worker_acks_only_after_host_hide(self):
        class Session:
            transport = FakeTransport()

        session = Session()
        self.provider.attach(session)
        self.provider.handle(event("renderer.assignment", selected=True, mode="replace", renderer_id="engram.xeyes"))
        self.assertEqual([message["type"] for message in session.transport.sent], ["renderer.ready"])
        self.provider.handle(event("overlay.hide"))
        self.assertEqual(
            [message["type"] for message in session.transport.sent],
            ["renderer.ready", "overlay.visibility_changed"],
        )
        self.assertEqual(session.transport.sent[-1]["payload"], {"visible": False})

    def test_late_output_from_replaced_item_is_dropped(self):
        class Session:
            transport = FakeTransport()

        session = Session()
        self.provider.attach(session)
        self.provider.handle(event("renderer.assignment", selected=True, mode="replace", renderer_id="engram.xeyes"))
        old = self.workers[0]
        self.provider.handle(event("renderer.assignment", selected=True, mode="replace", renderer_id="engram.rabbit-2d"))
        session.transport.sent.clear()
        old.emit({"schema_version": 1, "type": "overlay.geometry_changed", "payload": {"x": 1, "y": 2, "width": 3, "height": 4}})
        self.assertEqual(session.transport.sent, [])


class FakeProcess:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stderr = io.StringIO()
        self.stdout = io.StringIO(
            json.dumps({"schema_version": 1, "type": "overlay.hello", "payload": {}}) + "\n" +
            json.dumps({"schema_version": 1, "type": "renderer.worker_ready", "payload": {}}) + "\n"
        )
        self.args = None
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


class WorkerBridgeTests(unittest.TestCase):
    def test_worker_is_private_v1_stdio_and_launcher_managed(self):
        process = FakeProcess()

        def popen(args, **kwargs):
            process.args = args
            return process

        worker = CatalogWorker("rabbit-2d", "replace", lambda message: None, popen=popen)
        self.addCleanup(worker.stop)
        self.assertIn("--v1-stdio", process.args)
        self.assertIn("--presentation", process.args)
        self.assertEqual(process.args[process.args.index("--overlay") + 1], "rabbit-2d")
        worker.send(event("overlay.hide"))
        written = json.loads(process.stdin.getvalue())
        self.assertEqual(written["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
