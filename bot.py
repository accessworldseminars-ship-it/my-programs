import os
import sys
import traceback
import threading
import zipfile
import boto3
import requests
import time
from flask import Flask, request
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===", flush=True)
print(f"Python: {sys.version}", flush=True)

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

print(f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}")
print(f"R2: {'✅' if R2_ACCESS_KEY else '❌'}")
print(f"Cloudflare: {'✅' if CLOUDFLARE_API_TOKEN else '❌'}")

# ============================================
# DOWNLOAD BRAIN FROM R2
# ============================================
def download_brain():
    if os.path.exists('./bot_brain/chroma.sqlite3'):
        print("✅ Brain already exists")
        return True
    
    print("📥 Downloading brain from R2...")
    try:
        s3 = boto3.client(
            's3',
            endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name='auto'
        )
        s3.download_file(BUCKET_NAME, 'bot_brain.zip', '/tmp/brain.zip')
        print("✅ Downloaded")

        # Clean old extraction
        if os.path.exists('./bot_brain'):
            import shutil
            shutil.rmtree('./bot_brain')

        with zipfile.ZipFile('/tmp/brain.zip', 'r') as zip_ref:
            zip_ref.extractall('./')
        print("✅ Extracted")
        return True
    except Exception as e:
        print(f"❌ Download failed: {e}")
        traceback.print_exc()
        return False

# ============================================
# LOAD BRAIN
# ============================================
collection = None
print("\n📚 Loading brain...")

if download_brain():
    try:
        import chromadb
        print(f"✅ ChromaDB version: {chromadb.__version__}")
        
        client = chromadb.PersistentClient(path="./bot_brain")
        collection = client.get_collection("my_brain")
        
        # Safer count (avoids the 'int has no len()' error)
        try:
            count = collection.count()
        except:
            data = collection.get(limit=1)
            count = len(data['ids']) if data and 'ids' in data else "unknown"
        
        print(f"✅ Brain loaded! {count:,} chunks")
        
    except Exception as e:
        print(f"❌ Brain error: {e}")
        traceback.print_exc()
        collection = None

if collection is None:
    print("⚠️ FALLBACK MODE - no brain")

# ============================================
# AI RESPONSE ENGINE
# ============================================
class CloudflareTwin:
    def __init__(self):
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"

    def respond(self, message):
        context = ""
        if collection:
            try:
                results = collection.query(query_texts=[message], n_results=3)
                if results and results['documents']:
                    context = "\n".join(results['documents'][0])
            except Exception as e:
                print(f"Search error: {e}")

        prompt = f"""You are Joshua Roy. Be very concise. 1-2 sentences max.
Context from seminars: {context[:600]}
User: {message}
Joshua:"""

        try:
            resp = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                json={"prompt": prompt, "max_tokens": 180, "temperature": 0.65},
                timeout=20
            )
            if resp.status_code == 200:
                return resp.json()['result']['response']
            return "I'm here. What's on your mind?"
        except:
            return "Interesting point. Tell me more."

twin = CloudflareTwin()

# ============================================
# TELEGRAM + FLASK
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "OK", 200

# Webhook route
@flask_app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), app.bot)
        app.process_update(update)
    except:
        pass
    return "OK", 200

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("\n🚀 Starting Joshua AI Twin...")
    
    # Build Application
    global app
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Set webhook
    if RENDER_URL:
        webhook_url = f"{RENDER_URL}/webhook/{TELEGRAM_TOKEN}"
        try:
            app.bot.set_webhook(webhook_url, drop_pending_updates=True)
            print(f"✅ Webhook set: {webhook_url}")
        except Exception as e:
            print(f"Webhook warning: {e}")
    
    port = int(os.environ.get("PORT", 8080))
    print(f"📊 Brain: {'LOADED' if collection else 'FALLBACK'}")
    print(f"✅ Bot live on port {port}")
    
    flask_app.run(host='0.0.0.0', port=port)
