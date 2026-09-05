"""Check that this machine's Engram accepts a renderer connection.

The v1 checks worked by handing Engram a manifest and letting it spawn the
renderer as a child. v2 removed that entirely -- Engram publishes a loopback API
and starts nothing -- so verification is now the same thing a renderer does:
read discovery, connect, register, and see what comes back.

Nothing from Engram's source is imported. A v2 renderer is a client, and needing
the host's code to prove it works would mean it is not one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engram_overlay.client import Registration, connect_once  # noqa: E402
from engram_overlay.discovery import DiscoveryError, discovery_path, read_discovery  # noqa: E402
from engram_overlay.protocol import PRESENTATION_CAPABILITY  # noqa: E402
from engram_overlay.registry import OVERLAYS, overlay_ids, renderer_id  # noqa: E402

# Registering under the real id would take the selection away from a renderer
# the user is actually running, so the probe announces itself as one.
PROBE_SUFFIX = ".verify"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", choices=overlay_ids(), default="xeyes")
    parser.add_argument(
        "--discovery",
        type=Path,
        help="discovery file to use (default: the current user's)",
    )
    parser.add_argument("--json", action="store_true", help="print the welcome payload as JSON")
    args = parser.parse_args()

    path = args.discovery or discovery_path()
    try:
        discovery = read_discovery(path)
    except DiscoveryError as error:
        # Not a failure of this renderer: Engram is simply not running, which a
        # real one waits through rather than reporting.
        print(f"DISCOVERY=ABSENT {error}", file=sys.stderr)
        return 2
    print(f"DISCOVERY=PASS {discovery}")

    spec = OVERLAYS[args.overlay]
    registration = Registration(
        renderer_id=renderer_id(args.overlay) + PROBE_SUFFIX,
        name=f"{spec.name} (verify)",
        capabilities=(PRESENTATION_CAPABILITY,),
    )
    try:
        session = connect_once(registration, discovery_path=path)
    except OSError as error:
        print(f"CONNECT=FAIL {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(f"CONNECT=PASS {registration.renderer_id}")

    try:
        welcome = next(session.transport.messages(), None)
    finally:
        session.close()

    if welcome is None:
        print("REGISTER=FAIL host closed the socket without a welcome", file=sys.stderr)
        return 1
    if welcome.get("type") != "engram.welcome":
        print(f"REGISTER=FAIL first message was {welcome.get('type')!r}", file=sys.stderr)
        return 1

    payload = welcome.get("payload", {})
    print(
        "REGISTER=PASS "
        f"mode={payload.get('mode')} "
        f"schema={payload.get('selected_schema_version')} "
        f"policy={payload.get('content_policy')}"
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
