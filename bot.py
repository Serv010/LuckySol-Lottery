import logging
from aiogram import Bot, F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from typing import Optional
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient

# --------------------------
# CONFIG IMPORTS
# --------------------------
from config import (
    BOT_TOKEN,
    BOT_USERNAME,
    GROUP_CHAT_ID,
    POOL_SIZE,
    _LEVEL_PRICES,
    _LEVEL_EMOJIS,
    _LEVEL_NAMES,
    _LEVELS,
    SOLANA_RPC_ENDPOINT
)

# --------------------------
# DATABASE IMPORTS
# --------------------------
from database import (
    create_or_update_user,
    has_seen_disclaimer,
    set_disclaimer_true,
    get_buy_signals_enabled,
    set_buy_signals,
    generate_user_wallet,
    get_connection,
    sync_user_wallet_balance,
    get_user_stats,
    get_user_history,
    get_referral_stats
)

# --------------------------
# LOTTERY & CLAIM LOGIC
# --------------------------
from lottery import buy_ticket
from claim_logic import claim_ticket_logic

# --------------------------
# KEYBOARDS & CONSTANTS
# --------------------------
from keyboards import (
    history_keyboard,
    stats_keyboard,
    disclaimer_keyboard,
    help_keyboard,
    continue_keyboard,
    view_disclaimer_keyboard,
    main_menu_keyboard,
    wallet_menu_keyboard,
    play_menu_keyboard,
    confirm_buy_keyboard_multi,
    confirm_buy_3_keyboard_multi,
    claim_keyboard,
    group_buy_signal_keyboard,
    referrals_keyboard,
    privatekey_keyboard,
    buy_now_keyboard,
    DISCLAIMER_TEXT,
    DISCLAIMER_TEXT2
)
from emoji_constants import EMOJIS

# --------------------------
# LOGGER & BOT SETUP
# --------------------------
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
router = Router()

# --------------------------
# FSM STATES
# --------------------------
class WithdrawState(StatesGroup):
    waiting_for_address = State()
    waiting_for_amount  = State()

# --------------------------
# REFERRAL PARSER
# --------------------------
def _extract_referrer_id(text: str, current_user_id: int) -> Optional[int]:
    if not text or ' ' not in text:
        return None
    payload = text.split(' ', 1)[1]
    if payload.startswith('ref') and payload[3:].isdigit():
        ref_id = int(payload[3:])
        if ref_id != current_user_id:
            return ref_id
    return None

# --------------------------
# REFERRAL MENU
# --------------------------
@router.callback_query(F.data == "menu_referrals")
async def cb_menu_referrals(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    # build personal deep-link
    link = f"https://t.me/{BOT_USERNAME}?start=ref{user_id}"

    # fetch stats
    conn = await get_connection()
    try:
        referral_count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE referred_by = $1", user_id
        )
        earnings = await conn.fetchval(
            "SELECT COALESCE(referral_earnings, 0) FROM users WHERE user_id = $1",
            user_id
        )
    finally:
        await conn.close()

    # compose message
    text = (
        f"🤝 <b>Your Referral Program</b>\n\n"
        f"🔗 Share this link:\n<code>{link}</code>\n\n"
        f"👥 Referrals: <b>{referral_count}</b>\n"
        f"💰 Earned: <b>{earnings:.4f} SOL</b>"
    )

    await cbq.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=referrals_keyboard()
    )

# --------------------------
# START HANDLER
# --------------------------
@router.message(Command("start"))
async def cmd_start(msg: Message):
    if msg.chat.type in ("group", "supergroup"):
        return
    user_id = msg.from_user.id
    username = msg.from_user.username or ""
    first_name = msg.from_user.first_name or ""
    referrer_id = _extract_referrer_id(msg.text, user_id)

    await create_or_update_user(user_id, username, first_name, referred_by=referrer_id)

    if not await has_seen_disclaimer(user_id):
        await msg.answer(
            f"🏆 <b>Welcome to Solana Lottery Bot!</b>\n\n{DISCLAIMER_TEXT}",
            reply_markup=disclaimer_keyboard(),
        )
    else:
        status = await get_status_text(user_id)
        await msg.answer(
            f"{status}\n\n🎉 <b>Welcome back!</b> Please choose an option below:",
            reply_markup=main_menu_keyboard(),
        )

