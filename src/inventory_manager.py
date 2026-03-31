from dataclasses import dataclass, field

from src.logger import setup_logger

logger = setup_logger("inventory")


@dataclass
class Position:
    token_id: str
    question: str
    size: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    total_bought: float = 0.0
    total_sold: float = 0.0


class InventoryManager:
    def __init__(self):
        self.positions: dict[str, Position] = {}
        self.total_realized_pnl: float = 0.0

    def get_position(self, token_id: str) -> Position:
        return self.positions.get(token_id, Position(token_id=token_id, question=""))

    def get_inventory(self, token_id: str) -> float:
        """Return current position size (positive = long, negative = short)."""
        pos = self.positions.get(token_id)
        return pos.size if pos else 0.0

    def get_total_exposure(self) -> float:
        """Total absolute exposure across all markets."""
        return sum(abs(p.size * p.avg_entry_price) for p in self.positions.values())

    def on_fill(self, token_id: str, side: str, price: float, size: float, question: str = ""):
        """Update position after an order fill."""
        if token_id not in self.positions:
            self.positions[token_id] = Position(token_id=token_id, question=question)

        pos = self.positions[token_id]

        if side == "BUY":
            # Buying: increase position
            total_cost = pos.avg_entry_price * pos.size + price * size
            pos.size += size
            pos.avg_entry_price = total_cost / pos.size if pos.size > 0 else price
            pos.total_bought += size * price
        else:
            # Selling: decrease position, realize P&L
            if pos.size > 0:
                pnl = (price - pos.avg_entry_price) * min(size, pos.size)
                pos.realized_pnl += pnl
                self.total_realized_pnl += pnl
            pos.size -= size
            pos.total_sold += size * price

        logger.info(
            "Fill: %s %s %.2f @ %.4f | pos=%.2f avg=%.4f rpnl=%.4f | %s",
            side, token_id[:12], size, price,
            pos.size, pos.avg_entry_price, pos.realized_pnl,
            question[:40],
        )

    def get_unrealized_pnl(self, token_id: str, current_price: float) -> float:
        pos = self.positions.get(token_id)
        if not pos or pos.size == 0:
            return 0.0
        return (current_price - pos.avg_entry_price) * pos.size

    def get_total_unrealized_pnl(self, prices: dict[str, float]) -> float:
        total = 0.0
        for token_id, pos in self.positions.items():
            if token_id in prices and pos.size != 0:
                total += (prices[token_id] - pos.avg_entry_price) * pos.size
        return total

    def get_summary(self, prices: dict[str, float] | None = None) -> str:
        lines = ["=== Inventory Summary ==="]
        prices = prices or {}

        for token_id, pos in self.positions.items():
            upnl = self.get_unrealized_pnl(token_id, prices.get(token_id, pos.avg_entry_price))
            lines.append(
                f"  {pos.question[:40]}: size={pos.size:.2f} avg={pos.avg_entry_price:.4f} "
                f"rpnl=${pos.realized_pnl:.2f} upnl=${upnl:.2f}"
            )

        total_upnl = self.get_total_unrealized_pnl(prices)
        lines.append(f"  Total realized P&L: ${self.total_realized_pnl:.2f}")
        lines.append(f"  Total unrealized P&L: ${total_upnl:.2f}")
        lines.append(f"  Total P&L: ${self.total_realized_pnl + total_upnl:.2f}")

        return "\n".join(lines)
