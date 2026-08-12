import os
import time
import httpx
import asyncio
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from src.config.manager import ConfigManager
from src.storage.redis_client import RedisClient
from src.ingestion.middleware import IngestionMiddleware
from src.enforcement.engine import EnforcementEngine
from src.enforcement.models import EscalationLevel
from src.detection.detector import AnomalyDetector
from src.detection.global_monitor import GlobalSystemMonitor
from src.metrics.logger import configure_logger, get_logger
from src.metrics.prometheus import (
    HTTP_REQUESTS_TOTAL,
    HTTP_BLOCKED_TOTAL,
    CLIENT_CURRENT_LIMIT,
    CLIENT_ANOMALY_SCORE,
    DECISION_DURATION_SECONDS,
    FALSE_POSITIVE_INDICATOR
)

# Initialize configuration manager
config_path = os.getenv("CONFIG_PATH", "config/default_config.yaml")
config_manager = ConfigManager(config_path)

# Configure structured logging based on configuration debug mode
config = config_manager.get_config()
configure_logger(debug=config.system.debug)
logger = get_logger("arl.proxy")

app = FastAPI(title="Adaptive Rate Limiting Security Proxy")

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Backend service target URL
backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

# Globals initialized in startup
redis_client: RedisClient = None
detector: AnomalyDetector = None
global_monitor: GlobalSystemMonitor = None
enforcement_engine: EnforcementEngine = None
http_client: httpx.AsyncClient = None

@app.on_event("startup")
async def startup():
    global redis_client, detector, global_monitor, enforcement_engine, http_client
    
    # 1. Initialize config manager watcher
    config_manager.start_watcher()
    
    # 2. Initialize Redis client
    redis_client = RedisClient(config_manager)
    await redis_client.initialize()
    
    # 3. Initialize detector & monitors
    detector = AnomalyDetector(config_manager, redis_client)
    global_monitor = GlobalSystemMonitor(config_manager, redis_client)
    enforcement_engine = EnforcementEngine(config_manager, redis_client, detector, global_monitor)
    
    # 4. Initialize HTTP client for forwarding requests
    # Limit connections to prevent exhaustion
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    http_client = httpx.AsyncClient(base_url=backend_url, limits=limits, timeout=10.0)
    
    logger.info("rate_limiter_proxy_started", backend_url=backend_url)

@app.on_event("shutdown")
async def shutdown():
    global redis_client, http_client
    
    config_manager.stop_watcher()
    
    if redis_client:
        await redis_client.close()
        
    if http_client:
        await http_client.aclose()
        
    logger.info("rate_limiter_proxy_shutdown")

# Mount Ingestion Middleware
app.add_middleware(IngestionMiddleware, config_manager=config_manager)

