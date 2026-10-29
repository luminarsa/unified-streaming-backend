from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.account import router as account_router
from app.api.v1.platforms_administration import router as platforms_administration_router
from app.api.v1.platform_content import router as platform_content_router
from app.api.v1.telemetry import router as telemetry_router
from app.api.v1.subscriptions import router as subscriptions_router

api_router = APIRouter()
api_router.include_router(platform_content_router)
api_router.include_router(platforms_administration_router)
api_router.include_router(auth_router)
api_router.include_router(account_router)
api_router.include_router(telemetry_router)
api_router.include_router(subscriptions_router)