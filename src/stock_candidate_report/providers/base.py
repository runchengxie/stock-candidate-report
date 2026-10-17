from datetime import datetime
from typing import Protocol

from ..models import ProviderBatch


class Provider(Protocol):
    name: str
    categories: tuple[str, ...]

    def fetch(
        self,
        symbol: str,
        report_year: int,
        now: datetime,
        categories: tuple[str, ...] | None = None,
    ) -> ProviderBatch: ...
