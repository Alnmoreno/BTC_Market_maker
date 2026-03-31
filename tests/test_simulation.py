"""
Simulation test: $50 order volume, 10 cycles showing how the bot
readjusts quotes, inventory, risk, and circuit breaker through
a realistic sequence of market events.

Run with: python -m pytest tests/test_simulation.py -v -s
"""

from src.pricing_engine import calculate_quotes
from src.inventory_manager import InventoryManager
from src.risk_manager import RiskManager
from src.circuit_breaker import CircuitBreaker


# Shared config
SPREAD = 0.04
ORDER_SIZE = 50.0
NUM_LEVELS = 3
SKEW_FACTOR = 0.5
MAX_POSITION = 500.0

RISK_CONFIG = {
    "max_position_per_market": MAX_POSITION,
    "max_total_exposure": 5000,
    "max_loss_per_market": 100,
}

CB_CONFIG = {
    "max_change_pct": 10.0,
    "check_window_seconds": 60,
    "ma_window_seconds": 300,
    "recovery_volatility_threshold": 0.005,
    "recovery_window_seconds": 120,
}

TOKEN = "0xBTC200K"
MARKET = "BTC hits $200k?"


def _header():
    print()
    print("=" * 110)
    print(
        f"{'Cycle':<6} {'Mid':>6} {'Inv':>7} {'Event':<25} "
        f"{'L0 Bid':>7} {'L0 Ask':>7} {'L0 Size':>7} "
        f"{'L1 Bid':>7} {'L1 Ask':>7} {'L1 Size':>7} "
        f"{'L2 Bid':>7} {'L2 Ask':>7} {'L2 Size':>7}"
    )
    print("-" * 110)


def _row(cycle, mid, inv, event, quotes):
    cols = [f"{cycle:<6} {mid:>6.4f} {inv:>7.1f} {event:<25}"]
    for i in range(3):
        if i < len(quotes):
            q = quotes[i]
            cols.append(f" {q.bid_price:>7.4f} {q.ask_price:>7.4f} {q.bid_size:>7.1f}")
        else:
            cols.append(f" {'---':>7} {'---':>7} {'---':>7}")
    print("".join(cols))


def _status_row(label, value):
    print(f"       {label}: {value}")


