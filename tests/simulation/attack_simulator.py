import asyncio
import time
import random
import aiohttp
from typing import List, Dict, Any

class TrafficSimulator:
    def __init__(self, target_url: str = "http://localhost:8000"):
        self.target_url = target_url
        self.results: List[Dict[str, Any]] = []
        self.is_running = False

    async def _send_request(self, session: aiohttp.ClientSession, client_ip: str, endpoint: str, method: str = "GET", data: Any = None):
        headers = {
            "X-Forwarded-For": client_ip,
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 ClientIP/{client_ip}"
        }
        
        start_time = time.time()
        try:
            url = f"{self.target_url}{endpoint}"
            async with session.request(method, url, headers=headers, json=data, timeout=12) as response:
                body = await response.text()
                latency = time.time() - start_time
                self.results.append({
                    "timestamp": start_time,
                    "client_ip": client_ip,
                    "endpoint": endpoint,
                    "status": response.status,
                    "latency": latency,
                    "action": "allowed" if response.status == 200 else ("throttled" if response.status == 429 else "blocked")
                })
        except Exception as e:
            latency = time.time() - start_time
            self.results.append({
                "timestamp": start_time,
                "client_ip": client_ip,
                "endpoint": endpoint,
                "status": 0,
                "latency": latency,
                "error": str(e),
                "action": "error"
            })

    async def run_client_traffic(self, client_ip: str, endpoint: str, request_rate: float, duration: float):
        """
        Simulate a single client sending traffic.
        
        Args:
            client_ip: Spoofed IP of the client
            endpoint: Route path
            request_rate: Number of requests per second
            duration: Active period in seconds
        """
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            interval = 1.0 / request_rate
            
            while self.is_running and (time.time() - start_time) < duration:
                asyncio.create_task(self._send_request(session, client_ip, endpoint))
                # Add slight jitter to randomize arrival times
                jitter = random.uniform(-0.1 * interval, 0.1 * interval)
                await asyncio.sleep(max(0.001, interval + jitter))

    async def simulate_baseline(self, duration: float = 20.0):
        """
        Profile 1: Legitimate baseline traffic
        10 distinct IPs sending standard request volume (~1-2 req/s per IP)
        """
        print(f"\n[Simulator] Starting Legitimate Baseline traffic profile for {duration}s...")
        self.is_running = True
        
        # 10 Legitimate IPs
        client_ips = [f"192.168.10.{i}" for i in range(1, 11)]
        
        tasks = []
        for ip in client_ips:
            # Random request rate between 1.0 and 2.0 req/s
            rate = random.uniform(1.0, 2.0)
            tasks.append(self.run_client_traffic(ip, "/api/data", rate, duration))
            
        await asyncio.gather(*tasks)
        print("[Simulator] Finished Legitimate Baseline traffic profile.")

    async def simulate_volumetric_flood(self, duration: float = 20.0):
        """
        Profile 2: Sudden volumetric spike (flood)
        3 attacker IPs sending extreme request volume (~50 req/s per IP)
        """
        print(f"\n[Simulator] Starting Volumetric DDoS Flood traffic profile for {duration}s...")
        self.is_running = True
        
        # 3 Attacking IPs
        attacker_ips = [f"203.0.113.{i}" for i in range(1, 4)]
        
        tasks = []
        for ip in attacker_ips:
            # 50 req/s per IP
            tasks.append(self.run_client_traffic(ip, "/api/data", 50.0, duration))
            
        await asyncio.gather(*tasks)
        print("[Simulator] Finished Volumetric DDoS Flood traffic profile.")

    async def simulate_low_and_slow(self, duration: float = 20.0):
        """
        Profile 3: Distributed low-and-slow attack
        30 simulated IPs sending requests slowly to a heavy endpoint (/api/heavy?delay=2)
        Each IP sends 1 request every 3 seconds (~0.33 req/s)
        This is designed to tie up backend server capacity and check global monitor response
        """
        print(f"\n[Simulator] Starting Distributed Low-and-Slow attack traffic profile for {duration}s...")
        self.is_running = True
        
        # 30 Attacking IPs
        attacker_ips = [f"198.51.100.{i}" for i in range(1, 31)]
        
        tasks = []
        for ip in attacker_ips:
            # 1 request every 3 seconds targeting the heavy endpoint
            tasks.append(self.run_client_traffic(ip, "/api/heavy?delay=2", 0.33, duration))
            
        await asyncio.gather(*tasks)
        print("[Simulator] Finished Distributed Low-and-Slow attack traffic profile.")

    def stop(self):
        self.is_running = False

    def print_summary(self) -> Dict[str, Any]:
        total = len(self.results)
        if total == 0:
            print("[Simulator] No results to analyze.")
            return {}

        allowed = sum(1 for r in self.results if r.get("action") == "allowed")
        throttled = sum(1 for r in self.results if r.get("action") == "throttled")
        blocked = sum(1 for r in self.results if r.get("action") == "blocked")
        errors = sum(1 for r in self.results if r.get("action") == "error")

        avg_latency = sum(r.get("latency", 0) for r in self.results) / total
        
        print("\n" + "="*50)
        print(" ATTACK SIMULATION SUMMARY ")
        print("="*50)
        print(f"Total Requests Sent: {total}")
        print(f"Allowed Requests:    {allowed} ({allowed/total*100:.2f}%)")
        print(f"Throttled (429):     {throttled} ({throttled/total*100:.2f}%)")
        print(f"Blocked (403):       {blocked} ({blocked/total*100:.2f}%)")
        print(f"Errors/Outages:      {errors} ({errors/total*100:.2f}%)")
        print(f"Average Latency:     {avg_latency*1000:.2f}ms")
        print("="*50)
        
        return {
            "total_requests": total,
            "allowed": allowed,
            "throttled": throttled,
            "blocked": blocked,
            "errors": errors,
            "average_latency_ms": avg_latency * 1000
        }
