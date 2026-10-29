
from fastapi import FastAPI

from app.core.config import settings
from app.api.v1.router import api_router

app = FastAPI(
    title=settings.app_name,
    description="Backend API for the unified streaming platform demo",
    version="1.0.0",
)

app.include_router(
    api_router,
    prefix=settings.api_v1_prefix,
)

for route in app.routes:
    if hasattr(route, "methods") and hasattr(route, "path"):
        if "home" in route.path or "platform" in route.path:
            print("REGISTERED ROUTE:", route.methods, route.path)

@app.get("/")
def home():
    return {
        "message": "Streaming Platform API is running!",
        "status": "success",
    }

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "streaming-platform-backend",
    }
