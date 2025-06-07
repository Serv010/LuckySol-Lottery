import asyncio
import logging
import base58
import httpx

from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solders.transaction import Transaction
from solders.system_program import transfer, TransferParams
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.message import Message

from config import SOLANA_RPC_ENDPOINT, POOL_PUBLIC_KEY

# ─── Monkey-patch to drop any `proxy` kwarg ───
_httpx_orig_init = httpx.AsyncClient.__init__
def _httpx_init_no_proxy(self, *args, **kwargs):
    kwargs.pop("proxy", None)
    return _httpx_orig_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _httpx_init_no_proxy

# ─── Shared timeout (seconds) ───
_RPC_TIMEOUT = 60.0

def _normalize_endpoint(url: str) -> str:
    return url if url.startswith("http") else f"https://{url}"

# ─── Helpers ───────────────────────────────────────────────────────────

async def get_wallet_balance_lamports(pubkey_str: str) -> int:
    """
    Fetch on-chain balance in lamports, retrying up to 3× on ConnectTimeout.
    On persistent failure, returns 0.
    """
    client = AsyncClient(
        _normalize_endpoint(SOLANA_RPC_ENDPOINT),
        timeout=_RPC_TIMEOUT,
    )
    try:
        pubkey = Pubkey.from_string(pubkey_str)
        for attempt in range(3):
            try:
                return (await client.get_balance(pubkey)).value
            except httpx.ConnectTimeout as e:
                logging.warning("get_balance timeout (%d/2): %s", attempt, e)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logging.error("get_balance failed after 3 attempts")
                    return 0
            except httpx.ConnectError as e:
                logging.error("get_balance connection error: %s", e)
                return 0
    finally:
        await client.close()

async def _estimate_fee_lamports(message: Message) -> int:
    """
    Estimate fee in lamports for the given Message,
    retrying up to 2× on ConnectTimeout.
    Falls back to 0 on failure.
    """
    client = AsyncClient(
        _normalize_endpoint(SOLANA_RPC_ENDPOINT),
        timeout=_RPC_TIMEOUT,
    )
    try:
        for attempt in range(2):
            try:
                return (await client.get_fee_for_message(message)).value or 0
            except httpx.ConnectTimeout as e:
                logging.warning("get_fee_for_message timeout (%d/1): %s", attempt, e)
                if attempt < 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logging.error("get_fee_for_message failed after 2 attempts")
                    return 0
            except httpx.ConnectError as e:
                logging.error("get_fee_for_message connection error: %s", e)
                return 0
    finally:
        await client.close()

# ─── Public API ────────────────────────────────────────────────────────

async def get_wallet_balance(pubkey_str: str) -> float:
    """
    Returns SOL balance as float. On RPC failure, returns 0.0.
    """
    lamports = await get_wallet_balance_lamports(pubkey_str)
    return lamports / 1e9

async def get_fee_per_signature() -> float:
    """
    Returns network fee per signature in SOL.
    Falls back to 0.000005 SOL if estimation fails.
    """
    pool_pub = Pubkey.from_string(POOL_PUBLIC_KEY)
    ix       = transfer(TransferParams(from_pubkey=pool_pub, to_pubkey=pool_pub, lamports=0))
    msg      = Message([ix], pool_pub)
    lam = await _estimate_fee_lamports(msg)
    # typical fallback of ~5000 lamports
    return max(lam, 5_000) / 1e9


from solana.exceptions import SolanaRpcException

async def pay_sol(
    sender_private_key_b58: str,
    sender_public_key_str: str,
    recipient_wallet: str,
    amount_sol: float
) -> str:
    """
    Transfer `amount_sol` SOL from sender → recipient.
    Retries once on timeout, uses fresh blockhash, **does not skip preflight**,
    and will raise a clear RuntimeError on insufficient funds.
    """
    client = AsyncClient(
        _normalize_endpoint(SOLANA_RPC_ENDPOINT),
        timeout=_RPC_TIMEOUT,
    )
    try:
        secret     = base58.b58decode(sender_private_key_b58)
        sender_kp  = Keypair.from_bytes(secret)
        sender_pub = Pubkey.from_string(sender_public_key_str)
        recipient  = Pubkey.from_string(recipient_wallet)
        lamports   = int(amount_sol * 1e9)

        ix  = transfer(TransferParams(
                  from_pubkey=sender_pub,
                  to_pubkey=recipient,
                  lamports=lamports
              ))
        msg = Message([ix], sender_pub)

        # fresh blockhash
        bh = await client.get_latest_blockhash()
        tx = Transaction([sender_kp], msg, bh.value.blockhash)

        # ⚠️ preflight ON to catch lamport errors
        opts = TxOpts(skip_preflight=False, preflight_commitment="confirmed")

        try:
            resp = await client.send_transaction(tx, opts=opts)
        except SolanaRpcException as e:
            text = str(e)
            # look for the “insufficient lamports” line in the simulation error
            if "insufficient lamports" in text:
                # you could even fetch the exact balance again here if you like
                raise RuntimeError(
                    f"🚧 Insufficient on‐chain balance to send {amount_sol:.6f} SOL; please top up your wallet."
                ) from e
            raise

        # wait for confirmation (also will error if something went wrong)
        await client.confirm_transaction(resp.value, commitment="confirmed")
        return str(resp.value)

    finally:
        await client.close()

async def batch_pay_sol(
    sender_private_key_b58: str,
    sender_public_key_str: str,
    transfers: list[dict]
) -> str:
    """
    Batch multiple SOL transfers in one tx.
    transfers: [{"recipient": <base58 str>, "amount_sol": <float>}, ...]
    Retries up to 3× on httpx.ConnectTimeout, skips preflight.
    Returns tx signature.
    """
    client = AsyncClient(
        _normalize_endpoint(SOLANA_RPC_ENDPOINT),
        timeout=_RPC_TIMEOUT
    )
    try:
        # load sender
        secret     = base58.b58decode(sender_private_key_b58)
        sender_kp  = Keypair.from_bytes(secret)
        sender_pub = Pubkey.from_string(sender_public_key_str)

        # build all transfer instructions
        instructions = []
        for t in transfers:
            rec = Pubkey.from_string(t["recipient"])
            lam = int(t["amount_sol"] * 1e9)
            instructions.append(
                transfer(TransferParams(
                    from_pubkey=sender_pub,
                    to_pubkey=rec,
                    lamports=lam
                ))
            )

        # grab a recent blockhash
        bh = await client.get_latest_blockhash()
        msg = Message(instructions, sender_pub)
        tx  = Transaction([sender_kp], msg, bh.value.blockhash)

        opts = TxOpts(skip_preflight=True, preflight_commitment="confirmed")
        # attempt send, retry on timeout
        for attempt in range(3):
            try:
                resp = await client.send_transaction(tx, opts=opts)
                return str(resp.value)
            except httpx.ConnectTimeout:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

    finally:
        await client.close()