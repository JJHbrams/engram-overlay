# Selectable component bundles

`build-component-bundle.py` creates a core wheel, verified component payload ZIPs, SDK docs ZIP, and one manifest. Only its seven `components` entries are visible choices. CCTV requires the hidden V2 resource payload; it does not advertise V2 as installed. A generation marker limits provider catalog and CLI to selected IDs, while a legacy full wheel/source checkout remains compatible only when all preset modules exist.
