from dataclasses import dataclass

from src.inventory_manager import InventoryManager
from src.logger import setup_logger

logger = setup_logger("risk")


@dataclass
class RiskAction:
    can_trade: bool = True
    reduce_size: float = 1.0  # multiplier: 1.0 = normal, 0.5 = half size, 0 = stop
    widen_spread: float = 1.0  # multiplier: 1.0 = normal, 2.0 = double spread
    reason: str = ""


class RiskManager:
    def __init__(self, config: dict):
        self.max_position_per_market = config.get("max_position_per_market", 500)
        self.max_total_exposure = config.get("max_total_exposure", 5000)
        self.max_loss_per_market = config.get("max_loss_per_market", 100)

    def check(self, token_id: str, inventory: InventoryManager, current_price: float = 0.0) -> RiskAction:
        """Check risk limits and return action to take."""
        pos = inventory.get_position(token_id)
        position_value = abs(pos.size * pos.avg_entry_price)
        total_exposure = inventory.get_total_exposure()

        # Check max loss per market
        if pos.realized_pnl < -self.max_loss_per_market:
            logger.warning(
                "RISK: Max loss hit for %s (loss=$%.2f > $%.2f)",
                token_id[:12], abs(pos.realized_pnl), self.max_loss_per_market,
            )
            return RiskAction(
                can_trade=False,
                reduce_size=0.0,
                reason=f"Max loss per market exceeded: ${pos.realized_pnl:.2f}",
            )

        # Check total exposure
        if total_exposure > self.max_total_exposure:
            logger.warning(
                "RISK: Total exposure $%.2f exceeds limit $%.2f",
                total_exposure, self.max_total_exposure,
            )
            return RiskAction(
                can_trade=True,
                reduce_size=0.3,
                widen_spread=2.0,
                reason=f"Total exposure high: ${total_exposure:.0f}/${self.max_total_exposure:.0f}",
            )

        # Check position per market
        if position_value > self.max_position_per_market:
            ratio = self.max_position_per_market / position_value
            logger.warning(
                "RISK: Position $%.2f exceeds limit $%.2f for %s",
                position_value, self.max_position_per_market, token_id[:12],
            )
            return RiskAction(
                can_trade=True,
                reduce_size=ratio * 0.5,
                widen_spread=1.5,
                reason=f"Position limit: ${position_value:.0f}/${self.max_position_per_market:.0f}",
            )

        # Gradual size reduction as we approach limits
        position_ratio = position_value / self.max_position_per_market if self.max_position_per_market > 0 else 0
        exposure_ratio = total_exposure / self.max_total_exposure if self.max_total_exposure > 0 else 0

        size_mult = 1.0
        spread_mult = 1.0

        if position_ratio > 0.7:
            size_mult = 1.0 - (position_ratio - 0.7) / 0.3
            spread_mult = 1.0 + (position_ratio - 0.7)

        if exposure_ratio > 0.7:
            size_mult = min(size_mult, 1.0 - (exposure_ratio - 0.7) / 0.3)
            spread_mult = max(spread_mult, 1.0 + (exposure_ratio - 0.7))

        return RiskAction(
            can_trade=True,
            reduce_size=max(0.1, size_mult),
            widen_spread=min(3.0, spread_mult),
        )
