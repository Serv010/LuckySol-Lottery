from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_USERNAME, _LEVEL_PRICES, _LEVEL_EMOJIS, _LEVEL_NAMES, _LEVELS
from typing import Optional

def _next_level(current: str) -> str:
    """
    Rotate through ["low","mid","high"] in order, wrapping around.
    """
    idx = _LEVELS.index(current)
    return _LEVELS[(idx + 1) % len(_LEVELS)]

# ────────────────────────────────────────────────────────────────
#  DISCLAIMER TEXTS
# ────────────────────────────────────────────────────────────────
DISCLAIMER_TEXT = (
    "<b><i>Solana Lottery Bot - Disclaimer &amp; Terms of Participation</i></b>\n\n"
    "<b>Welcome to the Solana Lottery Bot!</b>\n\n"
    "Before you can participate, you must read and accept the following:\n\n"
    
    "<b>1. No Guarantees or Financial Advice</b>\n"
    "   This bot is provided for <i>entertainment</i> and <i>experimental</i> purposes only. "
    "Participation in the lottery does not guarantee any <b>winnings</b>. No part of this system "
    "constitutes <b>investment advice</b>, <b>financial services</b>, or any form of solicitation.\n\n"
    
    "<b>2. Participation Is at Your Own Risk</b>\n"
    "   By using this bot, you acknowledge that you are fully responsible for your actions, including "
    "any deposits, ticket purchases, and wallet interactions. You accept all risks associated with "
    "<b>digital assets</b> and <b>decentralized systems</b>.\n\n"
    
    "<b>3. Crypto Is Volatile</b>\n"
    "   SOL (<i>Solana</i>) and other cryptocurrencies are highly volatile. Sudden changes in network fees, "
    "congestion, or transaction times may affect your experience or delay lottery processing.\n\n"
    
    "<b>4. Not Affiliated with Solana or Any Official Entity</b>\n"
    "   This bot is not endorsed by the <b>Solana Foundation</b>, Telegram, or any official organization. "
    "It is an independent application running on the <i>Solana blockchain</i>.\n\n"
    
    "<b>5. Lottery Mechanics</b>\n"
    "   - Each lottery round accepts a limited number of participants.\n"
    "   - Ticket purchases are <b>final</b> and <i>non-refundable</i>.\n"
    "   - Winners are chosen <b>randomly</b>.\n"
    "   - Winnings are automatically paid out to your wallet.\n"
    "   - A fixed percentage of the pot goes to operational wallets (<b>House</b> and <b>Developer</b>) for sustainability.\n\n"
    
    "<b>6. Wallet &amp; Private Key Handling</b>\n"
    "   When you first accept these terms, a new wallet will be created for you. Your private key will be "
    "shown only once and is your responsibility to store safely. If you lose it, you lose access to your funds.\n\n"
    
    "<b>7. Legal Restrictions</b>\n"
    "   - You must be of legal age to participate in games of chance in your jurisdiction.\n"
    "   - By proceeding, you confirm that such activity is permitted in your country or region.\n"
    "   - This bot does not operate in, and should not be used by residents of, jurisdictions where lotteries "
    "or crypto-based games are prohibited.\n\n"
    
    "<b>8. Privacy</b>\n"
    "   The bot collects only the information required for gameplay and does not share your data with third parties. "
    "Blockchain transactions are <i>public</i> and <i>immutable</i>.\n\n"
    
    "By tapping \"<b>I Acknowledge and Accept</b>\", you confirm that you have read, understood, and agreed to the above terms.\n"
    "If you do not agree, please stop using the bot immediately."
)

