# global_pool.py
import asyncpg
from config import DATABASE_URL

pool = None

async def init_db_pool():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    print("[init_db_pool] Connection pool initialized.")

async def get_connection():
    return await pool.acquire()

async def release_connection(conn):
    await pool.release(conn)
