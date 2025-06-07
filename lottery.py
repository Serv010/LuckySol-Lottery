import random
import asyncio
import time
from collections import defaultdict

from aiogram import Bot
from aiogram.types import CallbackQuery, FSInputFile

from database import get_connection
from config import (
    DEV_WALLET,
    HOUSE_WALLET,
    POOL_PUBLIC_KEY,
    POOL_PRIVATE_KEY,
    GROUP_CHAT_ID,
    POOL_SIZE,
    _LEVEL_EMOJIS,
    _LEVEL_NAMES,    # ← add this
)
from solana_utils import get_wallet_balance, pay_sol, batch_pay_sol, get_fee_per_signature
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
    Clean version — no is_confirmed. Includes cooldown + full atomic insert + transfer.
    """
    key = f"{user_id}_{level}"
    now = time.time()
    if now - last_buy_time[key] < BUY_COOLDOWN:
        return {
            "success": False,
            "message": f"⏱️ Please wait {BUY_COOLDOWN}s before buying again."
        }
    last_buy_time[key] = now

    conn = await get_connection()
    try:
        async with conn.transaction():
            # 1) Lock pool for this level
            row = await conn.fetchrow(
                "SELECT pool_id FROM pools WHERE status='OPEN' AND level=$1 "
                "ORDER BY pool_id LIMIT 1 FOR UPDATE SKIP LOCKED",
                level
            )
            if not row:
                return {"success": False, "message": "⛔ No open pool at this level!"}
            pool_id = row["pool_id"]

            # 2) Check available spots
            count = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pool_id)
            remaining = POOL_SIZE - count
            if remaining < num_tickets:
                return {"success": False, "message": f"⛔ Only {remaining} spot(s) left."}

            # 3) Fetch wallet keys
            wallet = await conn.fetchrow(
                "SELECT wallet_public_key, wallet_private_key FROM users WHERE user_id=$1", user_id
            )
            if not wallet or not wallet["wallet_public_key"]:
                return {"success": False, "message": "⚠️ Wallet not found. Use /start first."}
            pub, priv = wallet["wallet_public_key"], wallet["wallet_private_key"]

            # 4) Check on-chain balance
            onchain = await get_wallet_balance(pub)
            total_cost = ticket_price * num_tickets
            if onchain < total_cost:
                return {
                    "success": False,
                    "message": f"💸 Insufficient funds: {onchain:.4f} vs {total_cost:.4f}"
                }

            # 5) Transfer funds
            try:
                tx_sig = await pay_sol(priv, pub, POOL_PUBLIC_KEY, total_cost)
            except Exception as e:
                return {"success": False, "message": f"❌ Transfer failed: {e}"}

            # 6) Insert ticket(s)
            for _ in range(num_tickets):
                await conn.execute(
                    "INSERT INTO tickets (pool_id, user_id, level, value) VALUES ($1,$2,$3,$4)",
                    pool_id, user_id, level, ticket_price
                )

        # 7) Post-insert stats
        final_count = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pool_id)
        pot = await conn.fetchval("SELECT COALESCE(SUM(value), 0) FROM tickets WHERE pool_id=$1", pool_id)

        # 8) If pool is full, trigger draw
        if final_count == POOL_SIZE:
            from lottery import run_lottery
            await run_lottery(bot, pool_id)

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
        await conn.close()

async def run_lottery(bot: Bot, pool_id: int):
    """
    Draws 1st/2nd/3rd, batch-pays prizes/fees/referrals, notifies players & groups,
    and opens a new pool at the same level.
    """
    conn = await get_connection()
    # placeholders so we can reference them after the transaction
    first_ticket = second_ticket = third_ticket = None
    first_prize = second_prize = third_prize = None
    batch_sig = None
    level = None

    try:
        # ─── Transaction B: select winners, build payouts, close pool ───
        async with conn.transaction():
            # a) Lock & verify pool
            row = await conn.fetchrow(
                "SELECT status, level FROM pools WHERE pool_id=$1 FOR UPDATE",
                pool_id
            )
            if not row or row["status"] != "OPEN":
                return
            level = row["level"]

            # b) Load only confirmed tickets
            tickets = await conn.fetch(
                """
                SELECT ticket_id, user_id, value
                FROM tickets
                WHERE pool_id = $1 AND is_confirmed = TRUE
                """,
                pool_id
            )

            if len(tickets) < POOL_SIZE:
                return  # somehow not full

            pot = sum(t["value"] for t in tickets)

            # c) Pick winners
            first_ticket = random.choice(tickets)
            rest1 = [t for t in tickets if t["ticket_id"] != first_ticket["ticket_id"]]
            second_ticket = random.choice(rest1) if rest1 else None
            rest2 = [
                t for t in tickets
                if t["ticket_id"] not in {
                    first_ticket["ticket_id"],
                    (second_ticket["ticket_id"] if second_ticket else None)
                }
            ]
            third_ticket = random.choice(rest2) if rest2 else None

            # d) Compute prize & fee splits
            first_prize  = pot * 0.60
            second_prize = pot * 0.20
            third_prize  = pot * 0.10
            house_fee    = pot * 0.08
            dev_fee      = pot * 0.02

            # e) Mark winners (auto-claimed)
            await conn.execute(
                "UPDATE tickets SET is_winner=TRUE, prize_amount=$1, is_claimed=TRUE WHERE ticket_id=$2",
                first_prize, first_ticket["ticket_id"]
            )
            if second_ticket:
                await conn.execute(
                    "UPDATE tickets SET is_winner=TRUE, prize_amount=$1, is_claimed=TRUE WHERE ticket_id=$2",
                    second_prize, second_ticket["ticket_id"]
                )
            if third_ticket:
                await conn.execute(
                    "UPDATE tickets SET is_winner=TRUE, prize_amount=$1, is_claimed=TRUE WHERE ticket_id=$2",
                    third_prize, third_ticket["ticket_id"]
                )

            # f) Build batch transfers list
            transfers = []

            # winners
            p1 = await conn.fetchval(
                "SELECT wallet_public_key FROM users WHERE user_id=$1",
                first_ticket["user_id"]
            )
            if p1 and first_prize > 0:
                transfers.append({"recipient": p1, "amount_sol": first_prize})

            if second_ticket:
                p2 = await conn.fetchval(
                    "SELECT wallet_public_key FROM users WHERE user_id=$1",
                    second_ticket["user_id"]
                )
                if p2 and second_prize > 0:
                    transfers.append({"recipient": p2, "amount_sol": second_prize})

            if third_ticket:
                p3 = await conn.fetchval(
                    "SELECT wallet_public_key FROM users WHERE user_id=$1",
                    third_ticket["user_id"]
                )
                if p3 and third_prize > 0:
                    transfers.append({"recipient": p3, "amount_sol": third_prize})

            # house & dev fees
            if house_fee > 0:
                transfers.append({"recipient": HOUSE_WALLET, "amount_sol": house_fee})
            if dev_fee > 0:
                transfers.append({"recipient": DEV_WALLET,   "amount_sol": dev_fee})

            # referral bonuses (3%)
            REF_PCT = 0.03
            bonus_rows = await conn.fetch(
                """
                SELECT u.referred_by, t.value
                  FROM tickets t
                  JOIN users u ON t.user_id = u.user_id
                 WHERE t.pool_id=$1
                   AND u.referred_by IS NOT NULL
                """,
                pool_id
            )
            bonuses = defaultdict(float)
            for br in bonus_rows:
                bonuses[br["referred_by"]] += br["value"] * REF_PCT
            for ref_id, amt in bonuses.items():
                pub_ref = await conn.fetchval(
                    "SELECT wallet_public_key FROM users WHERE user_id=$1",
                    ref_id
                )
                if pub_ref and amt > 0:
                    transfers.append({"recipient": pub_ref, "amount_sol": amt})
                    await conn.execute(
                        "UPDATE users SET referral_earnings = referral_earnings + $1 WHERE user_id=$2",
                        amt, ref_id
                    )

            # g) Execute the batch on-chain transaction
            batch_sig = await batch_pay_sol(POOL_PRIVATE_KEY, POOL_PUBLIC_KEY, transfers)

            # h) Mark pool CLOSED
            await conn.execute(
                """
                UPDATE pools
                   SET status='CLOSED',
                       completed_at=NOW(),
                       total_pot=$1,
                       first_winner_user_id=$2,
                       second_winner_user_id=$3,
                       third_winner_user_id=$4,
                       house_fee_tx=$5,
                       dev_fee_tx=$6
                 WHERE pool_id=$7
                """,
                pot,
                first_ticket["user_id"],
                (second_ticket    ["user_id"] if second_ticket else None),
                (third_ticket     ["user_id"] if third_ticket  else None),
                f"batch:{batch_sig}",
                f"batch:{batch_sig}",
                pool_id
            )
        # ─── End Transaction B ───

        # 1) Notify winners privately
        photo = FSInputFile("WinnerLucky.jpg")
        for ticket, medal, prize in [
            (first_ticket,  "🏆", first_prize),
            *([(second_ticket, "🥈", second_prize)] if second_ticket else []),
            *([(third_ticket,  "🥉", third_prize)]  if third_ticket  else [])
        ]:
            await bot.send_photo(
                chat_id=ticket["user_id"],
                photo=photo,
                caption=(
                    f"{medal} <b>CONGRATULATIONS!</b>\n"
                    f"You got {medal} Place in Pool <b>#{pool_id}</b>\n"
                    f"Prize: <b>{prize:.2f} SOL</b>\n\n"
                    f"Batch Tx: <code>{batch_sig}</code>"
                ),
                parse_mode="HTML",
                reply_markup=play_again_keyboard()
            )

        # 2) Notify losers with the correct level‐menu
        all_ids  = {t["user_id"] for t in tickets}
        win_ids  = {
            first_ticket["user_id"],
            *( {second_ticket["user_id"]} if second_ticket else set() ),
            *( {third_ticket ["user_id"]} if third_ticket  else set() )
        }
        for loser in all_ids - win_ids:
            await bot.send_message(
                loser,
                "😢 <b>No luck this time—try again next round!</b>",
                parse_mode="HTML",
                reply_markup=play_menu_keyboard(level)
            )

        # 3) Build stake‐aware group announcement
        stake_emoji = _LEVEL_EMOJIS[level]
        stake_name  = _LEVEL_NAMES[level]
        lines = [f"🎉 <b>Pool #{pool_id} — {stake_emoji} {stake_name}</b> concluded!"]

        async def _tag(uid, medal, amt):
            r = await conn.fetchrow(
                "SELECT first_name, username FROM users WHERE user_id=$1", uid
            )
            name = (r["first_name"] or r["username"] or str(uid)) if r else str(uid)
            lines.append(f"{medal} <a href='tg://user?id={uid}'>{name}</a> — <b>{amt:.2f} SOL</b>")

        await _tag(first_ticket["user_id"],  "🏆", first_prize)
        if second_ticket: await _tag(second_ticket["user_id"], "🥈", second_prize)
        if third_ticket:  await _tag(third_ticket["user_id"],  "🥉", third_prize)

        lines.append(f"\n<i>Batch Tx:</i> <code>{batch_sig}</code>\nA new round is OPEN!")
        announcement = "\n".join(lines)

        # 4) Send to your main GROUP_CHAT_ID
        try:
            await bot.send_photo(
                chat_id=GROUP_CHAT_ID,
                photo=photo,
                caption=announcement,
                parse_mode="HTML",
                reply_markup=group_buy_signal_keyboard()
            )
        except Exception as e:
            print(f"[run_lottery] main GROUP_CHAT_ID error: {e}")

    finally:
        await conn.close()

    # 5) Send to any extra groups with signals on
    extra_conn = await get_connection()
    try:
        rows = await extra_conn.fetch(
            "SELECT chat_id FROM group_settings WHERE buy_signals_enabled = TRUE"
        )
        for r in rows:
            try:
                await bot.send_photo(
                    chat_id=r["chat_id"],
                    photo=photo,
                    caption=announcement,
                    parse_mode="HTML",
                    reply_markup=group_buy_signal_keyboard()
                )
            except Exception as ge:
                print(f"[run_lottery] extra group error ({r['chat_id']}): {ge}")
    finally:
        await extra_conn.close()

    # 6) Re-open a new pool at this same level
    new_conn = await get_connection()
    try:
        async with new_conn.transaction():
            await new_conn.execute(
                "INSERT INTO pools (level, status) VALUES ($1,'OPEN')",
                level
            )
    finally:
        await new_conn.close()