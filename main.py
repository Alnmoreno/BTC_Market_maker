import os
import signal
import time
import traceback

import yaml
from dotenv import load_dotenv

from src.circuit_breaker import CircuitBreaker
from src.client import PolymarketClient
from src.inventory_manager import InventoryManager
from src.market_selector import select_markets
from src.order_manager import OrderManager
from src.pricing_engine import calculate_mid_price, calculate_quotes
from src.risk_manager import RiskManager
from src.telegram_bot import TelegramReporter
from src.logger import setup_logger

load_dotenv()
logger = setup_logger("main")


class BotController:
    """Provides control interface for Telegram commands."""

    def __init__(self):
        self.running = True
        self.paused = False
        self.inventory: InventoryManager | None = None
        self.order_manager: OrderManager | None = None
        self.circuit_breaker: CircuitBreaker | None = None
        self.selected_markets: list[dict] = []
        self.client: PolymarketClient | None = None

    def get_status(self) -> str:
        status = "PAUSED" if self.paused else "RUNNING"
        lines = [f"Status: {status}"]

        if self.order_manager:
            lines.append(f"Active orders: {self.order_manager.get_active_count()}")

        if self.circuit_breaker:
            cb_status = self.circuit_breaker.get_all_status()
            lines.append(f"Circuit breaker:\n{cb_status}")

        if self.inventory:
            lines.append(self.inventory.get_summary())

        return "\n".join(lines)

    def get_markets_info(self) -> str:
        if not self.selected_markets:
            return "No markets selected."
        lines = []
        for m in self.selected_markets:
            lines.append(f"- {m['question'][:60]} (vol={m['volume']:.0f})")
        return "\n".join(lines)

    def pause(self):
        self.paused = True
        if self.order_manager:
            self.order_manager.cancel_all()

    def resume(self):
        self.paused = False

    def stop(self):
        self.running = False


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    dry_run = config.get("dry_run", True)

    logger.info("Starting Polymarket Liquidity Bot (dry_run=%s)", dry_run)

    # Initialize components
    controller = BotController()
    telegram = TelegramReporter(bot_controller=controller)

    client = PolymarketClient(config.get("polymarket", {}), dry_run=dry_run)
    inventory = InventoryManager()
    risk_mgr = RiskManager(config.get("risk", {}))
    order_mgr = OrderManager(client)
    circuit_breaker = CircuitBreaker(config.get("circuit_breaker", {}))

    controller.client = client
    controller.inventory = inventory
    controller.order_manager = order_mgr
    controller.circuit_breaker = circuit_breaker

    strategy = config.get("strategy", {})
    spread = strategy.get("spread", 0.04)
    order_size = strategy.get("order_size", 50)
    num_levels = strategy.get("num_levels", 3)
    refresh_interval = strategy.get("refresh_interval", 10)
    skew_factor = strategy.get("skew_factor", 0.5)
    max_position = config.get("risk", {}).get("max_position_per_market", 500)

    pnl_interval = config.get("telegram", {}).get("pnl_interval", 300)

    # Graceful shutdown
    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received")
        controller.running = False

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Start Telegram listener
    telegram.start_command_listener()
    telegram.notify_started()

    # Select markets
    logger.info("Fetching markets...")
    markets = client.get_markets()
    selected = select_markets(markets, config.get("market_selection", {}))
    controller.selected_markets = selected

    if not selected and not dry_run:
        logger.warning("No markets selected. Check config or market conditions.")
        telegram.send("⚠️ No suitable markets found. Bot idle.")

    # If dry run with no markets, create a dummy for demonstration
    if dry_run and not selected:
        selected = [{
            "token_id": "0xDEMO_TOKEN_ID",
            "question": "Demo Market (dry run)",
            "volume": 50000,
            "spread": 0.05,
            "score": 2500,
        }]
        controller.selected_markets = selected
        logger.info("Dry run: using demo market")

    last_pnl_report = time.time()

    # Main loop
    logger.info("Entering main loop (interval=%ds)", refresh_interval)
    while controller.running:
        try:
            if controller.paused:
                time.sleep(refresh_interval)
                continue

            for market_info in selected:
                token_id = market_info["token_id"]
                question = market_info["question"]

                # 1. Fetch orderbook
                book = client.get_orderbook(token_id)
                mid = calculate_mid_price(book)

                if mid is None:
                    # In dry run, use a simulated mid price
                    if dry_run:
                        mid = 0.50
                    else:
                        logger.warning("No mid-price for %s, skipping", question[:40])
                        continue

                # 2. Circuit breaker: check for sudden price moves
                circuit_breaker.record_price(token_id, mid)
                if not circuit_breaker.check(token_id):
                    cb_status = circuit_breaker.get_status(token_id)
                    logger.warning(
                        "Circuit breaker ACTIVE for %s — cancelling orders, waiting for stabilization",
                        question[:40],
                    )
                    order_mgr.cancel_all_for_token(token_id)
                    telegram.notify_risk_alert(
                        f"Circuit breaker for {question[:40]}: "
                        f"price moved {cb_status.get('change_pct', 0):.1f}%\n"
                        f"Monitoring MA until volatility drops below threshold..."
                    )
                    continue

                # 3. Check risk
                inv = inventory.get_inventory(token_id)
                risk_action = risk_mgr.check(token_id, inventory, mid)

                if not risk_action.can_trade:
                    logger.warning("Risk block for %s: %s", question[:40], risk_action.reason)
                    telegram.notify_risk_alert(f"{question[:40]}: {risk_action.reason}")
                    order_mgr.cancel_all_for_token(token_id)
                    continue

                # 3. Calculate quotes with risk adjustments
                effective_spread = spread * risk_action.widen_spread
                effective_size = order_size * risk_action.reduce_size

                quotes = calculate_quotes(
                    mid_price=mid,
                    inventory=inv,
                    spread=effective_spread,
                    order_size=effective_size,
                    num_levels=num_levels,
                    skew_factor=skew_factor,
                    max_position=max_position,
                )

                # 4. Update orders
                order_mgr.update_orders(token_id, quotes)

                if quotes:
                    logger.info(
                        "%s: mid=%.4f inv=%.2f bid=%.4f ask=%.4f spread=%.4f",
                        question[:30], mid, inv,
                        quotes[0].bid_price, quotes[0].ask_price,
                        quotes[0].ask_price - quotes[0].bid_price,
                    )

            # P&L report
            now = time.time()
            if now - last_pnl_report >= pnl_interval:
                summary = inventory.get_summary()
                logger.info(summary)
                telegram.notify_pnl(summary)
                last_pnl_report = now

            time.sleep(refresh_interval)

        except KeyboardInterrupt:
            break
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error("Error in main loop: %s\n%s", error_msg, traceback.format_exc())
            telegram.notify_error(error_msg)
            time.sleep(refresh_interval * 2)

    # Shutdown
    logger.info("Shutting down...")
    order_mgr.cancel_all()
    telegram.notify_stopped()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
