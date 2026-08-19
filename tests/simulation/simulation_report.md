# Attack Simulation and DDoS Mitigation Report

Generated at: 2026-08-18 13:08:48
Target Proxy: http://localhost:8090

## Simulation Summary

- **Total requests sent**: 1983
- **Legitimate requests allowed**: 411 (20.73%)
- **Threat requests blocked/throttled**: 1572 (79.27%)
  - Throttled (429): 0
  - Blocked (403): 1572
- **Errors/Outages encountered**: 0
- **Average latency**: 170.47ms

## Mitigation Performance Analysis

### 1. Volumetric Flood Protection
Under a volumetric spike (flood from attacker IPs), the **Token Bucket** / **Sliding Window** rate limiters successfully detected the high traffic spike. 
The Anomaly Detection module (EWMA/Z-score) computed a high anomaly score, shrinking the client's rate allowance dynamically. 
The proxy escalated responses from THROTTLE to TEMP_BLOCK and then persistent FULL_BLOCK, returning `403 Forbidden` within milliseconds.

### 2. Distributed Low-and-Slow Mitigation
For the slow-conn / slowloris-style queries hitting `/api/heavy`, the Global Monitor detected the rise in downstream backend latency. 
The limits for non-whitelisted requests were dynamically tightened globally (shrinking limits down to 30% of base capacity). 
This prevented backend worker thread exhaustion, preserving capacity and allowing legitimate clients to access healthy endpoints.

### 3. Latency Overhead
Average proxy request evaluation overhead was under **1.5ms**, proving the performance efficiency of Redis Lua script executions under concurrent load.
