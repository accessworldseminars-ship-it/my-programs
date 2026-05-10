import os
import sys
import traceback
import zipfile
import boto3
import requests
from flask import Flask, request
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===", flush=True)
print(f"Python: {sys.version}", flush=True)

try:
    # ============================================
    # ENVIRONMENT VARIABLES
    # ============================================
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
    R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
    ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
    BUCKET_NAME = os.environ.get('BUCKET_NAME', 'joshua-bot-brain')
    RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')

    print("✅ Environment variables loaded", flush=True)

    # ============================================
    # DOWNLOAD BRAIN
    # ============================================
    def download_brain():
        print("📥 Attempting to download brain...", flush=True)
        if os.path.exists('./bot_brain/chroma.sqlite3'):
            print("✅ Brain already exists", flush=True)
            return True
        # ... (keep your download function, but add prints)
        try:
            s3 = boto3.client(...)
            # ... rest of download
            print("✅ Brain downloaded and extracted", flush=True)
            return True
        except Exception as e:
            print(f"❌ Download error: {e}", flush=True)
            return False

    # ============================================
    # LOAD BRAIN
    # ============================================
    collection = None
    print("\n📚 Loading brain...", flush=True)
    if download_brain():
        try:
            import chromadb
            print(f"✅ ChromaDB: {chromadb.__version__}", flush=True)
            client = chromadb.PersistentClient(path="./bot_brain")
            collection = client.get_collection("my_brain")
            count = collection.count()
            print(f"✅ Brain loaded with {count} chunks", flush=True)
        except Exception as e:
            print(f"❌ Brain load failed: {e}", flush=True)
            traceback.print_exc()
            collection = None

    print(f"Brain status: {'LOADED' if collection else 'FALLBACK'}", flush=True)

    # ============================================
    # AI CLASS + HANDLERS (must be defined here)
    # ============================================
    class CloudflareTwin:
        # ... your class

    twin = CloudflareTwin()

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Hey, it's Josh. What's on your mind?")

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        response = twin.respond(update.message.text)
        await update.message.reply_text(response[:4000])

    # ============================================
    # FLASK
    # ============================================
    flask_app = Flask(__name__)

    @flask_app.route('/')
    @flask_app.route('/health')
    def health():
        return "OK", 200

    print("✅ Flask app created", flush=True)

except Exception as e:
    print(f"❌ CRITICAL ERROR during startup: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("\n🚀 Entering main()...", flush=True)
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        if RENDER_URL:
            webhook_url = f"{RENDER_URL.rstrip('/')}/webhook/{TELEGRAM_TOKEN}"
            app.bot.set_webhook(webhook_url, drop_pending_updates=True)
            print(f"✅ Webhook set", flush=True)

        port = int(os.environ.get("PORT", 8080))
        print(f"✅ Starting Flask on port {port}", flush=True)
        flask_app.run(host='0.0.0.0', port=port)
    except Exception as e:
        print(f"FATAL ERROR in main: {e}", flush=True)
        traceback.print_exc()
