import asyncio
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from database import init_db
from bot import router, BOT_TOKEN  # We'll import the router & BOT_TOKEN from your bot.py

# On Windows, set the event loop policy to WindowsSelectorEventLoopPolicy.
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    # Initialize DB schema and ensure at least one open pool exists.
    await init_db()

    # Create Bot & Dispatcher
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher(storage=MemoryStorage())

    # Include all handlers (callbacks, messages, states) from your router
    dp.include_router(router)

    # Start polling
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
