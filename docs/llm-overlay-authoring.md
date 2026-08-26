# LLM overlay authoring guide

This is the canonical project guide for an LLM creating a personal Engram external overlay.

## Ownership boundary

Engram owns the Event API, process lifecycle, mode selection, geometry contract, and bundled fallback. This repository's
renderer owns its character, theme, animation, assets, and renderer-specific options. The integration receives semantic
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
manifests/<id>/manifest.yaml            install and selection contract
tests/test_<id>.py                      behavior and registration tests
```

Package assets below the overlay package and declare them in `pyproject.toml`. Never rely on a developer-only absolute
asset path.

## Protocol and window invariants

1. `overlay.hello` is the first stdout line. stdout contains no logs, banners, or tracebacks.
2. Logs go to stderr. Invalid JSONL and unknown events fail soft where the public contract permits.
3. Manifest commands are argv arrays with an absolute installed executable. They are not shell strings.
4. `screen_x` and `screen_y` on drag events describe the window's top-left position, not the raw cursor.
5. `observer` keeps its local visual position and reports geometry; `replace` participates in Engram-owned positioning.
6. Convert between physical screen, Tk client, and logical canvas coordinates explicitly on mixed-DPI Windows systems.
7. A failed renderer must be safe for Engram to terminate and replace with the bundled renderer.

## State and personalization

Map `display_hint` through a safe default expression. Event-triggered expressions should be deterministic enough to
test; idle variation may remain stochastic behind an injectable random source. Personal options belong in validated
renderer arguments or assets, not arbitrary settings injected into Engram.

## Acceptance contract

- The overlay is lazily registered and can start in every declared mode.
- Handshake and outbound envelopes remain schema-valid.
- Unknown input does not terminate the process.
- Pure behavior and geometry have focused tests.
- Packaged assets exist in a built wheel, not only the source tree.
- The full unittest suite passes.
- `scripts/verify-engram.py` passes against an installed manifest and the intended Engram source/runtime.
- No active overlay selection or external release is changed without explicit authorization.

## Useful request shape

An effective creation request states the visual concept, rendering layer if known, pointer/event behavior, required
assets, performance budget, and whether Engram installation or selection is in scope. Missing artistic details may be
chosen by the renderer; missing protocol or privacy details must follow this repository's contract.
