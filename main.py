# main.py
# -*- coding: utf-8 -*-
import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from global_pool import init_db_pool
from database import init_db
from bot import router

# Op Windows gebruik je de SelectorEventLoopPolicy
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    # 1) Start de DB-pool
    await init_db_pool()
    print("[startup] DB connection pool initialized.")

    # 2) Run je migrations / schema-init
    await init_db()
    print("[startup] Database schema ready.")

    # 3) Maak Bot & Dispatcher
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher(storage=MemoryStorage())

    # 4) Voeg al je handlers toe
    dp.include_router(router)

    # 5) Start polling
    print("[startup] Bot is polling now...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
