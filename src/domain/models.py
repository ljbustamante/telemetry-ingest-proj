
from __future__ import annotations
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator

class TelemetryIngest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_key: str = Field(..., min_length=1)
    event_ts_ms: int = Field(..., description="Epoch milliseconds for event_ts")
    agent_version: Optional[str] = None
    schema_version: Optional[str] = None
    sample_period_s: Optional[int] = None
    payload: Dict[str, Any]

    @field_validator("event_ts_ms")
    @classmethod
    def check_ts(cls, v: int) -> int:
        if v < 946684800000:
            raise ValueError("event_ts_ms seems too old or not in ms")
        return v
