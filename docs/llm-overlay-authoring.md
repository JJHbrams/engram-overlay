# LLM overlay authoring guide

This is the canonical project guide for an LLM creating a personal Engram external overlay.

## Ownership boundary

Engram owns the Event API host, mode selection, geometry contract, and bundled fallback. The external application owns
its renderer process, startup, restart, installation path, arguments, character, theme, animation, assets, and
renderer-specific options. Engram does not launch, stop, locate, or configure that process. The integration receives semantic
metadata only; it must not depend on conversation text, thinking, tool arguments/results, or user file paths.

## Pick the rendering layer

| Desired result | Starting point | Notes |
| --- | --- | --- |
| Functional 2D, sprites, layered images | `backends/tk.py`, `overlays/xeyes.py` | Small dependency footprint and easy headless math tests |
| Articulated 2D mechanism | `overlays/robot_arm.py` | Keep IK and expression mapping pure where possible |
| Fixed-camera software 3D | `scene3d.py`, `overlays/robot_arm_3d.py` | CPU projection/depth sort; suitable for restrained mesh counts |
| Textured low-poly software 3D | `software_uv.py`, `overlays/robot_arm_3d_v2.py` | Package texture atlases and test their presence |
| Arbitrary realtime 3D | new dedicated GPU backend | Own a real scene/camera/depth pipeline; do not overload Tk abstractions |
| Live2D or browser renderer | new WebView/backend module | Isolate runtime and model dependencies from other overlays |

An overlay shares only `OverlayRunner.run()`, `JsonlTransport`, and semantic state. It does not need to mimic another
overlay's view class.

## Required files

```text
src/engram_overlay/overlays/<id>.py     renderer behavior and factory
src/engram_overlay/registry.py          lazy-loaded id/backend/factory mapping
tests/roster.json                       display name and renderer id snapshot
tests/test_<id>.py                      behavior and registration tests
```

Package assets below the overlay package and declare them in `pyproject.toml`. Never rely on a developer-only absolute
asset path.

## Protocol and window invariants

1. The default is Event API v2: read `~/.engram/overlay-event-api-v2.json`, connect to its loopback endpoint,
   send `overlay.register` first, and reconnect with bounded backoff after either startup order or host restart.
2. Protocol uses the TCP socket. Logs go to stderr; token, instance credentials, and wire payloads do not.
   Invalid JSONL and unknown events fail soft where the public contract permits.
3. The external application owns launch and installation. Do not create an Engram command manifest or depend on
   Engram knowing an executable, argv, cwd, asset path, or virtual environment.
4. `screen_x` and `screen_y` on drag events describe the window's top-left position, not the raw cursor.
5. `observer` keeps its local visual position and reports geometry; `replace` participates in Engram-owned positioning.
6. A renderer may advertise `"overlay.set_size"` in `overlay.register.payload.capabilities`. Only an opted-in selected `replace` renderer then receives physical `width`/`height` requests; preserve its artwork aspect ratio, bound the result, and emit `overlay.geometry_changed` after applying it. Observer mode receives no size request.
7. Convert between physical screen, Tk client, and logical canvas coordinates explicitly on mixed-DPI Windows systems.
8. A disconnected renderer yields ownership to Engram's bundled fallback. Engram does not terminate the external process;
   the renderer remains responsible for its lifecycle and reconnect.

`--v1-stdio` preserves the old `overlay.hello` stdin/stdout protocol for legacy tests only. Do not use it as the
normal installation or ownership model.

## State and personalization

Map `display_hint` through a safe default expression. Event-triggered expressions should be deterministic enough to
test; idle variation may remain stochastic behind an injectable random source. Personal options belong in validated
renderer arguments or assets, not arbitrary settings injected into Engram.

## Acceptance contract

- The overlay is lazily registered and can start in every declared mode.
- v2 registration and every outbound envelope remain schema-valid; explicit v1 stdio remains schema 1.
- Unknown input does not terminate the process.
- Pure behavior and geometry have focused tests.
- Packaged assets exist in a built wheel, not only the source tree.
- The full unittest suite passes.
- `scripts/verify-connection.py` registers with a running Engram, or reports exit 2 because none is running.
- No active overlay selection or external release is changed without explicit authorization.

## Useful request shape

An effective creation request states the visual concept, rendering layer if known, pointer/event behavior, required
assets, performance budget, and whether Engram installation or selection is in scope. Missing artistic details may be
chosen by the renderer; missing protocol or privacy details must follow this repository's contract.
