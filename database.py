import base58
from typing import Optional, List, Dict

from config import DATABASE_URL, _LEVELS
from solders.keypair import Keypair
from global_pool import get_connection, release_connection

async def init_db():
    """
    Creates necessary tables if they do not exist and ensures schema is up-to-date.
      - users: user data + referral columns
      - pools: each lottery round, keyed by stake level
      - tickets: tickets including stake level and status
      - group_settings: per-group config
    Ensures at least one OPEN pool exists per level.
    """
    conn = await get_connection()
    try:
        # ---------------- USERS ----------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id             BIGINT PRIMARY KEY,
            username            TEXT,
            first_name          TEXT,
            has_seen_disclaimer BOOLEAN DEFAULT FALSE,
            balance             DOUBLE PRECISION DEFAULT 0,
            total_wins          INT    DEFAULT 0,
            wallet_public_key   TEXT,
            wallet_private_key  TEXT,
            referred_by         BIGINT,
            referral_earnings   DOUBLE PRECISION DEFAULT 0
        );
        """)

        # ---------------- POOLS ----------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS pools (
            pool_id               SERIAL PRIMARY KEY,
            level                 TEXT NOT NULL,
            status                TEXT DEFAULT 'OPEN',
            created_at            TIMESTAMP DEFAULT NOW(),
            completed_at          TIMESTAMP,
            total_pot             DOUBLE PRECISION DEFAULT 0,
            house_fee_tx          TEXT,
            dev_fee_tx            TEXT,
            first_winner_user_id  BIGINT,
            second_winner_user_id BIGINT,
            third_winner_user_id  BIGINT
        );
        """)

        # -------------- TICKETS --------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id     SERIAL PRIMARY KEY,
            pool_id       INT REFERENCES pools(pool_id),
            user_id       BIGINT,
            level         TEXT NOT NULL,
            value         DOUBLE PRECISION,
            status        TEXT NOT NULL DEFAULT 'not_drawn',  -- 'not_drawn', 'won', or 'lost'
            prize_amount  DOUBLE PRECISION DEFAULT 0,
            is_confirmed  BOOLEAN DEFAULT TRUE,
            created_at    TIMESTAMP DEFAULT NOW()
        );
        """)

        # -------------- GROUP SETTINGS ---------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id             BIGINT PRIMARY KEY,
            buy_signals_enabled BOOLEAN DEFAULT TRUE
        );
        """)

        # Ensure one OPEN pool per level
        for lvl in _LEVELS:
            row = await conn.fetchrow(
                "SELECT pool_id FROM pools WHERE status='OPEN' AND level=$1 LIMIT 1",
                lvl
            )
            if not row:
                await conn.execute(
                    "INSERT INTO pools (level, status) VALUES ($1, 'OPEN')",
                    lvl
                )
    finally:
        await release_connection(conn)

# ============================
#         USER HELPERS
# ============================

async def create_or_update_user(
    user_id: int,
    username: str,
    first_name: str,
    referred_by: Optional[int] = None
) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, referred_by)
                 VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE
              SET username   = EXCLUDED.username,
                  first_name = EXCLUDED.first_name
            """,
            user_id, username, first_name, referred_by,
        )
    finally:
        await release_connection(conn)

async def has_seen_disclaimer(user_id: int) -> bool:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT has_seen_disclaimer FROM users WHERE user_id=$1",
            user_id
        )
        return bool(row["has_seen_disclaimer"]) if row else False
    finally:
        await release_connection(conn)

async def set_disclaimer_true(user_id: int) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE users SET has_seen_disclaimer=TRUE WHERE user_id=$1",
            user_id
        )
    finally:
        await release_connection(conn)

async def get_balance(user_id: int) -> float:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT balance FROM users WHERE user_id=$1",
            user_id
        )
        return float(row["balance"]) if row else 0.0
    finally:
        await release_connection(conn)

async def set_balance(user_id: int, new_balance: float) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE users SET balance=$1 WHERE user_id=$2",
            new_balance, user_id
        )
    finally:
        await release_connection(conn)

async def increment_user_wins(user_id: int) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE users SET total_wins = total_wins + 1 WHERE user_id=$1",
            user_id
        )
    finally:
        await release_connection(conn)

# ============================
#     GROUP SETTINGS HELPERS
# ============================

async def set_buy_signals(chat_id: int, enabled: bool) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO group_settings (chat_id, buy_signals_enabled)
            VALUES ($1, $2)
            ON CONFLICT (chat_id) DO UPDATE SET buy_signals_enabled=$2
            """,
            chat_id, enabled,
        )
    finally:
        await release_connection(conn)

