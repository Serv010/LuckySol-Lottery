import random
import asyncio
import time
from collections import defaultdict

from aiogram import Bot
from aiogram.types import CallbackQuery, FSInputFile

from global_pool import get_connection, release_connection
from config import (
    DEV_WALLET,
    HOUSE_WALLET,
    POOL_PUBLIC_KEY,
    POOL_PRIVATE_KEY,
    GROUP_CHAT_ID,
    POOL_SIZE,
    _LEVEL_EMOJIS,
    _LEVEL_NAMES,
)
from solana_utils import get_wallet_balance, pay_sol, batch_pay_sol
from keyboards import (
    play_menu_keyboard,
    play_again_keyboard,
    group_buy_signal_keyboard,
)

# Anti-spam cooldown config (seconds)
BUY_COOLDOWN = 6
last_buy_time = defaultdict(float)

async def buy_ticket(
    user_id: int,
    ticket_price: float,
    level: str,
    cbq: CallbackQuery,
    bot: Bot,
    num_tickets: int = 1
) -> dict:
    """
    Clean version — uses pooled connections, updates ticket status.
    """
    key = f"{user_id}_{level}"
    now = time.time()
    if now - last_buy_time[key] < BUY_COOLDOWN:
        return {"success": False, "message": f"⏱️ Please wait {BUY_COOLDOWN}s before buying again."}
    last_buy_time[key] = now

    conn = await get_connection()
    try:
        async with conn.transaction():
            # 1) Lock pool
            row = await conn.fetchrow(
                "SELECT pool_id FROM pools WHERE status='OPEN' AND level=$1 "
                "ORDER BY pool_id LIMIT 1 FOR UPDATE SKIP LOCKED",
                level
            )
            if not row:
                return {"success": False, "message": "⛔ No open pool at this level!"}
            pool_id = row["pool_id"]

            # 2) Spots left
            count = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pool_id)
            remaining = POOL_SIZE - count
            if remaining < num_tickets:
                return {"success": False, "message": f"⛔ Only {remaining} spot(s) left."}

            # 3) Wallet keys
            wallet = await conn.fetchrow(
                "SELECT wallet_public_key, wallet_private_key FROM users WHERE user_id=$1", user_id
            )
            if not wallet or not wallet["wallet_public_key"]:
                return {"success": False, "message": "⚠️ Wallet not found. Use /start first."}
            pub, priv = wallet["wallet_public_key"], wallet["wallet_private_key"]

            # 4) On-chain balance
            onchain = await get_wallet_balance(pub)
            total_cost = ticket_price * num_tickets
            if onchain < total_cost:
                return {"success": False, "message": f"💸 Insufficient funds: {onchain:.4f} vs {total_cost:.4f}"}

            # 5) Transfer funds
            try:
                tx_sig = await pay_sol(priv, pub, POOL_PUBLIC_KEY, total_cost)
            except Exception as e:
                return {"success": False, "message": f"❌ Transfer failed: {e}"}

            # 6) Insert tickets
            for _ in range(num_tickets):
                await conn.execute(
                    "INSERT INTO tickets (pool_id, user_id, level, value, status) VALUES ($1,$2,$3,$4,'not_drawn')",
                    pool_id, user_id, level, ticket_price
                )

        # After transaction:
        final_count = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pool_id)
        pot = await conn.fetchval("SELECT COALESCE(SUM(value), 0) FROM tickets WHERE pool_id=$1", pool_id)

        # Trigger draw if full
        if final_count == POOL_SIZE:
            asyncio.create_task(run_lottery(bot, pool_id))

        return {
            "success": True,
            "message": f"✅ Bought {num_tickets} ticket(s).",
            "pool_id": pool_id,
            "pot": pot,
            "spots_left": POOL_SIZE - final_count,
            "tickets_bought": num_tickets
        }

    except Exception as e:
        return {"success": False, "message": f"🚫 Purchase failed: {e}"}
    finally:
        await release_connection(conn)