# Main reverse proxy route
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_handler(request: Request, path: str):
    global enforcement_engine, http_client, global_monitor
    
    # Check if request is whitelisted
    is_whitelisted = getattr(request.state, "is_whitelisted", False)
    
    # Get request metadata parsed by IngestionMiddleware
    metadata = getattr(request.state, "metadata", None)
    client_ip = metadata.client_ip if metadata else "127.0.0.1"
    endpoint_path = f"/{path}"
    
    # 1. Evaluate request against Rate Limiting Engine
    start_eval_time = time.time()
    decision = await enforcement_engine.evaluate_request(
        client_ip=client_ip,
        path=endpoint_path,
        method=request.method,
        is_whitelisted=is_whitelisted
    )
    eval_duration = time.time() - start_eval_time
    
    # Record decision duration metric
    DECISION_DURATION_SECONDS.observe(eval_duration)
    
    # Record requests total count in Prometheus
    decision_label = "allow" if decision.allowed else decision.escalation_level.name.lower()
    HTTP_REQUESTS_TOTAL.labels(method=request.method, endpoint=endpoint_path, decision=decision_label).inc()
    
    # Record current client limit and anomaly score
    CLIENT_CURRENT_LIMIT.labels(client_ip=client_ip, endpoint=endpoint_path).set(decision.current_limit)
    CLIENT_ANOMALY_SCORE.observe(decision.anomaly_score)
    
    # Dry-run for whitelisted clients to track false-positive indicators
    if is_whitelisted:
        # Check what the decision would have been if not whitelisted
        dry_run_decision = await enforcement_engine.evaluate_request(
            client_ip=client_ip,
            path=endpoint_path,
            method=request.method,
            is_whitelisted=False
        )
        if not dry_run_decision.allowed:
            # Whitelisted client would have been blocked/throttled -> false positive indicator
            FALSE_POSITIVE_INDICATOR.labels(client_ip=client_ip).inc()
            logger.info("false_positive_blocked_mitigation", client_ip=client_ip, path=endpoint_path, dry_run_reason=dry_run_decision.reason_code)
            
    # If blocked or throttled, escalate response
    if not decision.allowed:
        # Record blocked/throttled request in Prometheus
        HTTP_BLOCKED_TOTAL.labels(reason=decision.reason_code.lower(), client_ip=client_ip).inc()
        
        # Structured log of blocking decision
        logger.warning(
            "request_blocked",
            client_ip=client_ip,
            path=endpoint_path,
            method=request.method,
            decision=decision.reason_code,
            level=decision.escalation_level.name,
            anomaly_score=decision.anomaly_score,
            current_limit=decision.current_limit,
            eval_duration_ms=eval_duration * 1000
        )
        
        # Challenge response simulation (Level 2)
        if decision.escalation_level == EscalationLevel.CHALLENGE:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": "Challenge Required",
                    "message": "Suspicious behavior detected. Please complete challenge to continue.",
                    "code": "CHALLENGE_REQUIRED",
                    "challenge_simulation_url": f"/challenge?ip={client_ip}"
                },
                headers={"X-RateLimit-Action": "challenge"}
            )
            
        # Standard Throttle response (Level 1)
        if decision.escalation_level == EscalationLevel.THROTTLE:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "message": "Rate limit exceeded. Please slow down.",
                    "code": "RATE_LIMIT_EXCEEDED"
                },
                headers={
                    "Retry-After": str(int(decision.wait_time_seconds)),
                    "X-RateLimit-Action": "throttle"
                }
            )
            
        # Temporary or Permanent block responses (Level 3 or 4)
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": "Forbidden",
                "message": "Access is temporarily suspended due to security policy violations.",
                "code": "ACCESS_SUSPENDED"
            },
            headers={
                "Retry-After": str(int(decision.wait_time_seconds)),
                "X-RateLimit-Action": "block"
            }
        )

    # 2. Forward request to backend
    # Read request body
    body = await request.body()
    
    # Forward headers (excluding host header to avoid routing loops)
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    # Add client tracing headers
    headers["X-Forwarded-For"] = client_ip
    
    backend_start = time.time()
    try:
        # Make the request to backend
        backend_response = await http_client.request(
            method=request.method,
            url=f"/{path}",
            params=dict(request.query_params),
            headers=headers,
            content=body
        )
        backend_duration_ms = (time.time() - backend_start) * 1000
        
        # 3. Record backend statistics in global monitor
        await global_monitor.record_request(
            duration_ms=backend_duration_ms,
            status_code=backend_response.status_code
        )
        
        # Return response to client
        return Response(
            content=backend_response.content,
            status_code=backend_response.status_code,
            headers=dict(backend_response.headers)
        )
    except httpx.HTTPError as e:
        logger.error("backend_communication_error", error=str(e))
        # Record 502/Gateway error in monitor
        await global_monitor.record_request(
            duration_ms=(time.time() - backend_start) * 1000,
            status_code=502
        )
        return JSONResponse(
            status_code=502,
            content={"error": "Bad Gateway", "message": "Backend service is unreachable."}
        )
