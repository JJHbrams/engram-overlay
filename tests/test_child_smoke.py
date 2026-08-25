import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class ChildSmokeTests(unittest.TestCase):
    def test_headless_child_emits_hello_first(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repository / "src")
        child = subprocess.run(
            [sys.executable, "-m", "engram_overlay", "--headless"],
            input='{"schema_version":1,"type":"state.snapshot","display_hint":"idle","payload":{}}\n',
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            cwd=repository,
            timeout=5,
            check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        first_line = child.stdout.splitlines()[0]
        self.assertEqual(json.loads(first_line)["type"], "overlay.hello")


if __name__ == "__main__":
    unittest.main()

