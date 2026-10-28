"""QR code helpers for scrap loads.

Generates a QR PNG for a load id and returns the bytes. Optional dependency on
the `qrcode` package; if unavailable, returns None and the caller stores the
load id as text.
"""

from __future__ import annotations

import io
from typing import Optional


def make_qr_png(payload: str) -> Optional[bytes]:
    try:
        import qrcode  # type: ignore
        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None
