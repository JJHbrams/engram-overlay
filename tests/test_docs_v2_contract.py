import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V2DocumentationContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_current_guides_name_v2_and_external_process_ownership(self) -> None:
        for relative in (
            "AGENTS.md",
            "docs/architecture.md",
            "docs/development.md",
            "docs/llm-overlay-authoring.md",
        ):
            with self.subTest(relative=relative):
                content = self.read(relative)
                self.assertIn("v2", content.lower())
                self.assertNotIn("Engram child process / JSONL", content)

        authoring = self.read("docs/llm-overlay-authoring.md")
        self.assertIn("external application owns", authoring)
        self.assertIn("Do not create an Engram command manifest", authoring)

    def test_v1_is_explicitly_legacy_test_only(self) -> None:
        content = self.read("docs/event-api-v1.md")
        self.assertIn("Legacy/test-only", content)
        self.assertIn("--v1-stdio", content)

    def test_v2_contract_covers_discovery_reconnect_wire_and_privacy(self) -> None:
        content = self.read("docs/event-api-v2.md")
        for required in (
            "overlay-event-api-v2.json",
            "overlay.register",
            "bounded exponential backoff",
            "schema_version: 2",
            "metadata-only",
            "실행하거나 중지하지 않으며",
        ):
            with self.subTest(required=required):
                self.assertIn(required, content)

    def test_context_menu_history_records_global_hook_reversal(self) -> None:
        content = self.read("docs/engram-side-requests.md")
        self.assertIn("WH_MOUSE_LL", content)
        self.assertIn("전역 입력 지연", content)
        self.assertIn("custom dark nonmodal menu", content)

    def test_catalog_contract_keeps_provider_internals_out_of_engram(self) -> None:
        content = self.read("docs/event-api-v2.md")
        for required in ("최대 32개", "renderer_id", "catalog를 보내지 않는", "현재 item의 mode와 capabilities"):
            with self.subTest(required=required):
                self.assertIn(required, content)
        self.assertIn("Engram은", content)
        self.assertIn("child의 command/path/lifecycle을 전혀 보지 않는다", content)


if __name__ == "__main__":
    unittest.main()
