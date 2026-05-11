# ============================================
# FLASK + WEBHOOK (No polling)
# ============================================
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, filters
import asyncio

# Create Flask app
flask_app = Flask(__name__)

# Setup bot and dispatcher
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

# Add handlers
async def start(update: Update, context):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update: Update, context):
    response = twin.respond(update.message.text)
    await update.message.reply_text(response[:4000])

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@flask_app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, bot)
        dispatcher.process_update(update)
        return "OK", 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return "OK", 200

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "Bot is alive ✅", 200

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    # Set webhook
    webhook_url = f"{RENDER_URL}/webhook/{TELEGRAM_TOKEN}"
    try:
        asyncio.run(bot.set_webhook(webhook_url, drop_pending_updates=True))
        print(f"✅ Webhook set to: {webhook_url}")
    except Exception as e:
        print(f"Webhook error: {e}")
    
    print(f"📊 Brain: {collection.count():,} chunks | AI: Cloudflare")
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
