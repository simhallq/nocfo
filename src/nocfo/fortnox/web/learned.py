"""Persistent store for selectors discovered via vision fallback."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


class LearnedSelectors:
    """Thread-safe store for learned selectors persisted to JSON."""

    def __init__(self, path: Path = Path("data/learned_selectors.json")) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._loaded = False

    def _load(self) -> None:
        """Load from disk if not already loaded."""
        if self._loaded:
            return
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("learned_selectors_load_error", error=str(e))
                self._data = {}
        self._loaded = True

    def _save(self) -> None:
        """Write current data to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False))

    def get(self, key: str) -> list[str]:
        """Return learned selectors for a key, ordered by times_used descending."""
        with self._lock:
            self._load()
            entry = self._data.get(key)
            if not entry:
                return []
            return list(entry.get("selectors", []))

    def save(self, key: str, selector: str, **meta: Any) -> None:
        """Persist a working selector. Deduplicates."""
        with self._lock:
            self._load()
            now = datetime.now(timezone.utc).isoformat()
            if key in self._data:
                entry = self._data[key]
                if selector not in entry["selectors"]:
                    entry["selectors"].append(selector)
                entry["learned_at"] = now
                entry["times_used"] = entry.get("times_used", 0)
                entry.update(meta)
            else:
                self._data[key] = {
                    "selectors": [selector],
                    "learned_at": now,
                    "times_used": 0,
                    **meta,
                }
            self._save()
            logger.info("learned_selector_saved", key=key, selector=selector)

    def increment_used(self, key: str) -> None:
        """Increment times_used counter for a key."""
        with self._lock:
            self._load()
            if key in self._data:
                self._data[key]["times_used"] = self._data[key].get("times_used", 0) + 1
                self._save()

    def remove(self, key: str, selector: str) -> None:
        """Remove a failed learned selector. Removes the whole key if empty."""
        with self._lock:
            self._load()
            entry = self._data.get(key)
            if not entry:
                return
            sels = entry.get("selectors", [])
            if selector in sels:
                sels.remove(selector)
            if not sels:
                del self._data[key]
            self._save()
            logger.info("learned_selector_removed", key=key, selector=selector)

    def clear(self, key: str | None = None) -> None:
        """Wipe all learned selectors, or just those for a specific key."""
        with self._lock:
            self._load()
            if key is None:
                self._data = {}
            elif key in self._data:
                del self._data[key]
            self._save()
