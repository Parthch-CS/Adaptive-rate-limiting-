import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from src.proxy.app import app
import src.proxy.app as proxy_module
from src.enforcement.models import EscalationLevel

@pytest.fixture
def mock_http_client():
    client = MagicMock(spec=httpx.AsyncClient)
    # Mock backend response
    mock_resp = httpx.Response(
        status_code=200,
        content=b'{"message": "success from backend"}',
        headers={"content-type": "application/json"}
    )
    client.request = AsyncMock(return_value=mock_resp)
    return client

@pytest.mark.asyncio
async def test_proxy_flow_success(mock_http_client):
    # Set the mock HTTP client inside the proxy module
    proxy_module.http_client = mock_http_client
    
    # Mock the enforcement engine
    mock_engine = AsyncMock()
    mock_decision = MagicMock()
    mock_decision.allowed = True
    mock_decision.reason_code = "REQUEST_ALLOWED"
    mock_decision.remaining_tokens = 10.0
    mock_decision.anomaly_score = 0.0
    mock_decision.current_limit = 10.0
    mock_decision.client_ip = "127.0.0.1"
    mock_decision.escalation_level = EscalationLevel.ALLOW
    
    mock_engine.evaluate_request = AsyncMock(return_value=mock_decision)
    proxy_module.enforcement_engine = mock_engine
    
    # Mock global monitor
    proxy_module.global_monitor = AsyncMock()
    
    # Instantiate TestClient WITHOUT using "with" statement (to bypass startup/shutdown event triggers)
    client = TestClient(app)
    response = client.get("/api/data", headers={"X-Forwarded-For": "8.8.8.8"})
    
    assert response.status_code == 200
    assert response.json() == {"message": "success from backend"}
    
    # Verify it went to the engine
    mock_engine.evaluate_request.assert_called_once_with(
        client_ip="8.8.8.8",
        path="/api/data",
        method="GET",
        is_whitelisted=False
    )
    
    # Verify it forwarded to backend
    mock_http_client.request.assert_called_once()

@pytest.mark.asyncio
async def test_proxy_flow_throttled():
    mock_engine = AsyncMock()
    mock_decision = MagicMock()
    mock_decision.allowed = False
    mock_decision.reason_code = "CLIENT_THROTTLED"
    mock_decision.remaining_tokens = 0.0
    mock_decision.anomaly_score = 0.5
    mock_decision.current_limit = 2.0
    mock_decision.client_ip = "192.168.1.100"
    mock_decision.escalation_level = EscalationLevel.THROTTLE
    mock_decision.wait_time_seconds = 5.0
    
    mock_engine.evaluate_request = AsyncMock(return_value=mock_decision)
    proxy_module.enforcement_engine = mock_engine
    
    # Ensure client is NOT called
    mock_client = MagicMock(spec=httpx.AsyncClient)
    proxy_module.http_client = mock_client
    
    # Bypass startup by NOT using "with"
    client = TestClient(app)
    response = client.get("/api/data", headers={"X-Forwarded-For": "8.8.8.8"})
    
    assert response.status_code == 429
    assert response.json()["error"] == "Too Many Requests"
    assert response.headers["Retry-After"] == "5"
    
    # Backend should NOT be called
    mock_client.request.assert_not_called()
