from locust import HttpUser, task, between
import random

class LegitimateUser(HttpUser):
    # Wait between 0.5 to 2 seconds between tasks
    wait_time = between(0.5, 2.0)

    def on_start(self):
        # Assign a random IP prefix from local networks to simulate a client IP
        self.client_ip = f"192.168.10.{random.randint(1, 254)}"

    @task(5)
    def get_api_data(self):
        self.client.get(
            "/api/data",
            headers={"X-Forwarded-For": self.client_ip}
        )

    @task(1)
    def submit_data(self):
        payload = {
            "key1": "value1",
            "key2": "value2",
            "data": "simulation_load"
        }
        self.client.post(
            "/api/submit",
            json=payload,
            headers={"X-Forwarded-For": self.client_ip}
        )

class AttackerUser(HttpUser):
    # Attackers flood requests with minimal delay
    wait_time = between(0.01, 0.05)

    def on_start(self):
        # Attacker IP
        self.client_ip = f"203.0.113.{random.randint(1, 5)}"

    @task(10)
    def flood_endpoint(self):
        self.client.get(
            "/api/data",
            headers={"X-Forwarded-For": self.client_ip}
        )
        
    @task(1)
    def slowloris_attack(self):
        # Targets slow heavy endpoint
        self.client.get(
            "/api/heavy?delay=5",
            headers={"X-Forwarded-For": self.client_ip}
        )
