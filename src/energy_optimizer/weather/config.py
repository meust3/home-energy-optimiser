"""Optional collection settings. Disabled means no network or archive writes."""

import hashlib
import math
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeatherCollectionConfig:
    enabled: bool = False
    provider_cap_confirmed: bool = False
    provider_daily_cap: int = 1000
    interval_minutes: int = 10
    max_pages: int = 5
    local_attempt_cap: int = 900
    account_ref: str = "openweather_primary"
    api_key: str = field(default="", repr=False)
    latitude: float | None = field(default=None, repr=False)
    longitude: float | None = field(default=None, repr=False)

    @property
    def scope(self) -> str:
        # A location/key change cannot resume a different configuration's cycle.
        return hashlib.sha256(
            f"{self.latitude}|{self.longitude}|{self.api_key}".encode()
        ).hexdigest()

    @property
    def ready(self) -> bool:
        return (
            self.enabled
            and self.provider_cap_confirmed
            and self.provider_daily_cap == 1000
            and self.interval_minutes == 10
            and self.max_pages == 5
            and self.local_attempt_cap == 900
            and re.fullmatch(r"[a-fA-F0-9]{32}", self.api_key.strip()) is not None
            and self.latitude is not None
            and self.longitude is not None
            and math.isfinite(self.latitude)
            and math.isfinite(self.longitude)
            and -90 <= self.latitude <= 90
            and -180 <= self.longitude <= 180
        )