async def run_lottery(bot: Bot, pool_id: int):
    from collections import defaultdict
    from aiogram.types import FSInputFile

    conn = await get_connection()
    try:
        async with conn.transaction():
            # a) Lock & verify pool
            row = await conn.fetchrow(
                "SELECT status, level FROM pools WHERE pool_id=$1 FOR UPDATE",
                pool_id
            )
            if not row or row["status"] != 'OPEN':
                return
            level = row["level"]

            # b) Fetch tickets not yet drawn
            tickets = await conn.fetch(
                "SELECT ticket_id, user_id, value FROM tickets WHERE pool_id=$1 AND status='not_drawn'",
                pool_id
            )
            pot = sum(t["value"] for t in tickets)

            # c) Pick winners
            first = random.choice(tickets)
            rest1 = [t for t in tickets if t["ticket_id"] != first["ticket_id"]]
            second = random.choice(rest1) if rest1 else None
            rest2 = [t for t in rest1 if second and t["ticket_id"] != second["ticket_id"]]
            third = random.choice(rest2) if rest2 else None

            # d) Compute prize splits
            first_prize  = pot * 0.60
            second_prize = pot * 0.20
            third_prize  = pot * 0.10
            house_fee    = pot * 0.08
            dev_fee      = pot * 0.02

            # e) Mark winners in tickets table
            async def mark_winner(ticket, prize):
                await conn.execute(
                    "UPDATE tickets SET status='won', prize_amount=$1 WHERE ticket_id=$2",
                    prize, ticket["ticket_id"]
                )
            await mark_winner(first, first_prize)
            if second: await mark_winner(second, second_prize)
            if third:  await mark_winner(third, third_prize)

            # f) Mark all other tickets as lost
            ids_won = [first["ticket_id"]] + ([second["ticket_id"]] if second else []) + ([third["ticket_id"]] if third else [])
            await conn.execute(
                """
                UPDATE tickets
                   SET status = 'lost'
                 WHERE pool_id = $1
                   AND NOT ticket_id = ANY($2::int[])
                """,
                pool_id,
                ids_won
            )

            # g) Build list of transfers (winners + fees)
            transfers = []
            for ticket, amount in ((first, first_prize), (second, second_prize), (third, third_prize)):
                if ticket and amount > 0:
                    pub = await conn.fetchval(
                        "SELECT wallet_public_key FROM users WHERE user_id=$1",
                        ticket["user_id"]
                    )
                    if pub:
                        transfers.append({"recipient": pub, "amount_sol": amount})

            transfers.append({"recipient": HOUSE_WALLET, "amount_sol": house_fee})
            transfers.append({"recipient": DEV_WALLET,   "amount_sol": dev_fee})

            # h) Compute and add referral bonuses (3%)
            REF_PCT = 0.03
            bonus_rows = await conn.fetch(
                """
                SELECT u.referred_by, t.value
                  FROM tickets t
                  JOIN users u ON t.user_id = u.user_id
                 WHERE t.pool_id = $1
                   AND u.referred_by IS NOT NULL
                """,
                pool_id
            )
            bonuses = defaultdict(float)
            for br in bonus_rows:
                bonuses[br["referred_by"]] += br["value"] * REF_PCT
            for ref_id, amt in bonuses.items():
                if amt > 0:
                    pub_ref = await conn.fetchval(
                        "SELECT wallet_public_key FROM users WHERE user_id=$1",
                        ref_id
                    )
                    if pub_ref:
                        transfers.append({"recipient": pub_ref, "amount_sol": amt})
                        await conn.execute(
                            "UPDATE users SET referral_earnings = referral_earnings + $1 WHERE user_id=$2",
                            amt, ref_id
                        )

            # i) Execute batch transaction on-chain
            batch_sig = await batch_pay_sol(POOL_PRIVATE_KEY, POOL_PUBLIC_KEY, transfers)

            # j) Close the pool with metadata
            await conn.execute(
                """
                UPDATE pools
                   SET status               = 'CLOSED',
                       completed_at         = NOW(),
                       total_pot            = $1,
                       first_winner_user_id = $2,
                       second_winner_user_id= $3,
                       third_winner_user_id = $4,
                       house_fee_tx         = $5,
                       dev_fee_tx           = $6
                 WHERE pool_id = $7
                """,
                pot,
                first["user_id"],
                second["user_id"] if second else None,
                third["user_id"]  if third  else None,
                f"batch:{batch_sig}",
                f"batch:{batch_sig}",
                pool_id
            )
        # ─── end transaction block ───

        # 1) Notify winners privately
        photo = FSInputFile("WinnerLucky.jpg")
        for ticket, medal, prize in [
            (first,  "🏆", first_prize),
            (second, "🥈", second_prize),
            (third,  "🥉", third_prize)
        ]:
            if ticket:
                await bot.send_photo(
                    chat_id = ticket["user_id"],
                    photo   = photo,
                    caption = (
                        f"{medal} <b>CONGRATULATIONS!</b>\n"
                        f"You got {medal} Place in Pool <b>#{pool_id}</b>\n"
                        f"Prize: <b>{prize:.2f} SOL</b>\n\n"
                        f"Batch Tx: <code>{batch_sig}</code>"
                    ),
                    parse_mode = "HTML",
                    reply_markup = play_again_keyboard()
                )

        # 2) Notify losers
        all_ids = {t["user_id"] for t in tickets}
        win_ids = {first["user_id"]} | ({second["user_id"]} if second else set()) | ({third["user_id"]} if third else set())
        for loser in all_ids - win_ids:
            await bot.send_message(
                loser,
                "😢 <b>No luck this time—try again next round!</b>",
                parse_mode="HTML",
                reply_markup=play_menu_keyboard(level, None, None, None)
            )

        # 3) Build group announcement
        stake_emoji = _LEVEL_EMOJIS[level]
        stake_name  = _LEVEL_NAMES[level]
        lines = [f"🎉 <b>Pool #{pool_id} — {stake_emoji} {stake_name}</b> concluded!"]

        async def _tag(uid, medal, amt):
            r = await conn.fetchrow(
                "SELECT first_name, username FROM users WHERE user_id=$1",
                uid
            )
            name = (r["first_name"] or r["username"] or str(uid)) if r else str(uid)
            lines.append(f"{medal} <a href='tg://user?id={uid}'>{name}</a> — <b>{amt:.2f} SOL</b>")

        await _tag(first["user_id"],  "🏆", first_prize)
        if second: await _tag(second["user_id"], "🥈", second_prize)
        if third:  await _tag(third["user_id"],  "🥉", third_prize)

        lines.append(f"\n<i>Batch Tx:</i> <code>{batch_sig}</code>\nA new round is OPEN!")
        announcement = "\n".join(lines)

        # 4) Send to main group
        try:
            await bot.send_photo(
                chat_id    = GROUP_CHAT_ID,
                photo      = photo,
                caption    = announcement,
                parse_mode = "HTML",
                reply_markup = group_buy_signal_keyboard()
            )
        except Exception as e:
            print(f"[run_lottery] main GROUP_CHAT_ID error: {e}")

    finally:
        await release_connection(conn)

    # 5) Send to extra groups
    extra_conn = await get_connection()
    try:
        rows = await extra_conn.fetch(
            "SELECT chat_id FROM group_settings WHERE buy_signals_enabled = TRUE"
        )
        for r in rows:
            try:
                await bot.send_photo(
                    chat_id      = r["chat_id"],
                    photo        = photo,
                    caption      = announcement,
                    parse_mode   = "HTML",
                    reply_markup = group_buy_signal_keyboard()
                )
            except Exception as ge:
                print(f"[run_lottery] extra group error ({r['chat_id']}): {ge}")
    finally:
        await release_connection(extra_conn)

    # 6) Re-open a new pool at this level
    new_conn = await get_connection()
    try:
        await new_conn.execute(
            "INSERT INTO pools (level, status) VALUES ($1, 'OPEN')",
            level
        )
    finally:
        await release_connection(new_conn)
