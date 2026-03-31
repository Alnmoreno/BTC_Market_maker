from src.risk_manager import RiskManager
from src.inventory_manager import InventoryManager


def _setup(position_size: float = 0, avg_price: float = 0.5, realized_pnl: float = 0):
    config = {
        "max_position_per_market": 500,
        "max_total_exposure": 5000,
        "max_loss_per_market": 100,
    }
    risk = RiskManager(config)
    inv = InventoryManager()

    if position_size != 0:
        token_id = "test_token"
        inv.positions[token_id] = inv.get_position(token_id)
        inv.positions[token_id].token_id = token_id
        inv.positions[token_id].size = position_size
        inv.positions[token_id].avg_entry_price = avg_price
        inv.positions[token_id].realized_pnl = realized_pnl

    return risk, inv


class TestRiskManager:
    def test_no_position_can_trade(self):
        risk, inv = _setup()
        action = risk.check("test_token", inv)
        assert action.can_trade is True
        assert action.reduce_size == 1.0

    def test_max_loss_blocks_trading(self):
        risk, inv = _setup(position_size=100, realized_pnl=-150)
        action = risk.check("test_token", inv)
        assert action.can_trade is False

    def test_high_position_reduces_size(self):
        risk, inv = _setup(position_size=900, avg_price=0.5)
        # position_value = 900 * 0.5 = 450, ratio = 450/500 = 0.9 > 0.7
        action = risk.check("test_token", inv)
        assert action.can_trade is True
        assert action.reduce_size < 1.0
        assert action.widen_spread > 1.0

    def test_within_limits_normal(self):
        risk, inv = _setup(position_size=100, avg_price=0.5)
        # position_value = 50, well within 500 limit
        action = risk.check("test_token", inv)
        assert action.can_trade is True
        assert action.reduce_size == 1.0
        assert action.widen_spread == 1.0