# --------------------------
# DISCLAIMER ACCEPT
# --------------------------
@router.callback_query(F.data == "accept_disclaimer")
async def cb_accept_disclaimer(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    await set_disclaimer_true(user_id)
    wallet_info = await generate_user_wallet(user_id)

    if wallet_info.get("wallet_private_key"):
        text = (
            "✅ <b>Disclaimer Accepted!</b>\n\n"
            "💼 Your wallet has been created:\n"
            f"<code>{wallet_info['wallet_public_key']}</code>\n\n"
            "🔑 <i>(Private key shown once—save it securely!)</i>\n"
            f"<code>{wallet_info['wallet_private_key']}</code>\n\n"
            "➡️ Press <b>Continue</b> to enter the main menu."
        )
    else:
        text = "✅ <b>Disclaimer Accepted!</b>\n\n➡️ Press <b>Continue</b> to enter the main menu."

    await cbq.message.edit_text(text, reply_markup=continue_keyboard())

@router.callback_query(F.data == "continue_main")
async def cb_continue_main(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.edit_text(
        f"{status}\n\n🎉 <b>Main Menu</b>\nSelect an action below:",
        reply_markup=main_menu_keyboard(),
    )

@router.callback_query(F.data == "disclaimer_back_main")
async def cb_disclaimer_back_main(cbq: CallbackQuery):
    try:
        await cbq.message.delete()
    except:
        pass
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.answer(
        f"{status}\n\n🔙 <b>Main Menu</b>",
        reply_markup=main_menu_keyboard(),
    )

# --------------------------
# VIEW DISCLAIMER
# --------------------------
@router.callback_query(F.data == "view_disclaimer")
async def cb_view_disclaimer(cbq: CallbackQuery):
    await cbq.message.edit_text(
        f"📜 <b>Disclaimer & Terms</b>\n\n{DISCLAIMER_TEXT2}",
        reply_markup=disclaimer_keyboard(),
    )

# --------------------------
# HELP/FAQ
# --------------------------
@router.callback_query(F.data == "menu_help")
async def cb_menu_help(cbq: CallbackQuery):
    help_text = (
        "ℹ️ <b>Help & FAQ</b>\n\n"
        "Here’s how to play:\n"
        "1️⃣ Ensure you have SOL in your wallet.\n"
        "2️⃣ Tap <i>Play Lottery</i> → <i>Buy Ticket</i>.\n"
        "3️⃣ Wait for the pool to fill; draw happens automatically.\n"
        "4️⃣ Prizes are paid out as soon as winners are selected.\n\n"
        "Good luck! 🍀"
    )
    await cbq.message.edit_text(help_text, reply_markup=help_keyboard())

"""
@router.callback_query(F.data == "help_back_main")
async def cb_help_back_main(cbq: CallbackQuery):
    try:
        await cbq.message.delete()
    except:
        pass
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.answer(
        f"{status}\n\n🔙 <b>Main Menu</b>",
        reply_markup=main_menu_keyboard(),
    )
"""

# --------------------------
# BACK TO MAIN
# --------------------------
@router.callback_query(F.data == "back_main")
async def cb_back_main(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.edit_text(
        f"{status}\n\n🔙 <b>Main Menu</b>",
        reply_markup=main_menu_keyboard(),
    )

# --------------------------
# WALLET MENU
# --------------------------
@router.callback_query(F.data == "menu_wallet")
async def cb_menu_wallet(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    balance = await sync_user_wallet_balance(user_id)
    status = await get_status_text(user_id)
    await cbq.message.edit_text(
        f"{status}\n\n💼 <b>Wallet</b>\nBalance: <b>{balance:.4f} SOL</b>",
        reply_markup=wallet_menu_keyboard(),
    )

# --------------------------
# PLAY MENU (MULTI-STAKE)
# --------------------------
@router.callback_query(F.data == "menu_play")
async def cb_menu_play(cbq: CallbackQuery, state: FSMContext):
    user_id = cbq.from_user.id
    data    = await state.get_data()
    level   = data.get("last_level", _LEVELS[0])

    # 1) Fetch your up-to-date on-chain balance
    balance = await sync_user_wallet_balance(user_id)

    # 2) Fetch pool info for this level
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT pool_id FROM pools WHERE status='OPEN' AND level=$1 ORDER BY pool_id LIMIT 1",
            level
        )
        if row:
            pool_id    = row["pool_id"]
            count      = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pool_id)
            spots_left = POOL_SIZE - count
            pot        = float(await conn.fetchval(
                "SELECT COALESCE(SUM(value),0) FROM tickets WHERE pool_id=$1", pool_id
            ))
        else:
            pool_id, spots_left, pot = None, 0, 0.0
    finally:
        await conn.close()

    # 3) Remember this level for next time
    await state.update_data(last_level=level)

    emoji = _LEVEL_EMOJIS[level]
    name  = _LEVEL_NAMES[level]

    # 4) Build a concise header
    header = (
        f"🎰 <b>Lottery Menu</b>\n"
        f"💰 <b>Balance:</b> {balance:.4f} SOL\n\n"
        f"🔖 <b>Chosen Tier:</b> {emoji} {name}\n"
        f"┣ 🎟 Spots left: <b>{spots_left}/{POOL_SIZE}</b>\n"
        f"┗ 💰 Pot: <b>{pot:.2f} SOL</b>"
    )

    await cbq.message.edit_text(
        header,
        reply_markup=play_menu_keyboard(level, pool_id, spots_left, pot)
    )


@router.callback_query(F.data.startswith("switch_stake:"))
async def cb_switch_stake(cbq: CallbackQuery, state: FSMContext):
    user_id = cbq.from_user.id
    level   = cbq.data.split(":", 1)[1]

    # Fetch balance again
    balance = await sync_user_wallet_balance(user_id)

    # Fetch pool info for new level
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT pool_id FROM pools WHERE status='OPEN' AND level=$1 ORDER BY pool_id LIMIT 1",
            level
        )
        if row:
            pool_id    = row["pool_id"]
            count      = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pool_id)
            spots_left = POOL_SIZE - count
            pot        = float(await conn.fetchval(
                "SELECT COALESCE(SUM(value),0) FROM tickets WHERE pool_id=$1", pool_id
            ))
        else:
            pool_id, spots_left, pot = None, 0, 0.0
    finally:
        await conn.close()

    # Remember this new level
    await state.update_data(last_level=level)

    emoji = _LEVEL_EMOJIS[level]
    name  = _LEVEL_NAMES[level]

    header = (
        f"🎰 <b>Lottery Menu</b>\n"
        f"💰 <b>Balance:</b> {balance:.4f} SOL\n\n"
        f"🔖 <b>Chosen Tier:</b> {emoji} {name}\n"
        f"┣ 🎟 Spots left: <b>{spots_left}/{POOL_SIZE}</b>\n"
        f"┗ 💰 Pot: <b>{pot:.2f} SOL</b>"
    )

    await cbq.message.edit_text(
        header,
        reply_markup=play_menu_keyboard(level, pool_id, spots_left, pot)
    )

