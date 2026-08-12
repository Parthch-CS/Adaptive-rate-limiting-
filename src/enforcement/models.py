from enum import IntEnum
from pydantic import BaseModel
from typing import Optional, Dict, Any

class EscalationLevel(IntEnum):
    ALLOW = 0       # Request allowed under normal conditions
    THROTTLE = 1    # Request throttled (429 standard or delayed response)
    CHALLENGE = 2   # Request blocked with challenge (CAPTCHA simulation)
    TEMP_BLOCK = 3  # Temporary hard block (403 for some duration)
    FULL_BLOCK = 4  # Persistent hard block (403, added to blacklist)

class RateLimitDecision(BaseModel):
    allowed: bool
    escalation_level: EscalationLevel
    reason_code: str
    remaining_tokens: float
    wait_time_seconds: float = 0.0
    anomaly_score: float = 0.0
    current_limit: float = 0.0
    client_ip: str
    metadata: Optional[Dict[str, Any]] = None
