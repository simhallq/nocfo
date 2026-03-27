"""Token persistence as plain JSON (gitignored)."""

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

DEFAULT_TOKEN_PATH = Path("data/tokens.json")


class TokenStore:
    """File-based token storage."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_TOKEN_PATH

    def save(self, token_data: dict[str, Any]) -> None:
        """Save token data to file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(token_data, indent=2))
        self._path.chmod(0o600)
        logger.debug("tokens_saved", path=str(self._path))

    def load(self) -> dict[str, Any] | None:
        """Load token data from file."""
        if not self._path.exists():
            logger.debug("no_token_file", path=str(self._path))
            return None

        try:
            return json.loads(self._path.read_text())  # type: ignore[no-any-return]
        except Exception as e:
            logger.error("token_load_failed", error=str(e))
            return None

    def delete(self) -> None:
        """Delete the token file."""
        if self._path.exists():
            self._path.unlink()
            logger.info("tokens_deleted", path=str(self._path))