# --------------------------
# INIT BUY: SINGLE TICKET
# --------------------------
@router.callback_query(F.data.startswith("init_buy_ticket:"))
async def cb_init_buy_ticket(cbq: CallbackQuery):
    level = cbq.data.split(":", 1)[1]
    emoji = _LEVEL_EMOJIS[level]
    name  = _LEVEL_NAMES[level]

    user_id = cbq.from_user.id
    balance = await sync_user_wallet_balance(user_id)

    # fetch pool for this level
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT pool_id FROM pools WHERE status='OPEN' AND level=$1 ORDER BY pool_id LIMIT 1",
            level
        )
        if not row:
            return await cbq.message.edit_text(
                "⛔ <b>No open pool at that level.</b>",
                reply_markup=main_menu_keyboard()
            )
        pool_id    = row["pool_id"]
        filled     = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pool_id)
        spots_left = POOL_SIZE - filled
        pot        = float(await conn.fetchval(
            "SELECT COALESCE(SUM(value),0) FROM tickets WHERE pool_id=$1", pool_id
        ))
    finally:
        await conn.close()

    text = (
        f"🎰 <b>Lottery Menu</b>\n"
        f"💰 <b>Balance:</b> {balance:.4f} SOL\n\n"

        f"🔖 <b>Chosen Tier:</b> {emoji} {name}\n"
        f"🎟 <b>Buy 1× Ticket</b>\n"
        f"┣ 🎟 Spots left: <b>{spots_left}/{POOL_SIZE}</b>\n"
        f"┗ 💰 Pot: <b>{pot:.2f} SOL</b>"
    )

    await cbq.message.edit_text(text, reply_markup=confirm_buy_keyboard_multi(level))

