from fastapi import APIRouter

from ecommerce_ai_agent.api.v1.chat import router as chat_router

router = APIRouter(prefix="/api/v1")
router.include_router(chat_router, tags=["chat"])
