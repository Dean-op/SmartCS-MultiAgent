from fastapi import APIRouter

from ecommerce_ai_agent.api.v1.auth import router as auth_router
from ecommerce_ai_agent.api.v1.chat import router as chat_router
from ecommerce_ai_agent.api.v1.reviews import router as reviews_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router, tags=["auth"])
router.include_router(chat_router, tags=["chat"])
router.include_router(reviews_router, tags=["reviews"])
