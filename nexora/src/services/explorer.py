"""Single-process local work queue; credentials never enter browser state."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from uuid import uuid4

from ..ingestion.catalog import scan
from ..ingestion.connection import source_connection
from ..ingestion.extract import extract
from ..ingestion.selection import Selection
from ..storage.minio import publish
from .datasets import activate_collection


class Explorer:
    def __init__(self, source_url, output=None):
        self.source_url = source_url
        self.output = Path(output) if output is not None else None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nexora-explorer")
        self.lock = Lock()
        self.jobs = {}

    def submit(self, kind, payload):
        if kind not in {"scan", "extract", "collect"}:
            raise ValueError("Opération inconnue")
        with self.lock:
            if any(not f.done() for _, f in self.jobs.values()):
                raise ValueError("Un traitement est déjà en cours.")
            # Keep a bounded history. This local queue is intentionally not durable.
            if len(self.jobs) >= 50:
                del self.jobs[next(iter(self.jobs))]
            job = str(uuid4())
            self.jobs[job] = (kind, self.pool.submit(self._run, kind, payload))
            return job

    def _run(self, kind, payload):
        try:
            with source_connection(self.source_url) as conn:
                if kind == "scan":
                    return {"ok": True, "catalog": scan(conn, payload)}
                catalog = None
                if kind == "collect":
                    catalog = scan(conn)
                    payload = {
                        "source_label": payload["source_label"],
                        "objects": [
                            {
                                "schema": obj["schema"],
                                "name": obj["name"],
                                "columns": [col["name"] for col in obj["columns"]],
                                "row_limit": payload["row_limit"],
                            }
                            for obj in catalog["objects"]
                        ],
                    }
                selection = Selection.model_validate(payload)
                if self.output is None:
                    result = publish(conn, selection)
                    result["analysis_updated"] = activate_collection(result) is not None
                    if catalog is not None:
                        result["catalog"] = catalog
                    return result
                run = extract(conn, selection, self.output)
                return {
                    "ok": True,
                    "manifest": json.loads((run / "manifest.json").read_text()),
                    "directory": str(run),
                    **({"catalog": catalog} if catalog is not None else {}),
                }
        except Exception as exc:  # noqa: BLE001 — never expose driver secrets to the UI
            return {
                "ok": False,
                "error": f"Échec ({type(exc).__name__}). Vérifier la connexion, les droits et la sélection.",
            }

    def poll(self, job):
        with self.lock:
            entry = self.jobs.get(job)
        if entry is None:
            return {"ok": False, "error": "Traitement introuvable ; relancer après un redémarrage."}
        return entry[1].result() if entry[1].done() else None

    def close(self):
        self.pool.shutdown(wait=True)
