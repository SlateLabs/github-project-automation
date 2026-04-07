from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GatewayResult:
    status_code: int
    body: dict[str, Any]
