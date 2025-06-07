import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

DEV_WALLET = os.getenv("DEV_WALLET", "")
HOUSE_WALLET = os.getenv("HOUSE_WALLET", "")

POOL_PUBLIC_KEY = os.getenv("POOL_PUBLIC_KEY", "")
POOL_PRIVATE_KEY = os.getenv("POOL_PRIVATE_KEY", "")

SOLANA_RPC_ENDPOINT = os.getenv("SOLANA_RPC_ENDPOINT", "https://api.mainnet-beta.solana.com")
POOL_TICKET_PRICE = float(os.getenv("POOL_TICKET_PRICE", "0.1"))
POOL_SIZE = int(os.getenv("POOL_SIZE", "20"))

GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "TestServ123_Bot")

_LEVELS = ["low", "mid", "high"]

_LEVEL_NAMES = {
    "low":  "Lucky Penny",
    "mid":  "Gold Rush",
    "high": "High-Roller",
}
_LEVEL_EMOJIS = {
    "low":  "🎈",
    "mid":  "💰",
    "high": "🎲",
}

_LEVEL_PRICES = {
    "low":  0.05,
    "mid":  0.1,
    "high": 0.5,
}

if not BOT_TOKEN:
    raise ValueError("Missing BOT_TOKEN in .env")
if not DATABASE_URL:
    raise ValueError("Missing DATABASE_URL in .env")
if not DEV_WALLET:
    raise ValueError("Missing DEV_WALLET in .env")
if not HOUSE_WALLET:
    raise ValueError("Missing HOUSE_WALLET in .env")
if not POOL_PUBLIC_KEY:
    raise ValueError("Missing POOL_PUBLIC_KEY in .env")
if not POOL_PRIVATE_KEY:
    raise ValueError("Missing POOL_PRIVATE_KEY in .env")
if not BOT_USERNAME:
    raise ValueError("Missing BOT_USERNAME in .env")