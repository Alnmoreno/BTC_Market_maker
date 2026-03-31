from dataclasses import dataclass, field

from src.client import PolymarketClient, OrderResult
from src.pricing_engine import Quote
from src.logger import setup_logger

logger = setup_logger("orders")

# Minimum price change to trigger order update (avoids excessive cancel/replace)
MIN_PRICE_CHANGE = 0.005


@dataclass
class ManagedOrder:
    order: OrderResult
    level: int = 0


class OrderManager:
    def __init__(self, client: PolymarketClient):
        self.client = client
        # token_id -> list of managed orders
        self.active_orders: dict[str, list[ManagedOrder]] = {}
        self.fill_callbacks: list = []

    def on_fill(self, callback):
        """Register a callback for fill events: callback(token_id, side, price, size)."""
        self.fill_callbacks.append(callback)

    def update_orders(self, token_id: str, quotes: list[Quote]) -> list[OrderResult]:
        """Cancel stale orders and place new ones based on desired quotes."""
        current = self.active_orders.get(token_id, [])
        new_managed = []

        # Build desired orders from quotes
        desired_bids = [(q.bid_price, q.bid_size, q.level) for q in quotes]
        desired_asks = [(q.ask_price, q.ask_size, q.level) for q in quotes]

        # Cancel all existing orders for this token (simple strategy: full refresh)
        orders_to_cancel = [m.order for m in current if not m.order.order_id.startswith("dry_")]
        if current and not self._should_refresh(current, quotes):
            logger.debug("Orders for %s still valid, skipping refresh", token_id[:12])
            return [m.order for m in current]

        for m in current:
            self.client.cancel_order(m.order.order_id)

        # Place new bid orders
        for price, size, level in desired_bids:
            result = self.client.place_order(token_id, "BUY", price, size)
            if result:
                new_managed.append(ManagedOrder(order=result, level=level))

        # Place new ask orders
        for price, size, level in desired_asks:
            result = self.client.place_order(token_id, "SELL", price, size)
            if result:
                new_managed.append(ManagedOrder(order=result, level=level))

        self.active_orders[token_id] = new_managed

        placed = len(new_managed)
        logger.info(
            "Updated orders for %s: cancelled %d, placed %d (bids=%d, asks=%d)",
            token_id[:12], len(current), placed, len(desired_bids), len(desired_asks),
        )

        return [m.order for m in new_managed]

    def _should_refresh(self, current: list[ManagedOrder], quotes: list[Quote]) -> bool:
        """Check if current orders deviate enough from desired quotes to warrant refresh."""
        if len(current) != len(quotes) * 2:
            return True

        current_bids = sorted(
            [m for m in current if m.order.side == "BUY"],
            key=lambda m: m.level,
        )
        current_asks = sorted(
            [m for m in current if m.order.side == "SELL"],
            key=lambda m: m.level,
        )

        for i, q in enumerate(quotes):
            if i < len(current_bids):
                if abs(current_bids[i].order.price - q.bid_price) > MIN_PRICE_CHANGE:
                    return True
            if i < len(current_asks):
                if abs(current_asks[i].order.price - q.ask_price) > MIN_PRICE_CHANGE:
                    return True

        return False

    def cancel_all_for_token(self, token_id: str):
        """Cancel all orders for a specific token."""
        orders = self.active_orders.pop(token_id, [])
        for m in orders:
            self.client.cancel_order(m.order.order_id)
        logger.info("Cancelled all %d orders for %s", len(orders), token_id[:12])

    def cancel_all(self):
        """Cancel all active orders across all tokens."""
        total = sum(len(orders) for orders in self.active_orders.values())
        self.client.cancel_all()
        self.active_orders.clear()
        logger.info("Cancelled all %d orders", total)

    def get_active_count(self) -> int:
        return sum(len(orders) for orders in self.active_orders.values())