async def get_buy_signals_enabled(chat_id: int) -> bool:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT buy_signals_enabled FROM group_settings WHERE chat_id=$1",
            chat_id
        )
        return bool(row["buy_signals_enabled"]) if row else True
    finally:
        await release_connection(conn)

# ============================
#        WALLET HELPERS
# ============================

async def generate_user_wallet(user_id: int) -> Dict[str, Optional[str]]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT wallet_public_key FROM users WHERE user_id=$1",
            user_id
        )
        if row and row["wallet_public_key"]:
            return {"wallet_public_key": row["wallet_public_key"], "wallet_private_key": None}
        keypair = Keypair()
        pub = str(keypair.pubkey())
        priv = base58.b58encode(bytes(keypair)).decode()
        await conn.execute(
            "UPDATE users SET wallet_public_key=$1, wallet_private_key=$2 WHERE user_id=$3",
            pub, priv, user_id
        )
        return {"wallet_public_key": pub, "wallet_private_key": priv}
    finally:
        await release_connection(conn)

# ============================
#       BALANCE SYNC
# ============================

async def sync_user_wallet_balance(user_id: int) -> float:
    from solana_utils import get_wallet_balance
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT wallet_public_key FROM users WHERE user_id=$1",
            user_id
        )
        if not row or not row["wallet_public_key"]:
            return 0.0
        onchain = await get_wallet_balance(row["wallet_public_key"])
        await conn.execute(
            "UPDATE users SET balance=$1 WHERE user_id=$2",
            onchain, user_id
        )
        return onchain
    finally:
        await release_connection(conn)

# ============================
#       STATS & HISTORY
# ============================

async def get_user_stats(user_id: int) -> Dict[str, float]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT 
            COUNT(*)::INT                                  AS total_tickets,
            COALESCE(SUM(value), 0)                       AS total_spent,
            COALESCE(SUM(prize_amount), 0)                AS total_won,
            SUM(CASE WHEN status='won' THEN 1 ELSE 0 END)::INT AS total_wins
            FROM tickets WHERE user_id=$1 AND is_confirmed = TRUE
            """,
            user_id
        )
        total_tickets = row["total_tickets"] or 0
        win_rate = (row["total_wins"] / total_tickets * 100.0) if total_tickets else 0.0
        return {
            "total_tickets": total_tickets,
            "total_spent": float(row["total_spent"]),
            "total_won": float(row["total_won"]),
            "total_wins": row["total_wins"],
            "win_rate": win_rate,
        }
    finally:
        await release_connection(conn)

async def get_user_history(user_id: int, limit: int = 5) -> List[Dict]:
    conn = await get_connection()
    try:
        records = await conn.fetch(
            """
            SELECT ticket_id, pool_id, level, status, prize_amount, created_at
            FROM tickets
            WHERE user_id=$1 AND is_confirmed = TRUE
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
        return [dict(rec) for rec in records]
    finally:
        await release_connection(conn)

# ============================
#       REFERRAL HELPERS
# ============================

async def get_referral_stats(user_id: int) -> Dict[str, float]:
    conn = await get_connection()
    try:
        earnings = await conn.fetchval(
            "SELECT COALESCE(referral_earnings,0) FROM users WHERE user_id=$1",
            user_id
        )
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE referred_by=$1",
            user_id
        )
        return {
            "referred_count": count or 0,
            "referral_earnings": float(earnings or 0.0),
        }
    finally:
        await release_connection(conn)