# --------------------------
# INIT BUY: THREE TICKETS
# --------------------------
@router.callback_query(F.data.startswith("init_buy_3_tickets:"))
async def cb_init_buy_3_tickets(cbq: CallbackQuery):
    level = cbq.data.split(":", 1)[1]
    emoji = _LEVEL_EMOJIS[level]
    name  = _LEVEL_NAMES[level]

    user_id = cbq.from_user.id
    balance = await sync_user_wallet_balance(user_id)

    # fetch pool for this level
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT pool_id FROM pools WHERE status='OPEN' AND level=$1 ORDER BY pool_id LIMIT 1",
            level
        )
        if not row:
            return await cbq.message.edit_text(
                "⛔ <b>No open pool at that level.</b>",
                reply_markup=main_menu_keyboard()
            )
        pool_id    = row["pool_id"]
        filled     = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pool_id)
        spots_left = POOL_SIZE - filled
        pot        = float(await conn.fetchval(
            "SELECT COALESCE(SUM(value),0) FROM tickets WHERE pool_id=$1", pool_id
        ))
    finally:
        await conn.close()

    text = (
        f"🎰 <b>Lottery Menu</b>\n"
        f"💰 <b>Balance:</b> {balance:.4f} SOL\n\n"

        f"🔖 <b>Chosen Tier:</b> {emoji} {name}\n"
        f"🎟 <b>Buy 3× Ticket</b>\n"
        f"┣ 🎟 Spots left: <b>{spots_left}/{POOL_SIZE}</b>\n"
        f"┗ 💰 Pot: <b>{pot:.2f} SOL</b>"
    )
    await cbq.message.edit_text(text, reply_markup=confirm_buy_3_keyboard_multi(level))

# --------------------------
# CONFIRM BUY: SINGLE
# --------------------------
@router.callback_query(F.data.startswith("confirm_buy:"))
async def cb_confirm_buy(cbq: CallbackQuery):
    _, level, choice = cbq.data.split(":")
    if choice == "no":
        return await cbq.message.edit_text(
            "🚫 <b>Purchase cancelled.</b>",
            reply_markup=main_menu_keyboard()
        )

    user_id = cbq.from_user.id
    price   = _LEVEL_PRICES[level]
    result  = await buy_ticket(user_id, price, level, cbq, bot, num_tickets=1)
    balance = await sync_user_wallet_balance(user_id)

    if not result.get("success"):
        return await cbq.message.edit_text(f"❌ {result['message']}", reply_markup=main_menu_keyboard())

    emoji      = _LEVEL_EMOJIS[level]
    name       = _LEVEL_NAMES[level]
    pool_id    = result["pool_id"]
    spots_left = result["spots_left"]
    pot        = result["pot"]

    text = (
        f"✅ <b>Ticket purchased!</b>\n"
        f"🏷 {emoji} {name} — Pool #{pool_id}\n"
        f"┏ 🎟 Spots left: <b>{spots_left}/{POOL_SIZE}</b>\n"
        f"┗ 💰 Pot: <b>{pot:.2f} SOL</b>"
    )
    await cbq.message.edit_text(text, reply_markup=main_menu_keyboard())

    # 2) Broadcast to all groups with signals enabled
    if spots_left > 0:
        announcement = (
            f"🎟 <b>{cbq.from_user.first_name or 'A player'}</b> just bought a ticket in pool "
            f"<b>{emoji} {name}</b> (#{pool_id})!\n"
            f"Spots left: <b>{spots_left}/{POOL_SIZE}</b> | Current pot: <b>{pot:.2f} SOL</b>"
        )

        grp_conn = await get_connection()
        try:
            rows = await grp_conn.fetch("SELECT chat_id FROM group_settings WHERE buy_signals_enabled = TRUE")
            for r in rows:
                try:
                    await bot.send_message(r["chat_id"], announcement, reply_markup=group_buy_signal_keyboard())
                except:
                    pass
        finally:
            await grp_conn.close()

