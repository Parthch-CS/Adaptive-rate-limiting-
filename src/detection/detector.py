import time
import math
import logging
from typing import Tuple, Dict, Optional
from src.config.manager import ConfigManager
from src.storage.redis_client import RedisClient
from src.detection.models import AnomalyScore, ClientBaseline

logger = logging.getLogger("arl.detection.detector")

class AnomalyDetector:
    def __init__(self, config_manager: ConfigManager, redis_client: RedisClient):
        self.config_manager = config_manager
        self.redis_client = redis_client
        
        # In-memory baseline fallback when Redis is down
        self._fallback_baselines: Dict[str, ClientBaseline] = {}
        # In-memory request counters for the current interval when Redis is down
        self._fallback_counters: Dict[str, Tuple[int, float]] = {}

    async def calculate_anomaly_score(self, client_ip: str, path: str) -> AnomalyScore:
        config = self.config_manager.get_config()
        detection_cfg = config.detection
        now = time.time()
        
        if not detection_cfg.enabled:
            return AnomalyScore(client_ip=client_ip, score=0.0, reason="disabled", timestamp=now)
            
        interval = detection_cfg.evaluation_interval_seconds
        alpha = detection_cfg.ewma_alpha
        z_threshold = detection_cfg.z_score_threshold
        
        current_rate = 0.0
        baseline = None
        
        if self.redis_client.client:
            try:
                # Redis Keys
                baseline_key = f"baseline:{client_ip}"
                counter_key = f"eval_counter:{client_ip}"
                
                # Fetch baseline state
                data = await self.redis_client.client.hmget(
                    baseline_key, "ewma_rate", "ewma_variance", "last_evaluation"
                )
                
                # Increment current interval request count
                count = await self.redis_client.client.incr(counter_key)
                if count == 1:
                    await self.redis_client.client.expire(counter_key, interval * 3)
                    
                ewma_rate_val, ewma_var_val, last_eval_val = data
                
                if not ewma_rate_val or not last_eval_val:
                    # Initialize baseline in Redis
                    baseline = ClientBaseline(
                        client_ip=client_ip,
                        ewma_rate=1.0, # default starting rate
                        ewma_variance=1.0,
                        last_evaluation=now
                    )
                    await self.redis_client.client.hset(
                        baseline_key,
                        mapping={
                            "ewma_rate": str(baseline.ewma_rate),
                            "ewma_variance": str(baseline.ewma_variance),
                            "last_evaluation": str(baseline.last_evaluation)
                        }
                    )
                    await self.redis_client.client.expire(baseline_key, 3600) # Expire after 1 hour of inactivity
                    current_rate = float(count)
                else:
                    last_eval = float(last_eval_val)
                    ewma_rate = float(ewma_rate_val)
                    ewma_variance = float(ewma_var_val or 1.0)
                    
                    dt = now - last_eval
                    if dt >= interval:
                        # Interval completed, update baseline
                        current_rate = count / dt
                        
                        # EWMA updates
                        diff = current_rate - ewma_rate
                        new_ewma_rate = ewma_rate + (alpha * diff)
                        # EWMA Variance update
                        new_ewma_variance = (1.0 - alpha) * (ewma_variance + alpha * diff * diff)
                        
                        baseline = ClientBaseline(
                            client_ip=client_ip,
                            ewma_rate=new_ewma_rate,
                            ewma_variance=max(0.1, new_ewma_variance),
                            last_evaluation=now
                        )
                        
                        # Save back to Redis
                        await self.redis_client.client.hset(
                            baseline_key,
                            mapping={
                                "ewma_rate": str(baseline.ewma_rate),
                                "ewma_variance": str(baseline.ewma_variance),
                                "last_evaluation": str(baseline.last_evaluation)
                            }
                        )
                        # Reset counter key
                        await self.redis_client.client.delete(counter_key)
                    else:
                        # Use existing baseline
                        baseline = ClientBaseline(
                            client_ip=client_ip,
                            ewma_rate=ewma_rate,
                            ewma_variance=ewma_variance,
                            last_evaluation=last_eval
                        )
                        # Estimate current rate based on requests in the current active interval so far
                        current_rate = count / max(0.1, dt)
            except Exception as e:
                logger.error(f"Redis-backed anomaly detection failed: {e}. Falling back to in-memory.")

        # Fallback to local in-memory tracking
        if baseline is None:
            baseline, current_rate = self._get_in_memory_baseline(client_ip, interval, alpha, now)

        # Calculate Z-score
        std_dev = math.sqrt(baseline.ewma_variance)
        if std_dev < 1.0:
            std_dev = 1.0  # Cap standard deviation to avoid noise under low traffic
            
        z_score = (current_rate - baseline.ewma_rate) / std_dev
        z_score = max(0.0, z_score)  # Only penalize rate spikes
        
        # Calculate anomaly score (normalized between 0.0 and 1.0)
        anomaly_score = min(max(z_score / z_threshold, 0.0), 1.0)
        
        reason = "normal"
        if anomaly_score >= 0.8:
            reason = "critical_anomaly_spike"
        elif anomaly_score >= 0.3:
            reason = "warning_anomaly_trend"
            
        return AnomalyScore(
            client_ip=client_ip,
            score=anomaly_score,
            reason=reason,
            timestamp=now
        )

    def _get_in_memory_baseline(self, client_ip: str, interval: int, alpha: float, now: float) -> Tuple[ClientBaseline, float]:
        # Update counter
        counter_state = self._fallback_counters.get(client_ip)
        if counter_state is None:
            count = 1
            start_time = now
            self._fallback_counters[client_ip] = (count, start_time)
        else:
            count, start_time = counter_state
            count += 1
            self._fallback_counters[client_ip] = (count, start_time)

        # Update baseline
        baseline = self._fallback_baselines.get(client_ip)
        if baseline is None:
            baseline = ClientBaseline(
                client_ip=client_ip,
                ewma_rate=1.0,
                ewma_variance=1.0,
                last_evaluation=now
            )
            self._fallback_baselines[client_ip] = baseline
            current_rate = float(count)
        else:
            dt = now - baseline.last_evaluation
            if dt >= interval:
                current_rate = count / dt
                diff = current_rate - baseline.ewma_rate
                
                new_rate = baseline.ewma_rate + (alpha * diff)
                new_var = (1.0 - alpha) * (baseline.ewma_variance + alpha * diff * diff)
                
                baseline = ClientBaseline(
                    client_ip=client_ip,
                    ewma_rate=new_rate,
                    ewma_variance=max(0.1, new_var),
                    last_evaluation=now
                )
                self._fallback_baselines[client_ip] = baseline
                # Reset counter
                self._fallback_counters[client_ip] = (0, now)
            else:
                current_rate = count / max(0.1, dt)
                
        return baseline, current_rate

    def detect_slowloris(self, client_ip: str, payload_size: int, duration_seconds: float) -> bool:
        config = self.config_manager.get_config()
        slowloris_cfg = config.detection.slowloris
        
        if not slowloris_cfg.enabled:
            return False
            
        # Slowloris fingerprint:
        # Request is slow (duration is long) but has sent very few payload bytes
        if duration_seconds > slowloris_cfg.max_request_duration_seconds:
            # Check ratio: e.g. payload_size is extremely small
            if payload_size < 100:
                logger.warning(f"Slowloris connection flagged from {client_ip}. Duration: {duration_seconds}s, Payload: {payload_size} bytes.")
                return True
        return False
        
    def clear_fallback_db(self):
        self._fallback_baselines.clear()
        self._fallback_counters.clear()
