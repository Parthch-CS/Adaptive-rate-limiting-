import pytest
import time
from unittest.mock import patch, MagicMock
from src.config.manager import ConfigManager
from src.detection.detector import AnomalyDetector
from src.detection.global_monitor import GlobalSystemMonitor
from src.detection.models import AnomalyScore, ClientBaseline

@pytest.mark.asyncio
async def test_anomaly_detector_in_memory(mock_redis_client, mock_config_manager):
    # Enable anomaly detection in mock config
    mock_config = mock_config_manager.get_config()
    mock_config.detection.enabled = True
    mock_config.detection.evaluation_interval_seconds = 5
    mock_config.detection.ewma_alpha = 0.3
    mock_config.detection.z_score_threshold = 3.0
    
    detector = AnomalyDetector(mock_config_manager, mock_redis_client)
    client_ip = "192.168.1.50"
    
    # 1. First requests in interval: should initialize baseline
    with patch('time.time', return_value=100.0):
        score_obj = await detector.calculate_anomaly_score(client_ip, "/api/data")
        assert isinstance(score_obj, AnomalyScore)
        assert score_obj.score == 0.0 # Standard z-score initially 0
        
    # 2. Add requests in same interval (before 5 seconds elapse)
    with patch('time.time', return_value=102.0):
        # Trigger 5 more requests
        for _ in range(5):
            score_obj = await detector.calculate_anomaly_score(client_ip, "/api/data")
        # dt = 102.0 - 100.0 = 2.0. Count = 6. current_rate = 6/2 = 3.0.
        # std_dev = 1.0. ewma = 1.0. Z-score = (3.0 - 1.0)/1.0 = 2.0.
        # Score = 2.0 / 3.0 = 0.66
        assert score_obj.score > 0.0

    # 3. Trigger Slowloris check
    is_slowloris = detector.detect_slowloris(client_ip, payload_size=50, duration_seconds=12.0)
    assert is_slowloris is True
    
    is_slowloris_normal = detector.detect_slowloris(client_ip, payload_size=5000, duration_seconds=2.0)
    assert is_slowloris_normal is False

@pytest.mark.asyncio
async def test_global_system_monitor_in_memory(mock_redis_client, mock_config_manager):
    mock_config = mock_config_manager.get_config()
    mock_config.global_monitor.enabled = True
    mock_config.global_monitor.max_backend_latency_ms = 100.0
    mock_config.global_monitor.max_error_rate = 0.1
    mock_config.global_monitor.min_multiplier = 0.2
    
    monitor = GlobalSystemMonitor(mock_config_manager, mock_redis_client)
    
    with patch('time.time', return_value=100.0):
        # Record 10 healthy fast requests
        for _ in range(10):
            await monitor.record_request(duration_ms=10.0, status_code=200)
            
        load = await monitor.get_system_load()
        assert load.load_multiplier == 1.0
        assert load.latency_ms == 10.0
        
        # Record 5 slow requests (latency 500ms > threshold 100ms)
        # Average will be (10*10 + 5*500) / 15 = 2600 / 15 = 173.3ms
        for _ in range(5):
            await monitor.record_request(duration_ms=500.0, status_code=200)
            
        load_overloaded = await monitor.get_system_load()
        assert load_overloaded.load_multiplier < 1.0
        
        # Record 10 server errors (status 500)
        # Total requests = 10 + 5 + 10 = 25. Errors = 10. Error rate = 10/25 = 40% > threshold 10%
        for _ in range(10):
            await monitor.record_request(duration_ms=20.0, status_code=500)
            
        load_extreme = await monitor.get_system_load()
        assert load_extreme.load_multiplier < 0.8
