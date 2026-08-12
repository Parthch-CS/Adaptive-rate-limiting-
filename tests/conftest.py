import pytest
import yaml
from unittest.mock import MagicMock
from src.config.manager import ConfigManager
from src.config.models import AppConfig
from src.storage.redis_client import RedisClient

@pytest.fixture
def test_config():
    yaml_str = """
system:
  environment: "testing"
  debug: true
redis:
  host: "localhost"
  port: 6379
  db: 0
  prefix: "test:"
  pool_size: 5
defaults:
  algorithm: "token_bucket"
  rate: 2.0
  capacity: 4.0
  window_seconds: 10
escalation:
  cooldown_seconds: 60
  temp_block_duration: 120
  levels:
    throttle:
      trigger_violations: 2
      trigger_anomaly_score: 0.2
    challenge:
      trigger_violations: 4
      trigger_anomaly_score: 0.5
    temp_block:
      trigger_violations: 6
      trigger_anomaly_score: 0.7
    full_block:
      trigger_violations: 10
      trigger_anomaly_score: 0.9
endpoints:
  - path: "/api/heavy"
    rate: 1.0
    capacity: 2.0
access_control:
  whitelist: ["127.0.0.1"]
  blacklist: ["198.51.100.42"]
detection:
  enabled: true
  evaluation_interval_seconds: 5
  ewma_alpha: 0.3
  z_score_threshold: 3.0
  severity_factor: 0.7
  slowloris:
    enabled: true
    min_payload_ratio: 0.1
    max_request_duration_seconds: 10
    trigger_connection_count: 50
global_monitor:
  enabled: true
  max_backend_latency_ms: 100
  max_error_rate: 0.1
  min_multiplier: 0.2
"""
    raw = yaml.safe_load(yaml_str)
    return AppConfig(**raw)

@pytest.fixture
def mock_config_manager(test_config):
    manager = MagicMock(spec=ConfigManager)
    manager.get_config.return_value = test_config
    # Implement register_callback to immediately trigger the callback with the config
    def register_cb(cb):
        cb(test_config)
    manager.register_callback.side_effect = register_cb
    return manager

@pytest.fixture
def mock_redis_client(mock_config_manager):
    client = MagicMock(spec=RedisClient)
    client.config_manager = mock_config_manager
    client.client = None # Force fallback to in-memory
    client.run_script.return_value = None
    return client