class TestSimulation:
    def test_full_simulation_50_dollars(self):
        """
        Simulates 10 cycles with $50 order volume showing:
        - Initial quoting with 3 levels
        - Inventory accumulation and skew adjustment
        - Risk manager scaling down sizes
        - Circuit breaker trip and recovery
        - P&L tracking
        """
        inv_mgr = InventoryManager()
        risk_mgr = RiskManager(RISK_CONFIG)
        cb = CircuitBreaker(CB_CONFIG)

        base_ts = 1000.0  # Simulated timestamp

        print("\n" + "=" * 110)
        print("  POLYMARKET LIQUIDITY BOT SIMULATION — $50 Order Size, 3 Levels")
        print("  Market: 'BTC hits $200k?'  |  Spread: 4c  |  Max Position: $500")
        print("=" * 110)

        _header()

        # ===== CYCLE 1: Normal quoting, no fills =====
        mid = 0.50
        base_ts += 10
        cb.record_price(TOKEN, mid)
        cb.histories[TOKEN].timestamps[-1] = base_ts

        risk = risk_mgr.check(TOKEN, inv_mgr, mid)
        quotes = calculate_quotes(mid, 0, SPREAD * risk.widen_spread, ORDER_SIZE * risk.reduce_size, NUM_LEVELS, SKEW_FACTOR, MAX_POSITION)
        _row(1, mid, 0, "Initial — no fills", quotes)

        assert len(quotes) == 3
        assert quotes[0].bid_size == 50.0
        assert quotes[1].bid_size == 40.0
        assert quotes[2].bid_size == 30.0

        # ===== CYCLE 2: Still no fills =====
        mid = 0.505
        base_ts += 10
        cb.record_price(TOKEN, mid)
        cb.histories[TOKEN].timestamps[-1] = base_ts

        risk = risk_mgr.check(TOKEN, inv_mgr, mid)
        quotes = calculate_quotes(mid, 0, SPREAD * risk.widen_spread, ORDER_SIZE * risk.reduce_size, NUM_LEVELS, SKEW_FACTOR, MAX_POSITION)
        _row(2, mid, 0, "Slight move — no fills", quotes)

        # ===== CYCLE 3: BUY fill — 50 tokens @ 0.48 =====
        inv_mgr.on_fill(TOKEN, "BUY", 0.48, 50, MARKET)
        inv = inv_mgr.get_inventory(TOKEN)
        mid = 0.50
        base_ts += 10
        cb.record_price(TOKEN, mid)
        cb.histories[TOKEN].timestamps[-1] = base_ts

        risk = risk_mgr.check(TOKEN, inv_mgr, mid)
        quotes = calculate_quotes(mid, inv, SPREAD * risk.widen_spread, ORDER_SIZE * risk.reduce_size, NUM_LEVELS, SKEW_FACTOR, MAX_POSITION)
        _row(3, mid, inv, "BUY 50 @ 0.48", quotes)
        _status_row("Skew effect", f"Inv ratio={inv/MAX_POSITION:.2f} → prices shifted DOWN to encourage selling")

        assert quotes[0].bid_price < 0.48  # Bid shifted down
        assert quotes[0].ask_price < 0.52  # Ask shifted down too

        # ===== CYCLE 4: Another BUY fill — 40 tokens @ 0.46 =====
        inv_mgr.on_fill(TOKEN, "BUY", 0.46, 40, MARKET)
        inv = inv_mgr.get_inventory(TOKEN)
        mid = 0.49
        base_ts += 10
        cb.record_price(TOKEN, mid)
        cb.histories[TOKEN].timestamps[-1] = base_ts

        risk = risk_mgr.check(TOKEN, inv_mgr, mid)
        eff_spread = SPREAD * risk.widen_spread
        eff_size = ORDER_SIZE * risk.reduce_size
        quotes = calculate_quotes(mid, inv, eff_spread, eff_size, NUM_LEVELS, SKEW_FACTOR, MAX_POSITION)
        _row(4, mid, inv, "BUY 40 @ 0.46", quotes)
        _status_row("Risk adj", f"reduce_size={risk.reduce_size:.2f}, widen_spread={risk.widen_spread:.2f}")
        _status_row("Eff size", f"L0=${eff_size:.1f}, L1=${eff_size*0.8:.1f}, L2=${eff_size*0.6:.1f}")

        # ===== CYCLE 5: SELL fill — 30 tokens @ 0.51 (partial unwind) =====
        inv_mgr.on_fill(TOKEN, "SELL", 0.51, 30, MARKET)
        inv = inv_mgr.get_inventory(TOKEN)
        mid = 0.50
        base_ts += 10
        cb.record_price(TOKEN, mid)
        cb.histories[TOKEN].timestamps[-1] = base_ts

        risk = risk_mgr.check(TOKEN, inv_mgr, mid)
        quotes = calculate_quotes(mid, inv, SPREAD * risk.widen_spread, ORDER_SIZE * risk.reduce_size, NUM_LEVELS, SKEW_FACTOR, MAX_POSITION)
        pos = inv_mgr.get_position(TOKEN)
        _row(5, mid, inv, "SELL 30 @ 0.51", quotes)
        _status_row("P&L", f"Realized=${pos.realized_pnl:.2f}, Unrealized=${inv_mgr.get_unrealized_pnl(TOKEN, mid):.2f}")

        assert pos.realized_pnl > 0  # Sold higher than avg entry

        # ===== CYCLE 6: Price jump to 0.58 — circuit breaker trips =====
        mid = 0.58
        base_ts += 10
        cb.record_price(TOKEN, mid)
        cb.histories[TOKEN].timestamps[-1] = base_ts

        safe = cb.check(TOKEN)
        _row(6, mid, inv, "PRICE JUMP +16%", [])
        _status_row("Circuit breaker", f"TRIPPED! safe={safe}, change={cb.get_status(TOKEN)['change_pct']:.1f}%")
        _status_row("Action", "ALL ORDERS CANCELLED — waiting for stabilization")

        assert safe is False
        assert cb.is_tripped(TOKEN)

        # ===== CYCLE 7: Price still volatile =====
        mid = 0.56
        base_ts += 10
        cb.record_price(TOKEN, mid)
        cb.histories[TOKEN].timestamps[-1] = base_ts

        safe = cb.check(TOKEN)
        _row(7, mid, inv, "Still volatile", [])
        _status_row("Circuit breaker", f"Still tripped, vol={cb.get_status(TOKEN)['volatility']:.6f}")

        assert safe is False

        # ===== CYCLE 8: Starting to stabilize =====
        mid = 0.57
        base_ts += 30
        cb.record_price(TOKEN, mid)
        cb.histories[TOKEN].timestamps[-1] = base_ts

        safe = cb.check(TOKEN)
        _row(8, mid, inv, "Stabilizing...", [])
        _status_row("Circuit breaker", f"Tripped={cb.is_tripped(TOKEN)}, MA={cb.get_status(TOKEN)['ma']:.4f}")

        # ===== CYCLE 9: More stable data points =====
        # Add many stable prices to push old volatile ones out of recovery window
        for i in range(15):
            base_ts += 10
            cb.record_price(TOKEN, 0.57)
            cb.histories[TOKEN].timestamps[-1] = base_ts

        safe = cb.check(TOKEN)
        _row(9, 0.57, inv, "Stable period", [])
        _status_row("Circuit breaker", f"Tripped={cb.is_tripped(TOKEN)}, vol={cb.get_status(TOKEN)['volatility']:.6f}")

        # ===== CYCLE 10: Recovery — quoting resumes =====
        # Push timestamps far enough that recovery_window only sees stable prices
        base_ts += 200
        for i in range(10):
            cb.record_price(TOKEN, 0.57)
            cb.histories[TOKEN].timestamps[-1] = base_ts + i

        safe = cb.check(TOKEN)
        mid = 0.57

        if safe:
            risk = risk_mgr.check(TOKEN, inv_mgr, mid)
            quotes = calculate_quotes(mid, inv, SPREAD * risk.widen_spread, ORDER_SIZE * risk.reduce_size, NUM_LEVELS, SKEW_FACTOR, MAX_POSITION)
            _row(10, mid, inv, "RECOVERED — quoting", quotes)
            _status_row("Circuit breaker", "RECOVERED! Resuming normal operations")
        else:
            _row(10, mid, inv, "Still recovering...", [])
            _status_row("Circuit breaker", f"Still tripped, vol={cb.get_status(TOKEN)['volatility']:.6f}")

        # ===== FINAL SUMMARY =====
        pos = inv_mgr.get_position(TOKEN)
        upnl = inv_mgr.get_unrealized_pnl(TOKEN, mid)

        print()
        print("=" * 110)
        print("  FINAL SUMMARY")
        print("-" * 110)
        print(f"  Position: {pos.size:.0f} tokens @ avg ${pos.avg_entry_price:.4f}")
        print(f"  Current mid: ${mid:.4f}")
        print(f"  Realized P&L: ${pos.realized_pnl:.2f}")
        print(f"  Unrealized P&L: ${upnl:.2f}")
        print(f"  Total P&L: ${pos.realized_pnl + upnl:.2f}")
        print(f"  Total bought: ${pos.total_bought:.2f}")
        print(f"  Total sold: ${pos.total_sold:.2f}")
        print(f"  Exposure: ${inv_mgr.get_total_exposure():.2f}")
        print("=" * 110)

        # Verify final state
        assert pos.size == 60  # 50 + 40 - 30
        assert pos.realized_pnl > 0
