import logging
from aiogram import Bot, F, Router
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from typing import Optional
from solders.pubkey import Pubkey

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
# DATABASE IMPORTS (pooling)
# --------------------------
from global_pool import get_connection, release_connection
from database import (
    create_or_update_user,
    has_seen_disclaimer,
    set_disclaimer_true,
    get_buy_signals_enabled,
    set_buy_signals,
    generate_user_wallet,
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


from PIL import Image, ImageDraw, ImageFont
import os
import time

def _make_ticket_image(username: str, amount: float) -> str:
    """
    Opens LuckyTicket_username.png, finds the blanco slot,
    draws a white box with black outline around the username,
    and saves out a new image.
    """
    base = Image.open("LuckyTicket_monogram.png").convert("RGBA")
    w, h = base.size
    draw = ImageDraw.Draw(base)

    # 1) Detect the white-box region (bottom-right)
    qr_x, qr_y = int(w * 0.6), int(h * 0.6)
    pix = base.load()
    whites = [(x,y) for y in range(qr_y,h) for x in range(qr_x,w)
              if pix[x,y][:3] == (255,255,255)]
    if whites:
        xs, ys = zip(*whites)
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
    else:
        minx, maxx = int(w*0.7), w-10
        miny, maxy = int(h*0.8), h-10

    # 2) Prepare text
    text = username
    font_size = max(24, int(h * 0.05))
    font = ImageFont.truetype("arialbd.ttf", size=font_size)
    bbox = draw.textbbox((0,0), text, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]

    # 3) Compute box dimensions
    pad_x = 10
    pad_y = 5
    box_w = max(tw + 2*pad_x, 120)           # enforce minimum 120px
    box_h = th + 2*pad_y
    region_w = maxx - minx + 1

    # 4) Center the box inside the white slot
    box_x1 = minx + (region_w - box_w)//2
    box_y2 = maxy
    box_x2 = box_x1 + box_w
    box_y1 = box_y2 - box_h

    # 5) Draw the white-filled box with 1px black outline
    draw.rectangle(
        [(box_x1, box_y1), (box_x2, box_y2)],
        fill=(255,255,255,255),
        outline=(0,0,0,255),
        width=1
    )

    # 6) Draw the text centered in that box
    text_x = box_x1 + (box_w - tw)//2
    text_y = box_y1 + pad_y - 3
    draw.text((text_x, text_y), text, font=font, fill=(0,0,0,255))

    # 7) Save and return
    fname = f"ticket_{username}_{int(time.time())}.png"
    base.save(fname)
    return fname


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
    link = f"https://t.me/{BOT_USERNAME}?start=ref{user_id}"

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
        await release_connection(conn)

    text = (
        f"🤝 <b>Your Referral Program</b>\n\n"
        f"🔗 Share this link:\n<code>{link}</code>\n\n"
        f"👥 Referrals: <b>{referral_count}</b>\n"
        f"💰 Earned: <b>{earnings:.4f} SOL</b>"
    )
    await cbq.message.edit_text(text, parse_mode="HTML", reply_markup=referrals_keyboard())

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
    ref_id = _extract_referrer_id(msg.text, user_id)

    await create_or_update_user(user_id, username, first_name, referred_by=ref_id)

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

# --------------------------
# CONTINUE MAIN MENU
# --------------------------
@router.callback_query(F.data == "continue_main")
async def cb_continue_main(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.edit_text(
        f"{status}\n\n🎉 <b>Main Menu</b>\nSelect an action below:",
        reply_markup=main_menu_keyboard(),
    )

# --------------------------
# DISCLAIMER BACK TO MAIN
# --------------------------
@router.callback_query(F.data == "disclaimer_back_main")
async def cb_disclaimer_back_main(cbq: CallbackQuery):
    try:
        await cbq.message.delete()
    except:
        pass
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.answer(f"{status}\n\n🔙 <b>Main Menu</b>", reply_markup=main_menu_keyboard())

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

# --------------------------
# BACK TO MAIN
# --------------------------
@router.callback_query(F.data == "back_main")
async def cb_back_main(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    status = await get_status_text(user_id)
    await cbq.message.edit_text(f"{status}\n\n🔙 <b>Main Menu</b>", reply_markup=main_menu_keyboard())

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

    # 1) Fetch on-chain balance
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
        await release_connection(conn)

    # 3) Remember this level for next time
    await state.update_data(last_level=level)

    emoji = _LEVEL_EMOJIS[level]
    name  = _LEVEL_NAMES[level]

    # 4) Build header and reply
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
# SWITCH STAKE
# --------------------------
@router.callback_query(F.data.startswith("switch_stake:"))
async def cb_switch_stake(cbq: CallbackQuery, state: FSMContext):
    user_id = cbq.from_user.id
    level   = cbq.data.split(":", 1)[1]

    # new on-chain balance
    balance = await sync_user_wallet_balance(user_id)

    # fetch new level pool info
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
        await release_connection(conn)

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
    await cbq.message.edit_text(header, reply_markup=play_menu_keyboard(level, pool_id, spots_left, pot))

# --------------------------
# INIT BUY: SINGLE TICKET
# --------------------------
@router.callback_query(F.data.startswith("init_buy_ticket:"))
async def cb_init_buy_ticket(cbq: CallbackQuery):
    level = cbq.data.split(":", 1)[1]
    emoji, name = _LEVEL_EMOJIS[level], _LEVEL_NAMES[level]
    user_id = cbq.from_user.id
    balance = await sync_user_wallet_balance(user_id)

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
        await release_connection(conn)

    text = (
        f"🎰 <b>Lottery Menu</b>\n"
        f"💰 <b>Balance:</b> {balance:.4f} SOL\n\n"
        f"🔖 <b>Tier:</b> {emoji} {name}\n"
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
    emoji, name = _LEVEL_EMOJIS[level], _LEVEL_NAMES[level]
    user_id = cbq.from_user.id
    balance = await sync_user_wallet_balance(user_id)

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
        await release_connection(conn)

    text = (
        f"🎰 <b>Lottery Menu</b>\n"
        f"💰 <b>Balance:</b> {balance:.4f} SOL\n\n"
        f"🔖 <b>Tier:</b> {emoji} {name}\n"
        f"🎟 <b>Buy 3× Tickets</b>\n"
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
        return await cbq.message.edit_text("🚫 <b>Purchase cancelled.</b>", reply_markup=main_menu_keyboard())

    user_id = cbq.from_user.id
    price   = _LEVEL_PRICES[level]
    result  = await buy_ticket(user_id, price, level, cbq, bot, num_tickets=1)
    if not result.get("success"):
        return await cbq.message.edit_text(f"❌ {result['message']}", reply_markup=main_menu_keyboard())

    # private confirmation
    emoji      = _LEVEL_EMOJIS[level]
    name       = _LEVEL_NAMES[level]
    pool_id    = result["pool_id"]
    spots_left = result["spots_left"]
    pot        = result["pot"]
    await cbq.message.edit_text(
        f"✅ <b>Ticket purchased!</b>\n"
        f"🏷 {emoji} {name} — Pool #{pool_id}\n"
        f"┣ 🎟 Spots left: <b>{spots_left}/{POOL_SIZE}</b>\n"
        f"┗ 💰 Pot: <b>{pot:.2f} SOL</b>",
        reply_markup=main_menu_keyboard()
    )

    # generate and send ticket image in groups
    img_path = _make_ticket_image(cbq.from_user.first_name or "Player", pot)
    photo = FSInputFile(img_path)

    conn = await get_connection()
    rows = await conn.fetch("SELECT chat_id FROM group_settings WHERE buy_signals_enabled=TRUE")
    await release_connection(conn)

    announcement = (
        f"{cbq.from_user.first_name} just bought 1 ticket in pool {emoji} {name} "
        f"(#{pool_id})! Spots left: {spots_left}/{POOL_SIZE} | Current pot: {pot:.2f} SOL"
    )
    for r in rows:
        try:
            await bot.send_photo(
                chat_id=r["chat_id"],
                photo=photo,
                caption=announcement,
                reply_markup=group_buy_signal_keyboard()
            )
        except:
            pass

    os.remove(img_path)

# --------------------------
# CONFIRM BUY: THREE
# --------------------------
@router.callback_query(F.data.startswith("confirm_buy_3:"))
async def cb_confirm_buy_3(cbq: CallbackQuery):
    _, level, choice = cbq.data.split(":")
    if choice == "no":
        return await cbq.message.edit_text("🚫 <b>Purchase cancelled.</b>", reply_markup=main_menu_keyboard())

    user_id        = cbq.from_user.id
    price          = _LEVEL_PRICES[level]
    result         = await buy_ticket(user_id, price, level, cbq, bot, num_tickets=3)
    if not result.get("success"):
        return await cbq.message.edit_text(f"❌ {result['message']}", reply_markup=main_menu_keyboard())

    # private confirmation
    emoji          = _LEVEL_EMOJIS[level]
    name           = _LEVEL_NAMES[level]
    pool_id        = result["pool_id"]
    spots_left     = result["spots_left"]
    pot            = result["pot"]
    bought         = result.get("tickets_bought", 3)
    await cbq.message.edit_text(
        f"✅ <b>{bought} tickets purchased!</b>\n"
        f"🏷 {emoji} {name} — Pool #{pool_id}\n"
        f"┣ 🎟 Spots left: <b>{spots_left}/{POOL_SIZE}</b>\n"
        f"┗ 💰 Pot: <b>{pot:.2f} SOL</b>",
        reply_markup=main_menu_keyboard()
    )

    # generate and send ticket image in groups
    img_path = _make_ticket_image(cbq.from_user.first_name or "Player", pot)
    photo = FSInputFile(img_path)

    conn = await get_connection()
    rows = await conn.fetch("SELECT chat_id FROM group_settings WHERE buy_signals_enabled=TRUE")
    await release_connection(conn)

    announcement = (
        f"{cbq.from_user.first_name} just bought {bought} tickets in pool {emoji} {name} "
        f"(#{pool_id})! Spots left: {spots_left}/{POOL_SIZE} | Current pot: {pot:.2f} SOL"
    )
    for r in rows:
        try:
            await bot.send_photo(
                chat_id=r["chat_id"],
                photo=photo,
                caption=announcement,
                reply_markup=group_buy_signal_keyboard()
            )
        except:
            pass

    os.remove(img_path)

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
                lines.append(f"{_LEVEL_EMOJIS[level]} <b>{_LEVEL_NAMES[level]}</b> — {count}/{POOL_SIZE} tickets, pot {pot:.2f} SOL")
            else:
                lines.append(f"{_LEVEL_EMOJIS[level]} <b>{_LEVEL_NAMES[level]}</b> — No open pool")
        return "\n".join(lines)
    finally:
        await release_connection(conn)

# --------------------------
# WITHDRAW FLOW
# --------------------------
@router.message(Command("cancel"), StateFilter(WithdrawState))
async def cancel_withdraw(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "🚫 <b>Withdrawal cancelled.</b>",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "wallet_withdraw_prompt")
async def cb_withdraw_prompt(cbq: CallbackQuery, state: FSMContext):
    await cbq.message.edit_text("🚚 <b>Enter external Solana address:</b>\n(or /cancel to abort)")
    await state.set_state(WithdrawState.waiting_for_address)

@router.callback_query(F.data == "wallet_withdraw_all")
async def cb_withdraw_all(cbq: CallbackQuery, state: FSMContext):
    await state.update_data(requested_amount="all")
    await cbq.message.edit_text("🚚 <b>Enter address to withdraw <u>all</u> funds:</b>\n(or /cancel to abort)")
    await state.set_state(WithdrawState.waiting_for_address)

@router.message(StateFilter(WithdrawState.waiting_for_address))
async def process_withdraw_address(msg: Message, state: FSMContext):
    addr = msg.text.strip()
    if len(addr) < 32 or len(addr) > 44:
        return await msg.answer("⛔ <b>Invalid address length.</b> Enter a valid Solana address or /cancel.")

    data = await state.get_data()
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT wallet_public_key FROM users WHERE user_id=$1",
            msg.from_user.id
        )
    finally:
        await release_connection(conn)

    user_pub = row["wallet_public_key"] if row else None
    if addr == user_pub:
        return await msg.answer("⛔ <b>Cannot withdraw to your own wallet address.</b> Enter a different address or /cancel.")

    try:
        _ = Pubkey.from_string(addr)
    except:
        return await msg.answer("⛔ <b>Invalid address format.</b> Enter a valid Solana address or /cancel.")

    await state.update_data(recipient_address=addr)
    if data.get("requested_amount") == "all":
        return await finalize_withdraw(msg, state)

    await msg.answer(
        "✅ <b>Address OK!</b>\nNow send amount in SOL to withdraw, or type 'all', or /cancel."
    )
    await state.set_state(WithdrawState.waiting_for_amount)

@router.message(StateFilter(WithdrawState.waiting_for_amount))
async def process_withdraw_amount(msg: Message, state: FSMContext):
    inp = msg.text.strip().lower()
    if inp != "all":
        try:
            float(inp)
        except ValueError:
            return await msg.answer("⛔ <b>Invalid amount format.</b> Enter a number or 'all', or /cancel.")
    await state.update_data(requested_amount=inp)
    await finalize_withdraw(msg, state)

async def finalize_withdraw(msg: Message, state: FSMContext):
    data = await state.get_data()
    recipient = data["recipient_address"]
    req = data["requested_amount"]

    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT wallet_public_key, wallet_private_key FROM users WHERE user_id=$1",
            msg.from_user.id
        )
    finally:
        await release_connection(conn)

    if not row or not row["wallet_public_key"]:
        await msg.answer("⚠️ <b>No wallet found. Use /start.</b>", reply_markup=main_menu_keyboard())
        return await state.clear()

    user_pubkey, priv = row["wallet_public_key"], row["wallet_private_key"]
    from solana_utils import get_wallet_balance, pay_sol
    balance = await get_wallet_balance(user_pubkey)

    amount = balance - 0.001 if req == "all" else float(req)
    if amount > balance:
        return await msg.answer(f"⛔ <b>Insufficient funds:</b> {balance:.4f} SOL")

    try:
        sig = await pay_sol(priv, user_pubkey, recipient, amount)
        await msg.answer(f"🚀 <b>Withdrawn {amount:.4f} SOL</b>\nTx: https://solscan.io/tx/{sig}", reply_markup=main_menu_keyboard())
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
                   SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) AS total_wins
            FROM tickets WHERE user_id=$1
        """, user_id)
        per_level = await conn.fetch("""
            SELECT level,
                   COUNT(*) AS tickets,
                   COALESCE(SUM(value),0) AS spent,
                   COALESCE(SUM(prize_amount),0) AS won,
                   SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) AS wins
            FROM tickets WHERE user_id=$1 GROUP BY level
        """, user_id)
    finally:
        await release_connection(conn)

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
        emoji, name = _LEVEL_EMOJIS[lvl], _LEVEL_NAMES[lvl]
        prefix = "└" if i == len(_LEVELS) - 1 else "├"
        if row:
            rate = (row["wins"] / row["tickets"] * 100) if row["tickets"] else 0.0
            content = f"{row['tickets']} bought, spent {row['spent']:.2f}, won {row['won']:.2f}, {row['wins']} wins ({rate:.1f}%)"
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
    await cbq.message.answer(f"{status}\n\n🔙 <b>Main Menu</b>", reply_markup=main_menu_keyboard())

# --------------------------
# MENU: History
# --------------------------
@router.callback_query(F.data == "menu_history")
async def cb_menu_history(cbq: CallbackQuery):
    user_id = cbq.from_user.id
    conn = await get_connection()
    try:
        rows = await conn.fetch("""
            SELECT pool_id, level, status='won' AS is_winner, prize_amount, created_at
            FROM tickets WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10
        """, user_id)
    finally:
        await release_connection(conn)

    if not rows:
        return await cbq.message.edit_text("📜 <b>No history yet!</b>\nPlay to see your past tickets.", reply_markup=history_keyboard())

    lines = ["📜 <b>Recent History</b>", "────────────────────"]
    for t in rows:
        emoji = _LEVEL_EMOJIS.get(t["level"], "")
        name  = _LEVEL_NAMES.get(t["level"], t["level"])
        outcome = "✅ <b>WIN</b>" if t["is_winner"] else "❌ <b>Lost</b>"
        prize   = f"{t['prize_amount']:.2f} SOL" if t["is_winner"] else "-"
        ts = t["created_at"].strftime("%Y-%m-%d %H:%M")
        lines.append(f"{emoji} <b>{name}</b> | Pool #{t['pool_id']} | {outcome} | Prize: {prize}\n<i>{ts}</i>")

    await cbq.message.edit_text("\n".join(lines), reply_markup=history_keyboard())

# --------------------------
# SHOW PRIVATE KEY
# --------------------------
@router.callback_query(F.data == "wallet_show_private_key")
async def cb_show_private_key(cbq: CallbackQuery):
    if cbq.message.chat.type != "private":
        return await cbq.answer("🔒 Private keys are shown only in private chat.", show_alert=True)

    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT wallet_public_key, wallet_private_key FROM users WHERE user_id=$1", cbq.from_user.id)
    finally:
        await release_connection(conn)

    if not row or not row["wallet_public_key"]:
        return await cbq.message.edit_text("⚠️ <b>No wallet found.</b> Use /start to create one.", reply_markup=main_menu_keyboard())

    await cbq.message.answer(
        "🔑 <b>Your Wallet Credentials</b>\n\n"
        f"📮 Address:\n<code>{row['wallet_public_key']}</code>\n\n"
        f"🗝️ Private Key (keep it secret!):\n<code>{row['wallet_private_key']}</code>",
        reply_markup=privatekey_keyboard()
    )

# --------------------------
# SIMPLE COMMANDS
# --------------------------
@router.message(Command("buy"))
async def cmd_buy(msg: Message):
    kb = buy_now_keyboard() if msg.chat.type in ("group", "supergroup") else main_menu_keyboard()
    await msg.answer("🎟️ Want to join the lottery? Tap below!" if msg.chat.type in ("group","supergroup") else "🎰 Ready to play?", reply_markup=kb)

@router.message(Command("reset"))
async def cmd_reset(msg: Message):
    if msg.from_user.id != 6428898245:
        return await msg.reply("⛔ You’re not authorized to do that.")
    conn = await get_connection()
    try:
        await conn.execute("DELETE FROM tickets")
        await conn.execute("DELETE FROM pools")
        for lvl in _LEVELS:
            await conn.execute("INSERT INTO pools (level, status) VALUES ($1, 'OPEN')", lvl)
    finally:
        await release_connection(conn)
    await msg.reply("✅ All pools and tickets reset. New OPEN pools ready!")

# --------------------------
# ROUTER REGISTRATION
# --------------------------
# In your main: dp = Dispatcher(storage=MemoryStorage()); dp.include_router(router)
dp = None