DISCLAIMER_TEXT2 = (
    "<b><i>Solana Lottery Bot - Disclaimer &amp; Terms of Participation</i></b>\n\n"
    "<b>Welcome to the Solana Lottery Bot!</b>\n\n"
    "Before you can participate, you must read and accept the following:\n\n"
    
    "<b>1. No Guarantees or Financial Advice</b>\n"
    "   This bot is provided for <i>entertainment</i> and <i>experimental</i> purposes only. "
    "Participation in the lottery does not guarantee any <b>winnings</b>. No part of this system "
    "constitutes <b>investment advice</b>, <b>financial services</b>, or any form of solicitation.\n\n"
    
    "<b>2. Participation Is at Your Own Risk</b>\n"
    "   By using this bot, you acknowledge that you are fully responsible for your actions, including "
    "any deposits, ticket purchases, and wallet interactions. You accept all risks associated with "
    "<b>digital assets</b> and <b>decentralized systems</b>.\n\n"
    
    "<b>3. Crypto Is Volatile</b>\n"
    "   SOL (<i>Solana</i>) and other cryptocurrencies are highly volatile. Sudden changes in network fees, "
    "congestion, or transaction times may affect your experience or delay lottery processing.\n\n"
    
    "<b>4. Not Affiliated with Solana or Any Official Entity</b>\n"
    "   This bot is not endorsed by the <b>Solana Foundation</b>, Telegram, or any official organization. "
    "It is an independent application running on the <i>Solana blockchain</i>.\n\n"
    
    "<b>5. Lottery Mechanics</b>\n"
    "   - Each lottery round accepts a limited number of participants.\n"
    "   - Ticket purchases are <b>final</b> and <i>non-refundable</i>.\n"
    "   - Winners are chosen <b>randomly</b>.\n"
    "   - Winnings are automatically paid out to your wallet.\n"
    "   - A fixed percentage of the pot goes to operational wallets (<b>House</b> and <b>Developer</b>) for sustainability.\n\n"
    
    "<b>6. Wallet &amp; Private Key Handling</b>\n"
    "   When you first accept these terms, a new wallet will be created for you. Your private key will be "
    "shown only once and is your responsibility to store safely. If you lose it, you lose access to your funds.\n\n"
    
    "<b>7. Legal Restrictions</b>\n"
    "   - You must be of legal age to participate in games of chance in your jurisdiction.\n"
    "   - By proceeding, you confirm that such activity is permitted in your country or region.\n"
    "   - This bot does not operate in, and should not be used by residents of, jurisdictions where lotteries "
    "or crypto-based games are prohibited.\n\n"
    
    "<b>8. Privacy</b>\n"
    "   The bot collects only the information required for gameplay and does not share your data with third parties. "
    "Blockchain transactions are <i>public</i> and <i>immutable</i>.\n\n"
    
    "By tapping \"<b>I Acknowledge and Accept</b>\", you confirm that you have read, understood, and agreed to the above terms.\n"
    "If you do not agree, please stop using the bot immediately."
)

# ────────────────────────────────────────────────────────────────
#  GROUP BUY SIGNALS
# ────────────────────────────────────────────────────────────────
def group_buy_signal_keyboard() -> InlineKeyboardMarkup:
    """
    Inline button to send users back to the bot start 
    so they can purchase tickets in groups.
    """
    url = f"https://t.me/{BOT_USERNAME}?start=start"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Play Now", url=url)]
    ])

def buy_now_keyboard() -> InlineKeyboardMarkup:
    """
    A “Buy Now” button that deep-links users from a group into your bot’s /start flow.
    """
    url = f"https://t.me/{BOT_USERNAME}?start=start"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Buy Now!", url=url)],
    ])

# ────────────────────────────────────────────────────────────────
#  HOUSE-KEEPING KEYBOARDS
# ────────────────────────────────────────────────────────────────
def disclaimer_keyboard() -> InlineKeyboardMarkup:
    """
    Disclaimer screen - includes 'I Acknowledge and Accept' 
    and 'Back to Main' buttons.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="I Acknowledge and Accept", callback_data="accept_disclaimer")],
        [InlineKeyboardButton(text="Back to Main",               callback_data="disclaimer_back_main")]
    ])

def help_keyboard() -> InlineKeyboardMarkup:
    """
    Help / FAQ screen - has only 'Back to Main' button.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Back to Main", callback_data="back_main")]
    ])

def continue_keyboard() -> InlineKeyboardMarkup:
    """
    After disclaimer is accepted - 'Continue' button.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Continue", callback_data="continue_main")]
    ])

def view_disclaimer_keyboard() -> InlineKeyboardMarkup:
    """
    Simple 'View Disclaimer' button.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="View Disclaimer", callback_data="view_disclaimer")]
    ])

def play_again_keyboard() -> InlineKeyboardMarkup:
    """
    Button shown after a win/loss to let user jump back 
    into the lottery flow.
    """
    url = f"https://t.me/{BOT_USERNAME}?start=start"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Buy Another Ticket!", url=url)]
    ])

