import os
from pathlib import Path

from ..demo.generate import generate
from .app import create_app

is_demo = os.environ.get("NEXORA_DEMO") == "1"
if is_demo:
    source = Path("/app/data/enterprise.sqlite")
    if not source.exists():
        generate(source)
    source_url = f"sqlite:///{source}"
else:
    source_url = os.environ.get("NEXORA_SOURCE_URL")
    if not source_url:
        raise RuntimeError("Définir NEXORA_SOURCE_URL pour la source SQL.")
server = create_app(source_url, demo=is_demo).server
