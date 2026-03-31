from datetime import datetime, timezone

from src.logger import setup_logger

logger = setup_logger("market_selector")


def select_markets(markets: list[dict], config: dict) -> list[dict]:
    """
    Filter and rank markets for liquidity provision.

    Selection criteria:
    - Active and trading
    - Sufficient volume
    - Sufficient spread (profit opportunity)
    - Enough time to resolution (avoid binary resolution risk)
    """
    min_volume = config.get("min_volume_24h", 10000)
    min_spread = config.get("min_spread", 0.02)
    min_days = config.get("min_time_to_resolution_days", 7)
    max_markets = config.get("max_markets", 5)

    now = datetime.now(timezone.utc)
    candidates = []

    for market in markets:
        if not market.get("active", False):
            continue

        # Check volume
        volume = float(market.get("volume_num_24hr", 0) or 0)
        if volume < min_volume:
            continue

        # Check time to resolution
        end_date_str = market.get("end_date_iso")
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                days_remaining = (end_date - now).days
                if days_remaining < min_days:
                    logger.debug(
                        "Skipping %s: only %d days to resolution",
                        market.get("question", "?")[:50], days_remaining,
                    )
                    continue
            except (ValueError, TypeError):
                pass

        # Check spread from tokens
        tokens = market.get("tokens", [])
        if len(tokens) < 2:
            continue

        best_bid = float(tokens[0].get("price", 0) or 0)
        best_ask = 1.0 - float(tokens[1].get("price", 0) or 0)
        spread = abs(best_ask - best_bid)

        if spread < min_spread:
            continue

        # Score: higher volume and spread = more attractive
        score = volume * spread
        candidates.append({
            "market": market,
            "volume": volume,
            "spread": spread,
            "score": score,
            "token_id": tokens[0].get("token_id", ""),
            "question": market.get("question", "Unknown"),
        })

    # Sort by score descending
    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected = candidates[:max_markets]

    logger.info(
        "Selected %d/%d markets from %d candidates",
        len(selected), max_markets, len(candidates),
    )
    for m in selected:
        logger.info(
            "  - %s (vol=%.0f, spread=%.4f, score=%.0f)",
            m["question"][:60], m["volume"], m["spread"], m["score"],
        )

    return selected
