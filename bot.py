import os
import sys
import traceback
import zipfile
import boto3
import requests
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===", flush=True)

# Environment
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GROK_API_KEY = os.environ.get('GROK_API_KEY')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'joshua-bot-brain')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')

print(f"Telegram Token: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)

# Brain Loading (same as before)
collection = None
# ... (keep your download_brain and chromadb loading code here) ...

if download_brain():
    try:
        import chromadb
        client = chromadb.PersistentClient(path="./bot_brain")
        collection = client.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks", flush=True)
    except Exception as e:
        print(f"❌ Brain error: {e}", flush=True)

# GrokTwin (same)
class GrokTwin:
    def __init__(self):
        self.url = "https://api.x.ai/v1/chat/completions"
    def respond(self, message: str):
        # ... your current respond method ...
        # (keep it as is)

twin = GrokTwin()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📨 Received message: {update.message.text}", flush=True)
    response = twin.respond(update.message.text)
    await update.message.reply_text(response[:4000])
    print(f"✅ Replied: {response[:100]}...", flush=True)

# Flask
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "Bot is alive ✅", 200

@flask_app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    print("🚀 Webhook received a POST from Telegram!", flush=True)
    try:
        update_data = request.get_json(force=True)
        print(f"Update data received: {update_data}", flush=True)
        
        update = Update.de_json(update_data, application.bot)
        asyncio.run(application.process_update(update))
        print("✅ Processed update successfully", flush=True)
        return "OK", 200
    except Exception as e:
        print(f"❌ Webhook error: {e}", flush=True)
        traceback.print_exc()
        return "OK", 200

# Main
if __name__ == "__main__":
    global application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if RENDER_URL:
        webhook_url = f"{RENDER_URL.rstrip('/')}/webhook/{TELEGRAM_TOKEN}"
        try:
            asyncio.run(application.bot.set_webhook(webhook_url, drop_pending_updates=True))
            print(f"✅ Webhook set: {webhook_url}", flush=True)
        except Exception as e:
            print(f"Webhook warning: {e}", flush=True)

    print("🚀 Bot started - waiting for messages...", flush=True)
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
