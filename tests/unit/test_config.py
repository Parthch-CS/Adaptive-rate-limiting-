import os
import time
import tempfile
import pytest
import yaml
from src.config.manager import ConfigManager
from src.config.models import AppConfig

def test_load_default_config():
    # Test that default config loads correctly
    # Use path relative to current working dir (which should be the root of the project)
    config_path = "config/default_config.yaml"
    assert os.path.exists(config_path), f"Default config not found at {config_path}"
    
    manager = ConfigManager(config_path)
    config = manager.get_config()
    
    assert isinstance(config, AppConfig)
    assert config.system.environment == "production"
    assert config.redis.port == 6379
    assert config.defaults.algorithm == "token_bucket"
    assert "throttle" in config.escalation.levels
    assert len(config.endpoints) > 0
    assert "127.0.0.1" in config.access_control.whitelist

def test_config_hot_reload():
    # Test hot-reload of config using a temporary file
    test_yaml = """
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
  algorithm: "sliding_window"
  rate: 5.0
  capacity: 10.0
  window_seconds: 30
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
endpoints: []
access_control:
  whitelist: ["1.1.1.1"]
  blacklist: ["2.2.2.2"]
detection:
  enabled: true
  evaluation_interval_seconds: 2
  ewma_alpha: 0.2
  z_score_threshold: 2.5
  severity_factor: 0.5
  slowloris:
    enabled: false
    min_payload_ratio: 0.05
    max_request_duration_seconds: 5
    trigger_connection_count: 20
global_monitor:
  enabled: false
  max_backend_latency_ms: 1000
  max_error_rate: 0.20
  min_multiplier: 0.5
"""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode='w') as f:
        f.write(test_yaml)
        temp_path = f.name

    try:
        manager = ConfigManager(temp_path)
        config = manager.get_config()
        assert config.system.environment == "testing"
        assert config.defaults.algorithm == "sliding_window"
        
        # Start watching
        manager.start_watcher()
        
        # Register a callback to check updates
        callback_called = []
        def on_change(cfg):
            callback_called.append(cfg)
            
        manager.register_callback(on_change)
        # Clear it since registering calls it once
        callback_called.clear()
        
        # Update config contents
        updated_yaml = test_yaml.replace('"testing"', '"updated-testing"').replace('sliding_window', 'token_bucket')
        with open(temp_path, 'w') as f:
            f.write(updated_yaml)
            
        # Give watchdog slightly time to trigger
        time.sleep(0.5)
        
        # Check if updated
        updated_config = manager.get_config()
        assert updated_config.system.environment == "updated-testing"
        assert updated_config.defaults.algorithm == "token_bucket"
        assert len(callback_called) > 0
        assert callback_called[0].system.environment == "updated-testing"
        
        manager.stop_watcher()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
