from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class RequestMetadata(BaseModel):
    client_ip: str
    method: str
    path: str
    headers: Dict[str, str] = Field(default_factory=dict)
    payload_size: int = 0
    timestamp: float
    ua_fingerprint: str
    tls_fingerprint: Optional[str] = None
    duration_ms: Optional[float] = None
