---
name: create-engram-overlay
description: Create or extend a personal renderer in the engram-overlay repository, including backend selection, registry entry, roster entry, focused tests, and Engram Event API verification. Use for new 2D, software-3D, GPU-3D, WebView, or Live2D overlays; not for ordinary bug fixes to an existing overlay.
---

# Create an Engram overlay

Read the repository `AGENTS.md` and `docs/llm-overlay-authoring.md` before editing. Read `docs/architecture.md` when
the requested rendering technology is not already fixed, and read `docs/event-api-v1.md` before changing protocol or
input behavior.

## Choose the layer

- Small functional 2D or layered bitmap: use the existing Tk host.
- Perspective-rendered low-poly art: reuse `scene3d.py` and `software_uv.py` only when CPU software rendering is an
  explicit fit.
- Arbitrary realtime 3D: add or reuse a dedicated GPU backend; do not describe a shaded 2D canvas as full 3D.
- Live2D or browser runtime: isolate its dependencies behind a WebView/backend module.

Keep artwork, animation, assets, and renderer-specific settings in the overlay. Keep JSONL transport, lifecycle,
geometry, and shared pointer envelopes in common layers.

## Implement

For a new Tk overlay, run the scaffold in dry-run mode first, then apply it:

```powershell
python scripts/scaffold-overlay.py <overlay-id> --name "Display Name" --dry-run
python scripts/scaffold-overlay.py <overlay-id> --name "Display Name"
```

The scaffold creates a module, focused test, registry entry, and roster entry. Replace its visual placeholder with the
requested behavior; do not remove its lifecycle methods or protocol boundary.

For other backends, copy only the nearest relevant structure and register a lazy-loaded factory. Add dependencies as
backend-specific optional dependencies where practical.

## Verify

Test pure geometry, state mapping, and constraints without a window. Add a small smoke test only for lifecycle behavior
that cannot be covered headlessly. Then run the full suite and the connection check from `AGENTS.md`.

Do not mutate the user's active Engram selection unless explicitly requested. Report which backend, files, tests, and
runtime evidence were used.
