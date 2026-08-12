import time
import hashlib
import ipaddress
import logging
from typing import Dict, List, Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.ingestion.models import RequestMetadata
from src.config.manager import ConfigManager

logger = logging.getLogger("arl.ingestion.middleware")

class IngestionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config_manager: ConfigManager):
        super().__init__(app)
        self.config_manager = config_manager
        
        # Cached whitelist/blacklist compiled objects
        self.whitelist_nets: List[Any] = []
        self.blacklist_nets: List[Any] = []
        
        # Register for changes
        self.config_manager.register_callback(self._update_acls)

    def _update_acls(self, config):
        self.whitelist_nets = []
        self.blacklist_nets = []
        
        for ip_str in config.access_control.whitelist:
            try:
                self.whitelist_nets.append(ipaddress.ip_network(ip_str, strict=False))
            except Exception as e:
                logger.error(f"Invalid whitelist IP/CIDR '{ip_str}': {e}")
                
        for ip_str in config.access_control.blacklist:
            try:
                self.blacklist_nets.append(ipaddress.ip_network(ip_str, strict=False))
            except Exception as e:
                logger.error(f"Invalid blacklist IP/CIDR '{ip_str}': {e}")
                
        logger.info(f"Loaded {len(self.whitelist_nets)} whitelist and {len(self.blacklist_nets)} blacklist networks.")

    def _get_client_ip(self, request: Request) -> str:
        # Check X-Forwarded-For header
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Take the leftmost IP (original client)
            parts = [p.strip() for p in xff.split(",")]
            if parts:
                return parts[0]
        # Fallback to direct connection IP
        if request.client:
            return request.client.host
        return "127.0.0.1"

    def _is_ip_in_list(self, ip_str: str, networks: List[Any]) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
            return any(ip in net for net in networks)
        except Exception:
            return False

    def _generate_ua_fingerprint(self, user_agent: str) -> str:
        if not user_agent:
            return "no-user-agent"
        return hashlib.sha256(user_agent.encode('utf-8')).hexdigest()

    async def dispatch(self, request: Request, call_next):
        # Expose metrics endpoint without rate limiting
        if request.url.path == "/metrics":
            return await call_next(request)
            
        client_ip = self._get_client_ip(request)
        
        # 1. Blacklist check (escalation level 4/full block simulation)
        if self._is_ip_in_list(client_ip, self.blacklist_nets):
            logger.warning(f"Blocked request from blacklisted IP: {client_ip}")
            return JSONResponse(
                status_code=403,
                content={"error": "Forbidden", "message": "Access denied by security policy.", "code": "IP_BLACKLISTED"}
            )
            
        # 2. Whitelist check
        is_whitelisted = self._is_ip_in_list(client_ip, self.whitelist_nets)
        request.state.is_whitelisted = is_whitelisted
        
        # 3. Capture metadata
        content_length = request.headers.get("content-length")
        payload_size = int(content_length) if content_length and content_length.isdigit() else 0
        
        ua = request.headers.get("user-agent", "")
        ua_fingerprint = self._generate_ua_fingerprint(ua)
        
        # Look for custom load balancer TLS headers
        tls_fingerprint = request.headers.get("x-tls-fingerprint")
        
        metadata = RequestMetadata(
            client_ip=client_ip,
            method=request.method,
            path=request.url.path,
            headers=dict(request.headers),
            payload_size=payload_size,
            timestamp=time.time(),
            ua_fingerprint=ua_fingerprint,
            tls_fingerprint=tls_fingerprint
        )
        
        # Attach request metadata to request state so downstream middleware/routers can access it
        request.state.metadata = metadata
        
        # Store start time for latency tracking
        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000
            metadata.duration_ms = duration_ms
            return response
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            metadata.duration_ms = duration_ms
            logger.error(f"Error handling request from {client_ip} to {request.url.path}: {e}")
            raise
