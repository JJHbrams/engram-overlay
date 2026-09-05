# Engram overlay agent instructions

Before creating or changing an overlay, read `docs/llm-overlay-authoring.md` and the relevant sections of
`docs/event-api-v1.md`. Read `docs/architecture.md` when choosing or changing a rendering backend.

## Non-negotiable contract

- stdout is JSONL protocol only. Send `overlay.hello` as the first line and write diagnostics to stderr.
- Consume metadata-only events. Do not request or infer conversation text, thinking, tool payloads, or file paths.
- Keep Engram-owned protocol/lifecycle behavior in shared code and artwork-specific behavior inside the overlay.
- Treat unknown event types and fields as forward-compatible input.
- Never introduce shell command strings or arbitrary command execution.
- Read the host's address and token from the discovery file only. Keep the token out of argv, config, logs and errors.
- Preserve both `observer` and `replace` semantics. Do not persist observer-local drag as Engram's bundled rect.
- Keep screen coordinates, client coordinates, and mixed-DPI conversions explicit.

## Authoring workflow

For a small Tk overlay, start with:

```powershell
python scripts/scaffold-overlay.py <overlay-id> --name "Display Name" --dry-run
python scripts/scaffold-overlay.py <overlay-id> --name "Display Name"
```

For software 3D, GPU 3D, WebView, or Live2D work, choose the backend first and scaffold manually from the nearest
existing implementation. Do not force those runtimes through the Tk starter.

Every overlay change must include focused behavior tests and pass:

```powershell
python -m unittest discover -s tests
python scripts/verify-connection.py --overlay <id>
```

`verify-connection.py` needs a running Engram and exits 2 when there is none, which is not a failure of the change.

Do not change the user's installed Engram selection, publish a release, or add large generated assets unless the
request explicitly includes that action.
