import asyncio
import os
from threading import Thread

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.logger import setup_logger

logger = setup_logger("telegram")


class TelegramReporter:
    def __init__(self, bot_controller=None):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)
        self.bot_controller = bot_controller
        self._bot: Bot | None = None
        self._app: Application | None = None
        self._thread: Thread | None = None

        if self.enabled:
            self._bot = Bot(token=self.token)
        else:
            logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")

    def start_command_listener(self):
        """Start listening for Telegram commands in a background thread."""
        if not self.enabled:
            return

        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("markets", self._cmd_markets))
        self._app.add_handler(CommandHandler("pause", self._cmd_pause))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))
        self._app.add_handler(CommandHandler("stop", self._cmd_stop))

        self._thread = Thread(target=self._run_polling, daemon=True)
        self._thread.start()
        logger.info("Telegram command listener started")

    def _run_polling(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._app.initialize())
        loop.run_until_complete(self._app.start())
        loop.run_until_complete(self._app.updater.start_polling())
        loop.run_forever()

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_controller:
            status = self.bot_controller.get_status()
            await update.message.reply_text(f"📊 Status:\n{status}")
        else:
            await update.message.reply_text("Bot running, no status available.")

    async def _cmd_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_controller:
            markets = self.bot_controller.get_markets_info()
            await update.message.reply_text(f"📈 Markets:\n{markets}")
        else:
            await update.message.reply_text("No market info available.")

    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_controller:
            self.bot_controller.pause()
            await update.message.reply_text("⏸ Bot paused. Orders cancelled.")
        else:
            await update.message.reply_text("Cannot pause: no controller.")

    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_controller:
            self.bot_controller.resume()
            await update.message.reply_text("▶️ Bot resumed.")
        else:
            await update.message.reply_text("Cannot resume: no controller.")

    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_controller:
            await update.message.reply_text("🛑 Stopping bot...")
            self.bot_controller.stop()
        else:
            await update.message.reply_text("Cannot stop: no controller.")

    def send(self, message: str):
        """Send a message to the configured Telegram chat."""
        if not self.enabled:
            logger.info("[TELEGRAM DISABLED] %s", message)
            return

        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown",
            ))
            loop.close()
        except Exception as e:
            logger.error("Failed to send Telegram message: %s", e)

    def notify_started(self):
        self.send("🟢 *Polymarket Liquidity Bot started*")

    def notify_stopped(self):
        self.send("🔴 *Polymarket Liquidity Bot stopped*")

    def notify_fill(self, side: str, price: float, size: float, market: str):
        emoji = "📗" if side == "BUY" else "📕"
        self.send(
            f"{emoji} *Fill*: {side} {size:.2f} @ ${price:.4f}\n"
            f"Market: {market[:60]}"
        )

    def notify_pnl(self, summary: str):
        self.send(f"💰 *P&L Report*\n```\n{summary}\n```")

    def notify_risk_alert(self, message: str):
        self.send(f"⚠️ *Risk Alert*\n{message}")

    def notify_error(self, error: str):
        self.send(f"🚨 *Error*\n`{error[:500]}`")
