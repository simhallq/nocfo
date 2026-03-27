"""Screenshot evidence capture for audit trail and debugging."""

from datetime import datetime
from pathlib import Path

import structlog
from playwright.sync_api import Page

logger = structlog.get_logger()


class EvidenceCapture:
    """Captures numbered screenshots during browser operations."""

    def __init__(self, operation: str, base_dir: Path = Path("data/screenshots")) -> None:
        self._dir = base_dir / operation / datetime.now().strftime("%Y%m%d_%H%M%S")
        self._step = 0

    def capture(self, page: Page, label: str) -> Path:
        """Take a screenshot and save it with a numbered label.

        Returns the path to the saved screenshot.
        """
        self._step += 1
        path = self._dir / f"{self._step:03d}_{label}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(path))
            logger.debug("evidence_captured", path=str(path), label=label)
        except Exception as e:
            logger.warning("evidence_capture_failed", label=label, error=str(e))
        return path

    @property
    def directory(self) -> Path:
        return self._dir
