import time
import logging
from typing import Dict, Tuple, Optional

from src.config.manager import ConfigManager
from src.storage.redis_client import RedisClient
from src.enforcement.models import RateLimitDecision, EscalationLevel
from src.enforcement.algorithms.token_bucket import TokenBucketLimiter
from src.enforcement.algorithms.sliding_window import SlidingWindowLimiter
from src.enforcement.algorithms.leaky_bucket import LeakyBucketLimiter
from src.detection.detector import AnomalyDetector
from src.detection.global_monitor import GlobalSystemMonitor

logger = logging.getLogger("arl.enforcement.engine")

class EnforcementEngine:
    def __init__(
        self,
        config_manager: ConfigManager,
        redis_client: RedisClient,
        detector: AnomalyDetector,
        global_monitor: GlobalSystemMonitor
    ):
        self.config_manager = config_manager
        self.redis_client = redis_client
        self.detector = detector
        self.global_monitor = global_monitor
        
        # Initialize limiters
        self.token_bucket = TokenBucketLimiter(redis_client)
        self.sliding_window = SlidingWindowLimiter(redis_client)
        self.leaky_bucket = LeakyBucketLimiter(redis_client)
        
        # In-memory fallbacks for escalation states
        # client_ip -> (escalation_level, violations_count, last_violation_time, block_until)
        self._fallback_escalations: Dict[str, Tuple[EscalationLevel, int, float, float]] = {}

    def _get_limiter(self, algorithm_name: str):
        if algorithm_name == "sliding_window":
            return self.sliding_window
        elif algorithm_name == "leaky_bucket":
            return self.leaky_bucket
        return self.token_bucket # default is token_bucket

    async def _get_escalation_state(self, client_ip: str) -> Tuple[EscalationLevel, int, float, float]:
        now = time.time()
        
        if self.redis_client.client:
            try:
                key = f"escalation:{client_ip}"
                data = await self.redis_client.client.hmget(
                    key, "level", "violations", "last_violation", "block_until"
                )
                
                level_val, violations_val, last_viol_val, block_until_val = data
                
                if level_val:
                    level = EscalationLevel(int(level_val))
                    violations = int(violations_val or 0)
                    last_violation = float(last_viol_val or 0.0)
                    block_until = float(block_until_val or 0.0)
                    return level, violations, last_violation, block_until
            except Exception as e:
                logger.error(f"Redis fetch escalation state failed: {e}")

        # Fallback to local in-memory
        state = self._fallback_escalations.get(client_ip)
        if state is None:
            return EscalationLevel.ALLOW, 0, 0.0, 0.0
        return state

    async def _save_escalation_state(
        self,
        client_ip: str,
        level: EscalationLevel,
        violations: int,
        last_violation: float,
        block_until: float
    ):
        config = self.config_manager.get_config()
        cooldown = config.escalation.cooldown_seconds
        
        if self.redis_client.client:
            try:
                key = f"escalation:{client_ip}"
                await self.redis_client.client.hset(
                    key,
                    mapping={
                        "level": str(level.value),
                        "violations": str(violations),
                        "last_violation": str(last_violation),
                        "block_until": str(block_until)
                    }
                )
                # Expire after twice the cooldown period or block duration
                ttl = max(cooldown * 2, int(block_until - time.time()) + 60)
                await self.redis_client.client.expire(key, ttl)
                return
            except Exception as e:
                logger.error(f"Redis save escalation state failed: {e}")

        # Fallback to local in-memory
        self._fallback_escalations[client_ip] = (level, violations, last_violation, block_until)

    def _get_base_limits(self, path: str) -> Tuple[float, float, int]:
        config = self.config_manager.get_config()
        defaults = config.defaults
        
        # Check endpoint overrides
        for override in config.endpoints:
            # Simple prefix match
            if path.startswith(override.path):
                win = override.window_seconds if override.window_seconds else defaults.window_seconds
                return override.rate, override.capacity, win
                
        return defaults.rate, defaults.capacity, defaults.window_seconds

    async def evaluate_request(self, client_ip: str, path: str, method: str, is_whitelisted: bool = False) -> RateLimitDecision:
        now = time.time()
        
        # Whitelisted clients bypass all rate limiting
        if is_whitelisted:
            return RateLimitDecision(
                allowed=True,
                escalation_level=EscalationLevel.ALLOW,
                reason_code="CLIENT_WHITELISTED",
                remaining_tokens=9999.0,
                client_ip=client_ip
            )
            
        config = self.config_manager.get_config()
        
        # 1. Fetch current escalation state
        level, violations, last_violation, block_until = await self._get_escalation_state(client_ip)
        
        # Check if cooldown is applicable (client has been quiet for cooldown_seconds)
        cooldown = config.escalation.cooldown_seconds
        if level > EscalationLevel.ALLOW and (now - last_violation) >= cooldown:
            logger.info(f"Client {client_ip} has cooled down. Resetting escalation level to ALLOW.")
            level = EscalationLevel.ALLOW
            violations = 0
            block_until = 0.0
            await self._save_escalation_state(client_ip, level, violations, now, block_until)
            
        # Check if block is active
        if level in (EscalationLevel.TEMP_BLOCK, EscalationLevel.FULL_BLOCK):
            if level == EscalationLevel.TEMP_BLOCK and now >= block_until:
                # Temp block expired, de-escalate to throttle
                logger.info(f"Client {client_ip} temporary block expired. De-escalating to THROTTLE.")
                level = EscalationLevel.THROTTLE
                violations = config.escalation.levels["throttle"].trigger_violations
                block_until = 0.0
                await self._save_escalation_state(client_ip, level, violations, now, block_until)
            else:
                reason = "CLIENT_TEMP_BLOCKED" if level == EscalationLevel.TEMP_BLOCK else "CLIENT_PERM_BLOCKED"
                wait_sec = max(0.0, block_until - now) if level == EscalationLevel.TEMP_BLOCK else 99999.0
                return RateLimitDecision(
                    allowed=False,
                    escalation_level=level,
                    reason_code=reason,
                    remaining_tokens=0.0,
                    wait_time_seconds=wait_sec,
                    client_ip=client_ip
                )

        # 2. Get base rate/capacity and calculate anomaly + system load adjustments
        base_rate, base_capacity, window_seconds = self._get_base_limits(path)
        
        anomaly = await self.detector.calculate_anomaly_score(client_ip, path)
        anomaly_score = anomaly.score
        
        sys_load = await self.global_monitor.get_system_load()
        load_multiplier = sys_load.load_multiplier
        
        # Compute adaptive limits
        sev_factor = config.detection.severity_factor
        adaptive_factor = (1.0 - (anomaly_score * sev_factor)) * load_multiplier
        # Ensure we don't drop rate/capacity below minimum functional thresholds
        adaptive_rate = max(0.1, base_rate * adaptive_factor)
        adaptive_capacity = max(1.0, base_capacity * adaptive_factor)
        
        # 3. Check rate limit
        algorithm = config.defaults.algorithm
        limiter = self._get_limiter(algorithm)
        
        client_key = f"{client_ip}:{path}"
        allowed, remaining, wait_time = await limiter.check_limit(
            client_key,
            rate=adaptive_rate,
            capacity=adaptive_capacity,
            window_seconds=window_seconds,
            requested=1
        )
        
        if allowed:
            # Request allowed, return success decision
            return RateLimitDecision(
                allowed=True,
                escalation_level=level,
                reason_code="REQUEST_ALLOWED",
                remaining_tokens=remaining,
                anomaly_score=anomaly_score,
                current_limit=adaptive_rate,
                client_ip=client_ip,
                metadata={
                    "base_rate": base_rate,
                    "load_multiplier": load_multiplier
                }
            )
        else:
            # Limit exceeded, increment violations and check escalation
            violations += 1
            last_violation = now
            
            # Check transitions
            levels_cfg = config.escalation.levels
            new_level = level
            
            # Determine new escalation level based on violations count OR anomaly score
            if violations >= levels_cfg["full_block"].trigger_violations or anomaly_score >= levels_cfg["full_block"].trigger_anomaly_score:
                new_level = EscalationLevel.FULL_BLOCK
                block_until = now + 999999.0 # Permanent block simulation
            elif violations >= levels_cfg["temp_block"].trigger_violations or anomaly_score >= levels_cfg["temp_block"].trigger_anomaly_score:
                new_level = EscalationLevel.TEMP_BLOCK
                block_until = now + config.escalation.temp_block_duration
            elif violations >= levels_cfg["challenge"].trigger_violations or anomaly_score >= levels_cfg["challenge"].trigger_anomaly_score:
                new_level = EscalationLevel.CHALLENGE
            elif violations >= levels_cfg["throttle"].trigger_violations or anomaly_score >= levels_cfg["throttle"].trigger_anomaly_score:
                new_level = EscalationLevel.THROTTLE
                
            if new_level != level:
                logger.warning(f"Client {client_ip} escalated from {level.name} to {new_level.name}. Reason: violations={violations}, anomaly={anomaly_score:.2f}")
                level = new_level
                
            await self._save_escalation_state(client_ip, level, violations, last_violation, block_until)
            
            reason = "LIMIT_EXCEEDED"
            if level == EscalationLevel.THROTTLE:
                reason = "CLIENT_THROTTLED"
            elif level == EscalationLevel.CHALLENGE:
                reason = "CLIENT_CHALLENGE_REQUIRED"
            elif level == EscalationLevel.TEMP_BLOCK:
                reason = "CLIENT_TEMP_BLOCKED"
            elif level == EscalationLevel.FULL_BLOCK:
                reason = "CLIENT_PERM_BLOCKED"
                
            return RateLimitDecision(
                allowed=False,
                escalation_level=level,
                reason_code=reason,
                remaining_tokens=remaining,
                wait_time_seconds=wait_time if wait_time > 0 else (1.0 / adaptive_rate),
                anomaly_score=anomaly_score,
                current_limit=adaptive_rate,
                client_ip=client_ip
            )
            
    def clear_fallback_db(self):
        self._fallback_escalations.clear()
        self.token_bucket.clear_fallback_db()
        self.sliding_window.clear_fallback_db()
        self.leaky_bucket.clear_fallback_db()
