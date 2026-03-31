from dataclasses import dataclass

from src.logger import setup_logger

logger = setup_logger("pricing")


@dataclass
class Quote:
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    level: int = 0


def calculate_mid_price(orderbook: dict) -> float | None:
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])

    if not bids or not asks:
        return None

    best_bid = float(bids[0].get("price", 0))
    best_ask = float(asks[0].get("price", 0))

    if best_bid <= 0 or best_ask <= 0:
        return None

    return (best_bid + best_ask) / 2


def calculate_quotes(
    mid_price: float,
    inventory: float,
    spread: float,
    order_size: float,
    num_levels: int,
    skew_factor: float,
    max_position: float,
) -> list[Quote]:
    """
    Calculate bid/ask quotes with inventory skew.

    When inventory is positive (long YES), prices shift down to encourage
    selling and discourage buying. Vice versa for negative inventory.

    Args:
        mid_price: Current mid-price (0-1)
        inventory: Current position in USDC terms (positive = long)
        spread: Total spread (e.g. 0.04 = 4 cents)
        order_size: Size per order in USDC
        num_levels: Number of price levels per side
        skew_factor: How aggressively to skew (0-1)
        max_position: Max position for normalization
    """
    quotes = []
    half_spread = spread / 2

    # Normalize inventory to [-1, 1]
    inv_ratio = inventory / max_position if max_position > 0 else 0
    inv_ratio = max(-1.0, min(1.0, inv_ratio))

    skew = skew_factor * inv_ratio * half_spread

    for level in range(num_levels):
        level_offset = level * spread * 0.5  # Each level adds half a spread

        bid = mid_price - half_spread - skew - level_offset
        ask = mid_price + half_spread - skew + level_offset

        bid = max(0.01, min(0.99, round(bid, 4)))
        ask = max(0.01, min(0.99, round(ask, 4)))

        if bid >= ask:
            logger.warning(
                "Bid >= Ask at level %d (bid=%.4f, ask=%.4f), skipping",
                level, bid, ask,
            )
            continue

        # Reduce size at deeper levels
        level_size = order_size * (1.0 - level * 0.2)
        level_size = max(1.0, level_size)

        quotes.append(Quote(
            bid_price=bid,
            ask_price=ask,
            bid_size=level_size,
            ask_size=level_size,
            level=level,
        ))

    return quotes
