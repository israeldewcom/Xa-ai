"""Load test. Run: locust -f benchmarks/locustfile.py --host http://localhost:8000"""
import random
from locust import HttpUser, between, task


class XAUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        email = f"load-{random.randint(0, 10**9)}@x.com"
        self.client.post("/api/v1/auth/register", json={
            "email": email, "password": "loadtestpw123",
        })
        r = self.client.post("/api/v1/auth/login", json={
            "email": email, "password": "loadtestpw123",
        })
        self.token = r.json()["access_token"]
        self.client.headers["Authorization"] = f"Bearer {self.token}"

    @task(5)
    def chat(self):
        self.client.post("/api/v1/chat", json={"message": "hello"})

    @task(2)
    def upload(self):
        self.client.post("/api/v1/files", files={
            "file": ("t.txt", b"hello", "text/plain"),
        })

    @task(1)
    def quotas(self):
        self.client.get("/api/v1/account/quotas")
