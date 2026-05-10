import os
import sys
import traceback
import threading
import zipfile
import boto3
import requests
import httpx
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===")
print(f"Python version: {sys.version}")

# ============================================
# ENVIRONMENT VARIABLES
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
BUCKET_NAME = "joshua-bot-brain"

print(f"R2 Bucket: {BUCKET_NAME}")
print(f"Account ID: {ACCOUNT_ID[:10]}..." if ACCOUNT_ID else "Account ID: MISSING")
print(f"Telegram Token: {'SET' if TELEGRAM_TOKEN else 'MISSING'}")

# ============================================
# DOWNLOAD + EXTRACT BRAIN
# ============================================
def download_and_extract_brain():
    if os.path.exists('./bot_brain') and os.path.exists('./bot_brain/chroma.sqlite3'):
        print("✅ Brain already exists locally")
        return True

    print("📥 Downloading bot_brain.zip from Cloudflare R2...")
    try:
        s3 = boto3.client(
            's3',
            endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name='auto'
        )

        zip_path = '/tmp/bot_brain.zip'
        s3.download_file(BUCKET_NAME, 'bot_brain.zip', zip_path)
        size_mb = os.path.getsize(zip_path) / 1024 / 1024
        print(f"✅ Downloaded {size_mb:.1f} MB")

        # Clean previous extraction
        if os.path.exists('./bot_brain'):
            import shutil
            shutil.rmtree('./bot_brain')

        print("📦 Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall('./')

        print("✅ Extraction complete")
        return os.path.exists('./bot_brain/chroma.sqlite3')

    except Exception as e:
        print(f"❌ Download/extract error: {e}")
        traceback.print_exc()
        return False

# ============================================
# LOAD BRAIN
# ============================================
collection = None
brain_loaded = False

print("\n📚 Loading brain...")
brain_loaded = download_and_extract_brain()

if brain_loaded:
    try:
        import chromadb
        print(f"✅ ChromaDB imported: {chromadb.__version__}")

        client = chromadb.PersistentClient(path="./bot_brain")
        print("✅ ChromaDB client created")

        collections = client.list_collections()
        print(f"Available collections: {[c.name for c in collections]}")

        collection = client.get_collection("my_brain")
        count = collection.count()
        print(f"✅ Brain loaded successfully! {count:,} chunks")
    except Exception as e:
        print(f"❌ Failed to load ChromaDB: {e}")
        traceback.print_exc()
        collection = None
else:
    print("⚠️ Using FALLBACK MODE (no brain)")

# ============================================
# PERSONALITY + TWIN CLASS
# ============================================
PERSONALITY = """You are Joshua Roy. Be CONCISE. 1-3 sentences max. Short answers. Ask questions back."""

class CloudflareTwin:
    def __init__(self):
        self.model = "@cf/meta/llama-3.1-8b-instruct"
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{self.model}"

    def search_brain(self, query):
        if collection is None:
            return ""
        try:
            results = collection.query(query_texts=[query], n_results=3)
            return "\n".join(results['documents'][0]) if results['documents'] else ""
        except Exception as e:
            print(f"Search error: {e}")
            return ""

    def respond(self, user_message):
        context = self.search_brain(user_message)
        prompt = f"""{PERSONALITY}
Context: {context}
User: {user_message}
Response:"""

        try:
            resp = requests.post(
                self.base_url,
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                json={"prompt": prompt, "max_tokens": 250, "temperature": 0.7},
                timeout=25
            )
            if resp.status_code == 200:
                return resp.json()["result"]["response"]
            return f"AI Error {resp.status_code}"
        except Exception as e:
            return f"Error: {str(e)[:80]}"

twin = CloudflareTwin()

# ============================================
# TELEGRAM HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = twin.respond(update.message.text)
    await update.message.reply_text(response[:4000])

# ============================================
# FLASK HEALTH CHECK
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health_check():
    return "✅ Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False)

# ============================================
# MAIN
# ============================================
def main():
    print("\n🚀 Starting Joshua's AI Twin...")
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ Health check server running")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.bot._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running on Render with Cloudflare AI!")
    print(f"📊 Brain status: {'LOADED' if collection else 'FALLBACK MODE'}")

    app.run_polling()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
