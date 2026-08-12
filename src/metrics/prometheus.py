from prometheus_client import Counter, Gauge, Histogram

# HTTP Request metrics
HTTP_REQUESTS_TOTAL = Counter(
    "ratelimit_requests_total",
    "Total HTTP requests received by the rate limiter proxy",
    ["method", "endpoint", "decision"] # decision: allow, throttle, block, challenge
)

# Request blocking metrics
HTTP_BLOCKED_TOTAL = Counter(
    "ratelimit_blocked_total",
    "Total requests blocked/throttled by the rate limiter",
    ["reason", "client_ip"] # reason: client_throttled, client_temp_blocked, client_perm_blocked
)

# Current limits dynamic gauge
CLIENT_CURRENT_LIMIT = Gauge(
    "ratelimit_current_limit",
    "Current adaptive rate limit (req/s) applied to a client IP",
    ["client_ip", "endpoint"]
)

# Anomaly scores distribution
CLIENT_ANOMALY_SCORE = Histogram(
    "ratelimit_anomaly_score",
    "Distribution of anomaly scores computed per client",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]
)

# Latency of the rate limiter evaluation itself
DECISION_DURATION_SECONDS = Histogram(
    "ratelimit_decision_duration_seconds",
    "Time taken in seconds to make a rate limiting decision",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
)

# False positive indicator (count times whitelisted IPs were flagged for throttling/blocking)
FALSE_POSITIVE_INDICATOR = Counter(
    "ratelimit_false_positive_indicator",
    "Number of times whitelisted IPs triggered rate limiting thresholds",
    ["client_ip"]
)
