import os
import time
from dataclasses import dataclass

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds

from src.logger import setup_logger

logger = setup_logger("client")


@dataclass
class OrderResult:
    order_id: str
    side: str
    price: float
    size: float
    token_id: str
    status: str = "open"


class PolymarketClient:
    def __init__(self, config: dict, dry_run: bool = True):
        self.dry_run = dry_run
        self.config = config
        self._client = None

        if not dry_run:
            self._init_client()

    def _init_client(self):
        host = self.config.get("host", "https://clob.polymarket.com")
        chain_id = self.config.get("chain_id", 137)
        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")

        self._client = ClobClient(
            host=host,
            key=private_key,
            chain_id=chain_id,
        )

        api_key = os.environ.get("POLYMARKET_API_KEY")
        api_secret = os.environ.get("POLYMARKET_API_SECRET")
        api_passphrase = os.environ.get("POLYMARKET_API_PASSPHRASE")

        if api_key and api_secret and api_passphrase:
            self._client.set_api_creds(ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase,
            ))
        else:
            logger.info("No API creds found, deriving from private key...")
            self._client.set_api_creds(self._client.create_or_derive_api_creds())

        logger.info("Polymarket client initialized (chain_id=%d)", chain_id)

    def get_markets(self) -> list[dict]:
        if self.dry_run:
            logger.info("[DRY RUN] get_markets()")
            return []
        return self._client.get_markets()

    def get_orderbook(self, token_id: str) -> dict:
        if self.dry_run:
            logger.info("[DRY RUN] get_orderbook(%s)", token_id)
            return {"bids": [], "asks": []}
        return self._client.get_order_book(token_id)

    def get_midpoint(self, token_id: str) -> float | None:
        if self.dry_run:
            return None
        try:
            mid = self._client.get_midpoint(token_id)
            return float(mid) if mid else None
        except Exception as e:
            logger.error("Error getting midpoint for %s: %s", token_id, e)
            return None

    def place_order(
        self, token_id: str, side: str, price: float, size: float
    ) -> OrderResult | None:
        if self.dry_run:
            fake_id = f"dry_{token_id[:8]}_{side}_{price}_{int(time.time())}"
            logger.info(
                "[DRY RUN] place_order: %s %s @ %.4f, size=%.2f, token=%s",
                side, "BUY" if side == "BUY" else "SELL", price, size, token_id[:16],
            )
            return OrderResult(
                order_id=fake_id,
                side=side,
                price=price,
                size=size,
                token_id=token_id,
            )

        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
                order_type=OrderType.GTC,
            )
            resp = self._client.create_and_post_order(order_args)
            order_id = resp.get("orderID", resp.get("id", "unknown"))
            logger.info(
                "Order placed: %s %s @ %.4f, size=%.2f, id=%s",
                side, token_id[:16], price, size, order_id,
            )
            return OrderResult(
                order_id=order_id,
                side=side,
                price=price,
                size=size,
                token_id=token_id,
            )
        except Exception as e:
            logger.error("Failed to place order: %s", e)
            return None

    def cancel_order(self, order_id: str) -> bool:
        if self.dry_run:
            logger.info("[DRY RUN] cancel_order(%s)", order_id)
            return True
        try:
            self._client.cancel(order_id)
            logger.info("Order cancelled: %s", order_id)
            return True
        except Exception as e:
            logger.error("Failed to cancel order %s: %s", order_id, e)
            return False

    def cancel_all(self) -> bool:
        if self.dry_run:
            logger.info("[DRY RUN] cancel_all()")
            return True
        try:
            self._client.cancel_all()
            logger.info("All orders cancelled")
            return True
        except Exception as e:
            logger.error("Failed to cancel all orders: %s", e)
            return False

    def get_positions(self) -> list[dict]:
        if self.dry_run:
            logger.info("[DRY RUN] get_positions()")
            return []
        try:
            return self._client.get_positions() or []
        except Exception as e:
            logger.error("Failed to get positions: %s", e)
            return []

    def get_open_orders(self) -> list[dict]:
        if self.dry_run:
            logger.info("[DRY RUN] get_open_orders()")
            return []
        try:
            return self._client.get_orders() or []
        except Exception as e:
            logger.error("Failed to get open orders: %s", e)
            return []
