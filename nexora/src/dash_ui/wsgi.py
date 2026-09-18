import os
from pathlib import Path

from .app import create_app

is_demo = os.environ.get("NEXORA_DEMO") == "1"
if is_demo:
    source = Path("/app/data/enterprise.sqlite")
    if not source.is_file():
        raise RuntimeError("Charger le DW avec nexora-demo avant de démarrer en mode démo.")
    source_url = f"sqlite:///{source}"
else:
    source_url = os.environ.get("NEXORA_SOURCE_URL") or None

# Startup never generates, extracts or loads demonstration results.
server = create_app(source_url, demo=is_demo).server
