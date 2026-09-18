"""Create local development credentials without printing or overwriting them."""

import os
import secrets
from pathlib import Path

path = Path(".env")
content = "\n".join(
    [
        "MINIO_ROOT_USER=nexora-admin",
        f"MINIO_ROOT_PASSWORD={secrets.token_hex(24)}",
        "NEXORA_S3_ACCESS_KEY=nexora-app",
        f"NEXORA_S3_SECRET_KEY={secrets.token_hex(24)}",
        "NEXORA_S3_BUCKET=nexora-data",
        "NEXORA_DEMO=1",
        "",
    ]
)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write(content)
print(".env créé pour le développement local ; identifiants non affichés.")
