
from fastapi import FastAPI
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.redis_client import check_redis_connection
from app.api.v1.router import api_router
from contextlib import asynccontextmanager
from app.services.background_scheduler import (
    start_background_jobs,
    stop_background_jobs,
)

@asynccontextmanager
async def lifespan(app: FastAPI):

    # Start background jobs when FastAPI starts.
    background_tasks = start_background_jobs()

    yield

    # Stop background jobs when FastAPI shuts down.
    await stop_background_jobs(background_tasks)

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    description="Backend API for the unified streaming platform demo",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "https://unified-streaming-backend.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/health/redis")
def redis_health_check():

    connected = check_redis_connection()

    if connected:
        return {
            "status": "connected",
            "service": "redis",
            "message": "Successfully connected to Redis."
        }

    return {
        "status": "disconnected",
        "service": "redis",
        "message": "Could not connect to Redis."
    }