# ────────────────────────────────────────────────────────────────
#  MAIN MENU & WALLET MENUS
# ────────────────────────────────────────────────────────────────
def main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    The main navigation keyboard.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Wallet",       callback_data="menu_wallet"),
            InlineKeyboardButton(text="Play Lottery", callback_data="menu_play"),
        ],
        [
            InlineKeyboardButton(text="My Stats",    callback_data="menu_stats"),
            InlineKeyboardButton(text="My History",  callback_data="menu_history"),
        ],
        [
            InlineKeyboardButton(text="Referrals",    callback_data="menu_referrals"),
        ],
        [
            InlineKeyboardButton(text="Help / FAQ",   callback_data="menu_help"),
            InlineKeyboardButton(text="View Disclaimer", callback_data="view_disclaimer"),
        ],
    ])


def wallet_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Wallet submenu for withdraw, key display, and navigation.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        # Allow withdrawing all or a custom amount
        [InlineKeyboardButton(text="Withdraw All", callback_data="wallet_withdraw_all")],
        [InlineKeyboardButton(text="Withdraw Amount", callback_data="wallet_withdraw_prompt")],
        [InlineKeyboardButton(text="Show Private Key", callback_data="wallet_show_private_key")],
        [
            InlineKeyboardButton(text="Back to Main", callback_data="back_main"),
            InlineKeyboardButton(text="View Disclaimer", callback_data="view_disclaimer"),
        ]
    ])

# ────────────────────────────────────────────────────────────────
#  PLAY MENU (Multi-Stake with Toggle)
# ────────────────────────────────────────────────────────────────
def play_menu_keyboard(
    level: str,
    pool_id: Optional[int],
    spots_left: int,
    pot: float
) -> InlineKeyboardMarkup:
    """
    Playground menu for a given stake level, showing specific pool details.
    """
    price    = _LEVEL_PRICES[level]
    emoji    = _LEVEL_EMOJIS[level]
    next_lvl = _next_level(level)
    next_name = _LEVEL_NAMES[next_lvl]

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"Buy 1×🎟 ({price:.2f} SOL)",
                callback_data=f"init_buy_ticket:{level}"
            ),
            InlineKeyboardButton(
                text=f"Buy 3×🎟 ({(price*3):.2f} SOL)",
                callback_data=f"init_buy_3_tickets:{level}"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"Switch to: {_LEVEL_EMOJIS[next_lvl]} {next_name}",
                callback_data=f"switch_stake:{next_lvl}"
            )
        ],
        [
            InlineKeyboardButton(text="Back to Main", callback_data="back_main"),
            InlineKeyboardButton(text="View Disclaimer", callback_data="view_disclaimer"),
        ],
    ])

# ────────────────────────────────────────────────────────────────
#  CONFIRMATION DIALOGS (Multi-Stake)
# ────────────────────────────────────────────────────────────────
def confirm_buy_keyboard_multi(level: str) -> InlineKeyboardMarkup:
    """
    Confirmation for buying a single ticket at the given stake level.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes", callback_data=f"confirm_buy:{level}:yes"),
            InlineKeyboardButton(text="No",  callback_data=f"confirm_buy:{level}:no"),
        ],
        [
            InlineKeyboardButton(text="View Disclaimer", callback_data="view_disclaimer")
        ],
    ])

def confirm_buy_3_keyboard_multi(level: str) -> InlineKeyboardMarkup:
    """
    Confirmation for buying three tickets at the given stake level.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes, 3 tickets", callback_data=f"confirm_buy_3:{level}:yes"),
            InlineKeyboardButton(text="No",              callback_data=f"confirm_buy_3:{level}:no"),
        ],
        [
            InlineKeyboardButton(text="View Disclaimer", callback_data="view_disclaimer")
        ],
    ])

# ────────────────────────────────────────────────────────────────
#  CLAIM REWARD
# ────────────────────────────────────────────────────────────────
def claim_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """
    For winners to claim their prize (fallback if auto-sent fails).
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Claim Reward", callback_data=f"claim:{ticket_id}")],
        [InlineKeyboardButton(text="View Disclaimer", callback_data="view_disclaimer")],
    ])

# ────────────────────────────────────────────────────────────────
#  “Back to Main”
# ────────────────────────────────────────────────────────────────
def stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Main", callback_data="back_main")]
    ])

def history_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Main", callback_data="back_main")]
    ])

def referrals_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Main", callback_data="back_main")],
    ])

def privatekey_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Main", callback_data="back_main")],
    ])