# --------------------------
# CONFIRM BUY: THREE
# --------------------------
@router.callback_query(F.data.startswith("confirm_buy_3:"))
async def cb_confirm_buy_3(cbq: CallbackQuery):
    _, level, choice = cbq.data.split(":")
    if choice == "no":
        return await cbq.message.edit_text(
            "🚫 <b>Purchase cancelled.</b>",
            reply_markup=main_menu_keyboard()
        )

    user_id         = cbq.from_user.id
    price           = _LEVEL_PRICES[level]
    result          = await buy_ticket(user_id, price, level, cbq, bot, num_tickets=3)
    balance         = await sync_user_wallet_balance(user_id)

    if not result.get("success"):
        return await cbq.message.edit_text(f"❌ {result['message']}", reply_markup=main_menu_keyboard())

    emoji           = _LEVEL_EMOJIS[level]
    name            = _LEVEL_NAMES[level]
    pool_id         = result["pool_id"]
    spots_left      = result["spots_left"]
    pot             = result["pot"]
    tickets_bought  = result.get("tickets_bought", 3)

    text = (
        f"✅ <b>{tickets_bought} tickets purchased!</b>\n\n"
        f"🏷 {emoji} {name} — Pool #{pool_id}\n"
        f"┏ 🎟 Spots left: <b>{spots_left}/{POOL_SIZE}</b>\n"
        f"┗ 💰 Pot: <b>{pot:.2f} SOL</b>"
    )
    await cbq.message.edit_text(text, reply_markup=main_menu_keyboard())

    # 2) Broadcast to all groups with signals enabled
    if spots_left > 0:
        announcement = (
            f"🎟 <b>{cbq.from_user.first_name or 'A player'}</b> just bought <b>3 tickets</b> in pool "
            f"<b>{emoji} {name}</b> (#{pool_id})!\n"
            f"Spots left: <b>{spots_left}/{POOL_SIZE}</b> | Current pot: <b>{pot:.2f} SOL</b>"
        )

        grp_conn = await get_connection()
        try:
            rows = await grp_conn.fetch("SELECT chat_id FROM group_settings WHERE buy_signals_enabled = TRUE")
            for r in rows:
                try:
                    await bot.send_message(r["chat_id"], announcement, reply_markup=group_buy_signal_keyboard())
                except:
                    pass
        finally:
            await grp_conn.close()

# --------------------------
# CLAIM PRIZE
# --------------------------
@router.callback_query(F.data.startswith("claim:"))
async def cb_claim_ticket(cbq: CallbackQuery):
    parts = cbq.data.split(":")
    if len(parts) != 2:
        return await cbq.message.edit_text("⛔ <b>Invalid claim format.</b>")
    ticket_id = int(parts[1])
    text = await claim_ticket_logic(cbq.from_user.id, ticket_id)
    await cbq.message.edit_text(f"🏅 {text}", reply_markup=main_menu_keyboard())

# --------------------------
# GROUP SIGNALS TOGGLE
# --------------------------
@router.message(Command("enable_signals"))
async def cmd_enable_signals(msg: Message):
    if msg.chat.type not in ("group", "supergroup"):
        return await msg.answer("⛔ This command only works in groups.")
    member = await bot.get_chat_member(msg.chat.id, msg.from_user.id)
    if member.status not in ("administrator", "creator"):
        return await msg.answer("⛔ Only group admins can do that.")
    await set_buy_signals(msg.chat.id, True)
    await msg.answer("✅ <b>Buy signals ENABLED</b> for this group.")

@router.message(Command("disable_signals"))
async def cmd_disable_signals(msg: Message):
    if msg.chat.type not in ("group", "supergroup"):
        return await msg.answer("⛔ This command only works in groups.")
    member = await bot.get_chat_member(msg.chat.id, msg.from_user.id)
    if member.status not in ("administrator", "creator"):
        return await msg.answer("⛔ Only group admins can do that.")
    await set_buy_signals(msg.chat.id, False)
    await msg.answer("✅ <b>Buy signals DISABLED</b> for this group.")

