import pytest
import time
from unittest.mock import patch
from src.enforcement.engine import EnforcementEngine
from src.enforcement.models import EscalationLevel
from src.detection.detector import AnomalyDetector
from src.detection.global_monitor import GlobalSystemMonitor

@pytest.mark.asyncio
async def test_enforcement_engine_whitelist(mock_redis_client, mock_config_manager):
    detector = AnomalyDetector(mock_config_manager, mock_redis_client)
    global_monitor = GlobalSystemMonitor(mock_config_manager, mock_redis_client)
    engine = EnforcementEngine(mock_config_manager, mock_redis_client, detector, global_monitor)
    
    # Whitelisted IP
    decision = await engine.evaluate_request(client_ip="127.0.0.1", path="/api/data", method="GET", is_whitelisted=True)
    assert decision.allowed is True
    assert decision.reason_code == "CLIENT_WHITELISTED"

@pytest.mark.asyncio
async def test_enforcement_engine_adaptive_and_escalation(mock_redis_client, mock_config_manager):
    detector = AnomalyDetector(mock_config_manager, mock_redis_client)
    global_monitor = GlobalSystemMonitor(mock_config_manager, mock_redis_client)
    engine = EnforcementEngine(mock_config_manager, mock_redis_client, detector, global_monitor)
    
    client_ip = "192.168.1.100"
    path = "/api/data"
    
    # Mock anomaly score to 0.0 so we only test violations escalation in isolation
    with patch.object(detector, 'calculate_anomaly_score') as mock_anomaly:
        anomaly_mock = MagicMock()
        anomaly_mock.score = 0.0
        mock_anomaly.return_value = anomaly_mock
        
        # Defaults in mock config: rate = 2.0, capacity = 4.0
        with patch('time.time', return_value=100.0):
            # 1. Allow first request
            dec1 = await engine.evaluate_request(client_ip, path, "GET")
            assert dec1.allowed is True
            assert dec1.escalation_level == EscalationLevel.ALLOW
            
            # 2. Consume capacity entirely to trigger throttle escalation
            # Capacity is 4. Let's make 4 requests -> all allowed. 5th request -> blocked.
            for i in range(3):
                await engine.evaluate_request(client_ip, path, "GET")
                
            dec_fail = await engine.evaluate_request(client_ip, path, "GET")
            assert dec_fail.allowed is False
            # 1st violation count = 1. Level should still be ALLOW (threshold for throttle is 2 violations in mock config)
            assert dec_fail.escalation_level == EscalationLevel.ALLOW
            
            # Make 2nd failed request
            dec_fail2 = await engine.evaluate_request(client_ip, path, "GET")
            assert dec_fail2.allowed is False
            # 2nd violation. Escalate to THROTTLE (threshold is 2 violations in mock config)
            assert dec_fail2.escalation_level == EscalationLevel.THROTTLE
            assert dec_fail2.reason_code == "CLIENT_THROTTLED"

@pytest.mark.asyncio
async def test_enforcement_engine_adaptive_limits_under_load(mock_redis_client, mock_config_manager):
    detector = AnomalyDetector(mock_config_manager, mock_redis_client)
    global_monitor = GlobalSystemMonitor(mock_config_manager, mock_redis_client)
    engine = EnforcementEngine(mock_config_manager, mock_redis_client, detector, global_monitor)
    
    # Mock global monitor to simulate high latency load_multiplier = 0.5
    # Mock detector to simulate anomaly score = 0.6
    with patch.object(global_monitor, 'get_system_load') as mock_load, \
         patch.object(detector, 'calculate_anomaly_score') as mock_anomaly:
        
        # Setup load return value
        load_mock = MagicMock()
        load_mock.load_multiplier = 0.5
        mock_load.return_value = load_mock
        
        # Setup anomaly return value
        anomaly_mock = MagicMock()
        anomaly_mock.score = 0.6
        mock_anomaly.return_value = anomaly_mock
        
        # Check base limits: rate = 2.0, capacity = 4.0
        # Adaptive factor = (1 - anomaly * severity) * load = (1 - 0.6 * 0.7) * 0.5 = (1 - 0.42) * 0.5 = 0.58 * 0.5 = 0.29
        # Adaptive rate = 2.0 * 0.29 = 0.58
        # Let's verify that the limit is tightened!
        
        with patch('time.time', return_value=200.0):
            dec = await engine.evaluate_request("10.0.0.5", "/api/data", "GET")
            # The current_limit in decision should match the computed adaptive limit
            assert dec.current_limit == pytest.approx(2.0 * 0.58 * 0.5)
            # The escalation level should transition based on the anomaly score (0.6 is >= 0.5 challenge threshold in mock config)
            # Since first request failed or succeeded? Let's check:
            # Under capacity (since it's a new client_key), it is allowed.
            assert dec.allowed is True
            # Level should be challenge if evaluated after failure, but here request is allowed, wait, the level is ALLOW?
            # Wait, level is ALLOW initially. If allowed, we don't escalate level. We only check escalation on failure.
            # But the remaining tokens should reflect the tighter capacity.
            # Base capacity = 4.0. Adjusted capacity = 4.0 * 0.29 = 1.16. Remaining tokens = 1.16 - 1 = 0.16.
            assert dec.remaining_tokens == pytest.approx(1.16 - 1.0)
            
from unittest.mock import MagicMock
