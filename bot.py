import os
import logging
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import asyncio

# Konfiguration aus Umgebungsvariablen (kein hartkodiertes Token!)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set. Please set it in your environment (e.g. via .env).")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret123")
PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "0.0.0.0")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Logging konfigurieren
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL)
)
logger = logging.getLogger(__name__)

# FastAPI App
app = FastAPI(title="Telegram Bot API", version="1.0.0")

# create Application here
application = Application.builder().token(TELEGRAM_TOKEN).build()

# register handlers (handlers.py must exist)
try:
    from handlers import (
        start_command,
        handle_message,
        button_callback,
        help_command,
        status_command
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
except Exception as e:
    logger.exception(f"Failed to register handlers: {e}")
    raise

async def setup_webhook(application: Application):
    if WEBHOOK_URL:
        try:
            webhook_url = f"{WEBHOOK_URL}/webhook/{WEBHOOK_SECRET}"
            await application.bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook eingerichtet: {webhook_url}")
        except Exception as e:
            logger.error(f"Fehler beim Einrichten des Webhooks: {e}")
    else:
        logger.info("Kein WEBHOOK_URL gesetzt - Polling wird verwendet")

@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook_handler(request: Request):
    try:
        update_data = await request.json()
        update = Update.de_json(update_data, application.bot)
        await application.process_update(update)
        return Response(content="OK", status_code=200)
    except Exception as e:
        logger.exception(f"Fehler im Webhook: {e}")
        return Response(content="Error", status_code=500)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "webhook_configured": bool(WEBHOOK_URL),
    }

@app.on_event("startup")
async def startup_event():
    logger.info("Starting application...")
    await application.initialize()
    await application.start()
    if WEBHOOK_URL:
        await setup_webhook(application)
    else:
        try:
            # ensure webhook deleted so polling works (best-effort)
            await application.bot.delete_webhook()
            logger.info("Webhook gelöscht (Polling aktiv).")
        except Exception:
            logger.debug("Webhook löschen fehlgeschlagen (kann ignoriert werden).")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Stopping application...")
    try:
        await application.stop()
        await application.shutdown()
    except Exception as e:
        logger.exception(f"Fehler beim Stoppen des Bots: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
