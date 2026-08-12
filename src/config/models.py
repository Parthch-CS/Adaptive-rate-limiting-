from typing import List, Dict, Optional
from pydantic import BaseModel, Field

class SystemConfig(BaseModel):
    environment: str = "production"
    debug: bool = False

class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    prefix: str = "arl:"
    pool_size: int = 20

class DefaultRateLimitConfig(BaseModel):
    algorithm: str = "token_bucket"
    rate: float = 10.0
    capacity: float = 20.0
    window_seconds: int = 60

class EscalationLevel(BaseModel):
    trigger_violations: int
    trigger_anomaly_score: float

class EscalationConfig(BaseModel):
    cooldown_seconds: int = 300
    temp_block_duration: int = 600
    levels: Dict[str, EscalationLevel]

class EndpointOverride(BaseModel):
    path: str
    rate: float
    capacity: float
    window_seconds: Optional[int] = None

class AccessControlConfig(BaseModel):
    whitelist: List[str] = Field(default_factory=list)
    blacklist: List[str] = Field(default_factory=list)

class SlowlorisConfig(BaseModel):
    enabled: bool = True
    min_payload_ratio: float = 0.1
    max_request_duration_seconds: int = 10
    trigger_connection_count: int = 50

class DetectionConfig(BaseModel):
    enabled: bool = True
    evaluation_interval_seconds: int = 5
    ewma_alpha: float = 0.3
    z_score_threshold: float = 3.0
    severity_factor: float = 0.7
    slowloris: SlowlorisConfig = Field(default_factory=SlowlorisConfig)

class GlobalMonitorConfig(BaseModel):
    enabled: bool = True
    max_backend_latency_ms: int = 500
    max_error_rate: float = 0.10
    min_multiplier: float = 0.3

class AppConfig(BaseModel):
    system: SystemConfig = Field(default_factory=SystemConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    defaults: DefaultRateLimitConfig = Field(default_factory=DefaultRateLimitConfig)
    escalation: EscalationConfig
    endpoints: List[EndpointOverride] = Field(default_factory=list)
    access_control: AccessControlConfig = Field(default_factory=AccessControlConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    global_monitor: GlobalMonitorConfig = Field(default_factory=GlobalMonitorConfig)
