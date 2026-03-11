"""Fortnox Inbox API — upload files for attachment to vouchers/invoices."""

from pathlib import Path
from typing import Any

import structlog

from nocfo.fortnox.client import FortnoxClient

logger = structlog.get_logger()

MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB

# Fortnox inbox accepts these MIME types
ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
}


class InboxService:
    """Upload files to the Fortnox Inbox."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def upload(self, file_path: Path) -> str:
        """Upload a file to the Fortnox Inbox.

        Returns the Fortnox file ID for use with FileConnectionService.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Evidence file not found: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{suffix}'. "
                f"Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        file_size = file_path.stat().st_size
        if file_size > MAX_UPLOAD_SIZE:
            raise ValueError(
                f"File too large ({file_size / 1024 / 1024:.1f} MB). "
                f"Maximum: {MAX_UPLOAD_SIZE / 1024 / 1024:.0f} MB"
            )

        content_type = ALLOWED_EXTENSIONS[suffix]
        file_bytes = file_path.read_bytes()

        # Fortnox Inbox upload uses multipart form
        data = await self._client.upload_file(
            path="/inbox",
            filename=file_path.name,
            file_bytes=file_bytes,
            content_type=content_type,
        )

        file_id = data["File"]["Id"]
        logger.info("file_uploaded_to_inbox", file_id=file_id, filename=file_path.name)
        return file_id

    async def list(self) -> list[dict[str, Any]]:
        """List files in the inbox."""
        data = await self._client.get("/inbox")
        return data.get("Files", [])