# --------------------------
# STATUS TEXT HELPER
# --------------------------
async def get_status_text(user_id: int) -> str:
    onchain_balance = await sync_user_wallet_balance(user_id)
    conn = await get_connection()
    try:
        wallet_pub = await conn.fetchval(
            "SELECT wallet_public_key FROM users WHERE user_id = $1",
            user_id
        ) or "No wallet"
        lines = [
            f"💼 <b>Wallet</b>: <code>{wallet_pub}</code>",
            f"💰 <b>Balance</b>: {onchain_balance:.4f} SOL",
            "",
            "🎰 <b>Current Pools</b>:"
        ]
        for level in _LEVELS:
            pool_row = await conn.fetchrow(
                "SELECT pool_id FROM pools WHERE status='OPEN' AND level = $1 ORDER BY pool_id LIMIT 1",
                level
            )
            if pool_row:
                pid = pool_row["pool_id"]
                count = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE pool_id=$1", pid)
                pot = await conn.fetchval("SELECT COALESCE(SUM(value),0) FROM tickets WHERE pool_id=$1", pid)
                lines.append(
                    f"{_LEVEL_EMOJIS[level]} <b>{_LEVEL_NAMES[level]}</b> — {count}/{POOL_SIZE} tickets, pot {pot:.2f} SOL"
                )
            else:
                lines.append(f"{_LEVEL_EMOJIS[level]} <b>{_LEVEL_NAMES[level]}</b> — No open pool")
        return "\n".join(lines)
    finally:
        await conn.close()

# --------------------------
# WITHDRAW FLOW
# --------------------------
# Cancel command to abort withdrawal at any step
@router.message(Command("cancel"), StateFilter(WithdrawState))
async def cancel_withdraw(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "🚫 <b>Withdrawal cancelled.</b>",
        reply_markup=main_menu_keyboard()
    )

# Prompt for recipient address
@router.callback_query(F.data == "wallet_withdraw_prompt")
async def cb_withdraw_prompt(cbq: CallbackQuery, state: FSMContext):
    await cbq.message.edit_text("🚚 <b>Enter external Solana address:</b>\n(or /cancel to abort)")
    await state.set_state(WithdrawState.waiting_for_address)

# Withdraw all funds in one step
@router.callback_query(F.data == "wallet_withdraw_all")
async def cb_withdraw_all(cbq: CallbackQuery, state: FSMContext):
    await state.update_data(requested_amount="all")
    await cbq.message.edit_text("🚚 <b>Enter address to withdraw <u>all</u> funds:</b>\n(or /cancel to abort)")
    await state.set_state(WithdrawState.waiting_for_address)

# Receive and validate address, then ask for amount if needed
@router.message(StateFilter(WithdrawState.waiting_for_address))
async def process_withdraw_address(msg: Message, state: FSMContext):
    addr = msg.text.strip()

    # Basic structural check
    if len(addr) < 32 or len(addr) > 44:
        return await msg.answer("⛔ <b>Invalid address length.</b> Enter a valid Solana address or /cancel.")

    # Prevent withdrawing to self
    data = await state.get_data()
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT wallet_public_key FROM users WHERE user_id=$1",
            msg.from_user.id
        )
    finally:
        await conn.close()

    user_pub = row["wallet_public_key"] if row else None
    if addr == user_pub:
        return await msg.answer("⛔ <b>Cannot withdraw to your own wallet address.</b> Enter a different address or /cancel.")

    # ✅ Skip recipient existence check — just validate it's a structurally valid pubkey
    try:
        _ = Pubkey.from_string(addr)
    except Exception:
        return await msg.answer("⛔ <b>Invalid address format.</b> Enter a valid Solana address or /cancel.")

    # Store address
    await state.update_data(recipient_address=addr)

    # Auto finalize if amount already known
    if data.get("requested_amount") == "all":
        return await finalize_withdraw(msg, state)

    # Prompt for withdrawal amount
    await msg.answer(
        "✅ <b>Address OK!</b>\nNow send amount in SOL to withdraw, or type 'all', or /cancel."
    )
    await state.set_state(WithdrawState.waiting_for_amount)

