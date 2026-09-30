from aiogram import Dispatcher
from app.handlers.common import router as common_router
from app.handlers.profile import router as profile_router

def register_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(common_router)
    dispatcher.include_router(profile_router)
