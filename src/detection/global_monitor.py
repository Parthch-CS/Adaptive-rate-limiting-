import time
import logging
from typing import Tuple, Dict
from src.config.manager import ConfigManager
from src.storage.redis_client import RedisClient
from src.detection.models import SystemLoad

logger = logging.getLogger("arl.detection.global_monitor")

class GlobalSystemMonitor:
    def __init__(self, config_manager: ConfigManager, redis_client: RedisClient):
        self.config_manager = config_manager
        self.redis_client = redis_client
        
        # In-memory fallback
        self._fallback_metrics: Dict[str, float] = {
            "total_requests": 0.0,
            "total_errors": 0.0,
            "total_duration_ms": 0.0,
            "last_reset": time.time()
        }

    async def record_request(self, duration_ms: float, status_code: int):
        config = self.config_manager.get_config()
        if not config.global_monitor.enabled:
            return
            
        now = time.time()
        window_id = int(now / 10) # 10-second slots
        is_error = 1 if 500 <= status_code < 600 else 0
        
        if self.redis_client.client:
            try:
                # Store aggregated metrics in Redis with 10-second granularity
                req_key = f"global:req:{window_id}"
                err_key = f"global:err:{window_id}"
                lat_key = f"global:lat:{window_id}"
                
                pipe = self.redis_client.client.pipeline()
                pipe.incr(req_key)
                if is_error:
                    pipe.incr(err_key)
                pipe.incrbyfloat(lat_key, duration_ms)
                
                # Set expirations to 60 seconds
                pipe.expire(req_key, 60)
                pipe.expire(err_key, 60)
                pipe.expire(lat_key, 60)
                
                await pipe.execute()
                return
            except Exception as e:
                logger.error(f"Redis global monitor record failed: {e}")

        # Fallback to local in-memory aggregation
        self._fallback_metrics["total_requests"] += 1
        if is_error:
            self._fallback_metrics["total_errors"] += 1
        self._fallback_metrics["total_duration_ms"] += duration_ms
        
        # Reset fallback metrics every 10 seconds to keep them sliding/fresh
        if now - self._fallback_metrics["last_reset"] >= 10.0:
            self._fallback_metrics["total_requests"] = 1.0
            self._fallback_metrics["total_errors"] = float(is_error)
            self._fallback_metrics["total_duration_ms"] = duration_ms
            self._fallback_metrics["last_reset"] = now

    async def get_system_load(self) -> SystemLoad:
        config = self.config_manager.get_config()
        monitor_cfg = config.global_monitor
        now = time.time()
        
        if not monitor_cfg.enabled:
            return SystemLoad(latency_ms=0.0, error_rate=0.0, load_multiplier=1.0, timestamp=now)
            
        current_window = int(now / 10)
        previous_window = current_window - 1
        
        avg_latency = 0.0
        error_rate = 0.0
        
        if self.redis_client.client:
            try:
                req_keys = [f"global:req:{current_window}", f"global:req:{previous_window}"]
                err_keys = [f"global:err:{current_window}", f"global:err:{previous_window}"]
                lat_keys = [f"global:lat:{current_window}", f"global:lat:{previous_window}"]
                
                req_data = await self.redis_client.client.mget(req_keys)
                err_data = await self.redis_client.client.mget(err_keys)
                lat_data = await self.redis_client.client.mget(lat_keys)
                
                total_reqs = sum(int(x or 0) for x in req_data)
                total_errs = sum(int(x or 0) for x in err_data)
                total_lats = sum(float(x or 0.0) for x in lat_data)
                
                if total_reqs > 0:
                    avg_latency = total_lats / total_reqs
                    error_rate = total_errs / total_reqs
            except Exception as e:
                logger.error(f"Redis global monitor fetch failed: {e}")
                # Fallback to local
                total_reqs = self._fallback_metrics["total_requests"]
                if total_reqs > 0:
                    avg_latency = self._fallback_metrics["total_duration_ms"] / total_reqs
                    error_rate = self._fallback_metrics["total_errors"] / total_reqs
        else:
            total_reqs = self._fallback_metrics["total_requests"]
            if total_reqs > 0:
                avg_latency = self._fallback_metrics["total_duration_ms"] / total_reqs
                error_rate = self._fallback_metrics["total_errors"] / total_reqs
                
        # Calculate load multiplier based on thresholds
        # Under normal conditions, multiplier is 1.0
        # Multiplier scales down linearly to min_multiplier under extreme load
        latency_factor = 1.0
        error_factor = 1.0
        
        max_lat = monitor_cfg.max_backend_latency_ms
        max_err = monitor_cfg.max_error_rate
        min_mult = monitor_cfg.min_multiplier
        
        if avg_latency > max_lat:
            # Scale down to min_multiplier as latency doubles threshold
            overage = (avg_latency - max_lat) / max_lat
            latency_factor = max(min_mult, 1.0 - overage)
            
        if error_rate > max_err:
            # Scale down to min_multiplier as error rate goes from max_err to 100%
            overage = (error_rate - max_err) / (1.0 - max_err)
            error_factor = max(min_mult, 1.0 - overage)
            
        load_multiplier = min(latency_factor, error_factor)
        
        return SystemLoad(
            latency_ms=avg_latency,
            error_rate=error_rate,
            load_multiplier=load_multiplier,
            timestamp=now
        )
