from aiogram import Dispatcher
from app.handlers.common import router as common_router
from app.handlers.profile import router as profile_router
from app.handlers.menu import router as menu_router
from app.handlers.group import router as group_router
from app.handlers.game import router as game_router
from app.handlers.gameplay import router as gameplay_router

def register_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(common_router)
    dispatcher.include_router(profile_router)
    dispatcher.include_router(menu_router)
    dispatcher.include_router(group_router)
    dispatcher.include_router(game_router)
    dispatcher.include_router(gameplay_router)
