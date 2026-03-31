import time
from collections import deque
from dataclasses import dataclass, field

from src.logger import setup_logger

logger = setup_logger("circuit_breaker")


@dataclass
class PriceHistory:
    prices: deque = field(default_factory=lambda: deque(maxlen=500))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=500))

    def add(self, price: float, ts: float | None = None):
        self.prices.append(price)
        self.timestamps.append(ts or time.time())

    def moving_average(self, window_seconds: float) -> float | None:
        """Calculate moving average over the last N seconds."""
        if not self.prices:
            return None

        now = self.timestamps[-1]
        cutoff = now - window_seconds
        total = 0.0
        count = 0

        for i in range(len(self.prices) - 1, -1, -1):
            if self.timestamps[i] < cutoff:
                break
            total += self.prices[i]
            count += 1

        return total / count if count > 0 else None

    def price_change_pct(self, window_seconds: float) -> float | None:
        """Calculate price change percentage over the last N seconds."""
        if len(self.prices) < 2:
            return None

        now = self.timestamps[-1]
        cutoff = now - window_seconds

        # Find oldest price within window
        oldest_price = None
        for i in range(len(self.prices)):
            if self.timestamps[i] >= cutoff:
                oldest_price = self.prices[i]
                break

        if oldest_price is None or oldest_price == 0:
            return None

        current = self.prices[-1]
        return abs(current - oldest_price) / oldest_price * 100

    def volatility(self, window_seconds: float) -> float | None:
        """Standard deviation of price changes within window."""
        if len(self.prices) < 3:
            return None

        now = self.timestamps[-1]
        cutoff = now - window_seconds

        window_prices = []
        for i in range(len(self.prices)):
            if self.timestamps[i] >= cutoff:
                window_prices.append(self.prices[i])

        if len(window_prices) < 2:
            return None

        mean = sum(window_prices) / len(window_prices)
        variance = sum((p - mean) ** 2 for p in window_prices) / len(window_prices)
        return variance ** 0.5


class CircuitBreaker:
    """
    Monitors price movements and triggers a circuit break when prices
    move too fast. Resumes when moving average stabilizes.

    Flow:
    1. Track prices for each market
    2. If price changes > max_change_pct in check_window seconds → TRIP
    3. While tripped: monitor moving average
    4. If MA volatility < recovery_threshold for recovery_window → RECOVER
    """

    def __init__(self, config: dict):
        self.max_change_pct = config.get("max_change_pct", 10.0)
        self.check_window = config.get("check_window_seconds", 60)
        self.ma_window = config.get("ma_window_seconds", 300)
        self.recovery_threshold = config.get("recovery_volatility_threshold", 0.005)
        self.recovery_window = config.get("recovery_window_seconds", 120)

        # token_id -> PriceHistory
        self.histories: dict[str, PriceHistory] = {}
        # token_id -> True if tripped
        self.tripped: dict[str, bool] = {}
        # token_id -> timestamp when tripped
        self.trip_time: dict[str, float] = {}

    def record_price(self, token_id: str, price: float):
        """Record a new price observation."""
        if token_id not in self.histories:
            self.histories[token_id] = PriceHistory()
        self.histories[token_id].add(price)

    def check(self, token_id: str) -> bool:
        """
        Check if trading should continue for this token.
        Returns True if safe to trade, False if circuit breaker is tripped.
        """
        history = self.histories.get(token_id)
        if not history or len(history.prices) < 2:
            return True

        is_tripped = self.tripped.get(token_id, False)

        if is_tripped:
            return self._check_recovery(token_id, history)
        else:
            return self._check_trip(token_id, history)

    def _check_trip(self, token_id: str, history: PriceHistory) -> bool:
        """Check if we should trip the circuit breaker."""
        change = history.price_change_pct(self.check_window)

        if change is not None and change > self.max_change_pct:
            self.tripped[token_id] = True
            self.trip_time[token_id] = time.time()
            logger.warning(
                "CIRCUIT BREAKER TRIPPED for %s: %.2f%% change in %ds (limit: %.2f%%)",
                token_id[:12], change, self.check_window, self.max_change_pct,
            )
            return False

        return True

    def _check_recovery(self, token_id: str, history: PriceHistory) -> bool:
        """Check if the market has stabilized enough to resume."""
        vol = history.volatility(self.recovery_window)
        ma = history.moving_average(self.ma_window)

        if vol is not None and vol < self.recovery_threshold:
            self.tripped[token_id] = False
            elapsed = time.time() - self.trip_time.get(token_id, 0)
            logger.info(
                "CIRCUIT BREAKER RECOVERED for %s: volatility=%.6f < %.6f "
                "(MA=%.4f, tripped for %.0fs)",
                token_id[:12], vol, self.recovery_threshold,
                ma or 0, elapsed,
            )
            return True

        # Still tripped
        logger.info(
            "Circuit breaker still active for %s: volatility=%.6f (threshold=%.6f), MA=%.4f",
            token_id[:12], vol or 0, self.recovery_threshold, ma or 0,
        )
        return False

    def is_tripped(self, token_id: str) -> bool:
        return self.tripped.get(token_id, False)

    def get_status(self, token_id: str) -> dict:
        history = self.histories.get(token_id)
        return {
            "tripped": self.is_tripped(token_id),
            "change_pct": history.price_change_pct(self.check_window) if history else None,
            "volatility": history.volatility(self.recovery_window) if history else None,
            "ma": history.moving_average(self.ma_window) if history else None,
            "trip_time": self.trip_time.get(token_id),
        }

    def get_all_status(self) -> str:
        lines = []
        for token_id in self.histories:
            s = self.get_status(token_id)
            status = "TRIPPED" if s["tripped"] else "OK"
            lines.append(
                f"  {token_id[:12]}: {status} "
                f"(change={s['change_pct']:.2f}% vol={s['volatility']:.6f} ma={s['ma']:.4f})"
                if s["change_pct"] is not None
                else f"  {token_id[:12]}: {status} (no data)"
            )
        return "\n".join(lines) if lines else "No markets tracked."
