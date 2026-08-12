import asyncio
import logging
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI(title="Sample Backend Service")

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "cpu_usage_percent": 12.5,
        "memory_usage_percent": 45.2,
        "active_connections": 14
    }

@app.get("/api/data")
async def get_data():
    return {
        "message": "Hello from the backend!",
        "payload": {
            "items": [1, 2, 3, 4, 5],
            "details": "This represents resource data served by the application."
        }
    }

@app.get("/api/heavy")
async def heavy_endpoint(delay: float = 1.0):
    # Simulate a heavy, slow database or calculation request
    logger.info(f"Simulating heavy endpoint with delay: {delay}s")
    # Clamp delay to prevent abuse in testing
    delay = min(max(0.0, delay), 10.0)
    await asyncio.sleep(delay)
    return {
        "message": f"Successfully finished slow processing after {delay} seconds."
    }

@app.post("/api/submit")
async def submit_data(request: Request):
    body = await request.json()
    return {
        "status": "received",
        "processed_keys": list(body.keys()),
        "payload_size_received": len(str(body))
    }
