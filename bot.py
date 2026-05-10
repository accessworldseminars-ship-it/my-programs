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

# ============================================
# DOWNLOAD BRAIN
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
        
        count = collection.count()
        print(f"✅ Brain loaded! {count:,} chunks")
    except Exception as e:
        print(f"❌ Brain error: {e}")
        traceback.print_exc()
        collection = None

if collection is None:
    print("⚠️ FALLBACK MODE - no brain")

# ============================================
# AI TWIN
# ============================================
class CloudflareTwin:
    def __init__(self):
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"

    def respond(self, message):
        context = ""
        if collection:
            try:
                results = collection.query(query_texts=[message], n_results=2)
                if results['documents']:
                    context = "\n".join(results['documents'][0])
            except:
                pass

        prompt = f"""You are Joshua Roy. Be concise (1-2 sentences).
Context: {context[:500]}
User: {message}
Joshua:"""
        try:
            resp = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                json={"prompt": prompt, "max_tokens": 150},
                timeout=20
            )
            return resp.json()['result']['response'] if resp.status_code == 200 else "I'm here. What's on your mind?"
        except:
            return "Good question. Tell me more."

twin = CloudflareTwin()

# ============================================
# HANDLERS (defined BEFORE use)
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = twin.respond(update.message.text)
    await update.message.reply_text(response[:4000])

# ============================================
# FLASK APP
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "OK", 200

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("\n🚀 Starting Joshua AI Twin...")

    # Create Application
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Set webhook
    if RENDER_URL:
        webhook_url = f"{RENDER_URL.rstrip('/')}/webhook/{TELEGRAM_TOKEN}"
        try:
            app.bot.set_webhook(webhook_url, drop_pending_updates=True)
            print(f"✅ Webhook set to: {webhook_url}")
        except Exception as e:
            print(f"Webhook error: {e}")

    print(f"📊 Brain status: {'LOADED' if collection else 'FALLBACK'}")

    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
