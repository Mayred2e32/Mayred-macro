from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .events import MacroRecording

MACRO_ROOT = (Path(__file__).resolve().parent.parent / "macro_recordings").resolve()


def _slugify(value: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in value.strip().lower())
    condensed = "-".join(filter(None, safe.split("-")))
    return condensed or "macro"


class MacroStorage:
    def __init__(self, root: Path = MACRO_ROOT):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def list_recordings(self) -> List[Dict[str, str]]:
        summaries: List[Dict[str, str]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    header = json.load(handle)
            except Exception:
                continue
            summaries.append(
                {
                    "name": header.get("name", path.stem),
                    "slug": path.stem,
                    "created": header.get("created_at", 0.0),
                }
            )
        return summaries

    def save(self, recording: MacroRecording, name: Optional[str] = None) -> Path:
        slug_source = name or recording.name
        slug = _slugify(slug_source)
        path = self.root / f"{slug}.json"
        payload = recording.to_dict()
        payload.setdefault("saved_at", datetime.utcnow().isoformat() + "Z")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        return path

    def load(self, slug: str) -> MacroRecording:
        path = self.root / f"{slug}.json"
        if not path.exists():
            raise FileNotFoundError(f"Macro '{slug}' not found")
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return MacroRecording.from_dict(payload)

    def delete(self, slug: str) -> None:
        path = self.root / f"{slug}.json"
        if path.exists():
            path.unlink()


__all__ = ["MacroStorage", "MACRO_ROOT"]
