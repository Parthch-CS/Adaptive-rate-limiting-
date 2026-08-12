from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class AnomalyScore(BaseModel):
    client_ip: str
    score: float = 0.0  # 0.0 (normal) to 1.0 (highly anomalous)
    reason: str = "normal"
    timestamp: float

class ClientBaseline(BaseModel):
    client_ip: str
    ewma_rate: float = 0.0
    ewma_variance: float = 0.0
    last_evaluation: float

class SystemLoad(BaseModel):
    latency_ms: float = 0.0
    error_rate: float = 0.0
    load_multiplier: float = 1.0  # 1.0 (healthy) down to min_multiplier (overloaded)
    timestamp: float