# Receive amount input
@router.message(StateFilter(WithdrawState.waiting_for_amount))
async def process_withdraw_amount(msg: Message, state: FSMContext):
    user_input = msg.text.strip().lower()
    if user_input != "all":
        try:
            float(user_input)
        except ValueError:
            return await msg.answer("⛔ <b>Invalid amount format.</b> Enter a number or 'all', or /cancel.")
    await state.update_data(requested_amount=user_input)
    await finalize_withdraw(msg, state)

# Finalize withdrawal with safety checks
async def finalize_withdraw(msg: Message, state: FSMContext):
    data = await state.get_data()
    recipient = data["recipient_address"]
    req = data["requested_amount"]
    # Fetch user wallet keys
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT wallet_public_key, wallet_private_key FROM users WHERE user_id=$1",
            msg.from_user.id
        )
    finally:
        await conn.close()

    if not row or not row["wallet_public_key"]:
        await msg.answer(
            "⚠️ <b>No wallet found. Use /start.</b>",
            reply_markup=main_menu_keyboard()
        )
        return await state.clear()

    user_pubkey = row["wallet_public_key"]
    priv_key = row["wallet_private_key"]
    # Get on-chain balance
    from solana_utils import get_wallet_balance, pay_sol
    balance = await get_wallet_balance(user_pubkey)

    # Determine withdrawal amount
    if req == "all":
        amount = max(balance - 0.001, 0)
    else:
        amount = float(req)
    # Prevent overdraw
    if amount > balance:
        return await msg.answer(f"⛔ <b>Insufficient funds:</b> {balance:.4f} SOL")

    # Execute transfer
    try:
        sig = await pay_sol(priv_key, user_pubkey, recipient, amount)
        await msg.answer(
            f"🚀 <b>Withdrawn {amount:.4f} SOL</b>\nTx: https://solscan.io/tx/{sig}",
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        await msg.answer(f"❌ <b>Withdrawal failed:</b> {e}")
    finally:
        await state.clear()

# --------------------------
# MENU: Stats
# --------------------------
@router.callback_query(F.data == "menu_stats")
async def cb_menu_stats(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    conn = await get_connection()
    try:
        total = await conn.fetchrow("""
            SELECT COUNT(*) AS total_tickets,
                   COALESCE(SUM(value),0) AS total_spent,
                   COALESCE(SUM(prize_amount),0) AS total_won,
                   SUM(CASE WHEN is_winner THEN 1 ELSE 0 END) AS total_wins
            FROM tickets WHERE user_id=$1
        """, user_id)
        per_level = await conn.fetch("""
            SELECT level,
                   COUNT(*) AS tickets,
                   COALESCE(SUM(value),0) AS spent,
                   COALESCE(SUM(prize_amount),0) AS won,
                   SUM(CASE WHEN is_winner THEN 1 ELSE 0 END) AS wins
            FROM tickets WHERE user_id=$1
            GROUP BY level
        """, user_id)
    finally:
        await conn.close()

    lines = [
        "📊 <b>Your Stats</b>",
        "────────────────────",
        f"🎟 Tickets Bought: <b>{total['total_tickets']}</b>",
        f"💸 Total Spent: <b>{total['total_spent']:.2f} SOL</b>",
        f"💰 Total Won: <b>{total['total_won']:.2f} SOL</b>",
        f"🏆 Wins: <b>{total['total_wins']}</b>",
        "",
        "🔢 <b>By Tier</b>",
        "────────────────────",
    ]
    for i, lvl in enumerate(_LEVELS):
        row = next((r for r in per_level if r["level"] == lvl), None)
        emoji = _LEVEL_EMOJIS[lvl]
        name = _LEVEL_NAMES[lvl]
        prefix = "└" if i == len(_LEVELS) - 1 else "├"
        if row:
            tickets = row["tickets"]
            spent = row["spent"]
            won = row["won"]
            wins = row["wins"]
            rate = (wins / tickets * 100) if tickets else 0.0
            content = f"{tickets} bought, spent {spent:.2f}, won {won:.2f}, {wins} wins ({rate:.1f}%)"
        else:
            content = "No activity"
        lines.append(f"{prefix} {emoji} <b>{name}</b> — {content}")

    await cbq.message.edit_text("\n".join(lines), reply_markup=stats_keyboard())

@router.callback_query(F.data == "stats_back_main")
async def cb_stats_back_main(cbq: CallbackQuery):
    try:
        await cbq.message.delete()
    except:
        pass
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.answer(
        f"{status}\n\n🔙 <b>Main Menu</b>",
        reply_markup=main_menu_keyboard(),
    )

# --------------------------
# MENU: History
# --------------------------
@router.callback_query(F.data == "menu_history")
async def cb_menu_history(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    conn = await get_connection()
    try:
        rows = await conn.fetch("""
            SELECT pool_id, level, is_winner, prize_amount, created_at
            FROM tickets WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10
        """, user_id)
    finally:
        await conn.close()

    if not rows:
        return await cbq.message.edit_text(
            "📜 <b>No history yet!</b>\nPlay to see your past tickets.",
            reply_markup=history_keyboard()
        )

    lines = ["📜 <b>Recent History</b>", "────────────────────"]
    for t in rows:
        lvl = t["level"]
        name = _LEVEL_NAMES.get(lvl, lvl.title())
        emoji = _LEVEL_EMOJIS.get(lvl, "")
        outcome = "✅ <b>WIN</b>" if t["is_winner"] else "❌ <b>Lost</b>"
        prize = f"{t['prize_amount']:.2f} SOL" if t["is_winner"] else "-"
        ts = t["created_at"].strftime("%Y-%m-%d %H:%M")
        lines.append(f"{emoji} <b>{name}</b> | Pool #{t['pool_id']} | {outcome} | Prize: {prize}\n<i>{ts}</i>")

    await cbq.message.edit_text("\n".join(lines), reply_markup=history_keyboard())

"""
@router.callback_query(F.data == "history_back_main")
async def cb_history_back_main(cbq: CallbackQuery):
    try:
        await cbq.message.delete()
    except:
        pass
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.answer(
        f"{status}\n\n🔙 <b>Main Menu</b>",
        reply_markup=main_menu_keyboard(),
    )
"""

# --------------------------
# SHOW PRIVATE KEY (SAFETY)
# --------------------------
@router.callback_query(F.data == "wallet_show_private_key")
async def cb_show_private_key(cbq: CallbackQuery):
    if cbq.message.chat.type != "private":
        return await cbq.answer("🔒 Private keys are shown only in private chat.", show_alert=True)

    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT wallet_public_key, wallet_private_key FROM users WHERE user_id=$1",
            cbq.from_user.id
        )
    finally:
        await conn.close()

    if not row or not row["wallet_public_key"]:
        return await cbq.message.edit_text(
            "⚠️ <b>No wallet found.</b> Use /start to create one.",
            reply_markup=main_menu_keyboard()
        )

    await cbq.message.answer(
        "🔑 <b>Your Wallet Credentials</b>\n\n"
        f"📮 Address:\n<code>{row['wallet_public_key']}</code>\n\n"
        f"🗝️ Private Key (keep it secret!):\n<code>{row['wallet_private_key']}</code>",
        reply_markup=privatekey_keyboard()
    )

@router.message(Command("buy"))
async def cmd_buy(msg: Message):
    # Only in groups/supergroups
    if msg.chat.type in ("group", "supergroup"):
        await msg.answer(
            "🎟️ Want to join the lottery? Tap below to buy your ticket now!",
            reply_markup=buy_now_keyboard()
        )
    else:
        # In private chat, just show your normal play menu
        await msg.answer(
            "🎰 Ready to play?",
            reply_markup=main_menu_keyboard()
        )

@router.message(Command("reset"))
async def cmd_reset(msg: Message):
    # only allow you (or any admin you choose) to do this
    if msg.from_user.id != 6428898245:
        return await msg.reply("⛔ You’re not authorized to do that.")
    conn = await get_connection()
    try:
        # wipe out everything
        await conn.execute("DELETE FROM tickets")
        await conn.execute("DELETE FROM pools")
        # re-open one pool per level
        for lvl in _LEVELS:
            await conn.execute(
                "INSERT INTO pools (level, status) VALUES ($1, 'OPEN')",
                lvl
            )
    finally:
        await conn.close()
    await msg.reply("✅ All pools and tickets reset. New OPEN pools ready!")

# --------------------------
# REGISTER ROUTER
# --------------------------
# In your main setup, register:
#   dp.include_router(router)
dp = None  # Set this to your Dispatcher instance after import
