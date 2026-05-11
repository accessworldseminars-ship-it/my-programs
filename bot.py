import os
import sys
import traceback
import zipfile
import boto3
import requests
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===", flush=True)

# ============================================
# ENVIRONMENT VARIABLES
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'joshua-bot-brain')

print(f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Cloudflare: {'✅' if CLOUDFLARE_API_TOKEN else '❌'}", flush=True)
print(f"Account ID: {'✅' if ACCOUNT_ID else '❌'}", flush=True)

# ============================================
# DOWNLOAD + EXTRACT BRAIN
# ============================================
def download_and_extract_brain():
    # Check if brain already exists (files in current directory)
    if os.path.exists('./chroma.sqlite3'):
        print("✅ Brain already exists locally (chroma.sqlite3 found)")
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

        # Clean old files if they exist
        if os.path.exists('./chroma.sqlite3'):
            os.remove('./chroma.sqlite3')
        
        print("📦 Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall('./')  # Extract to current directory
        
        print("✅ Extraction complete")
        
        # Verify extraction
        if os.path.exists('./chroma.sqlite3'):
            print("✅ Brain extracted successfully (chroma.sqlite3 found)")
            return True
        else:
            print("❌ chroma.sqlite3 not found after extraction")
            return False
            
    except Exception as e:
        print(f"❌ Download/extract error: {e}")
        traceback.print_exc()
        return False

# ============================================
# LOAD BRAIN
# ============================================
collection = None

print("\n📚 Loading brain...")
if download_and_extract_brain():
    try:
        import chromadb
        print(f"✅ ChromaDB imported")
        
        # Connect to current directory (where chroma.sqlite3 is)
        client = chromadb.PersistentClient(path=".")
        print("✅ ChromaDB client created")
        
        # List all collections
        collections = client.list_collections()
        print(f"Available collections: {[c.name for c in collections]}")
        
        if collections:
            # Use the first collection found
            collection = client.get_collection(collections[0].name)
            count = collection.count()
            print(f"✅ Brain loaded! {count:,} chunks from '{collections[0].name}'")
        else:
            print("❌ No collections found in brain")
            collection = None
            
    except Exception as e:
        print(f"❌ Brain load error: {e}")
        traceback.print_exc()
        collection = None
else:
    print("⚠️ Could not download/extract brain")

if collection is None:
    print("⚠️ FALLBACK MODE - no brain loaded")

# ============================================
# CLOUDFLARE AI TWIN
# ============================================
class CloudflareTwin:
    def __init__(self):
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"

    def respond(self, message: str):
        context = ""
        if collection:
            try:
                results = collection.query(query_texts=[message], n_results=3)
                if results and results.get('documents') and len(results['documents'][0]) > 0:
                    context = "\n\n".join(results['documents'][0])
                    print(f"📚 Found {len(results['documents'][0])} relevant chunks", flush=True)
                else:
                    print("📚 No relevant chunks found", flush=True)
            except Exception as e:
                print(f"Search error: {e}", flush=True)

        # Build prompt based on whether context was found
        if context:
            prompt = f"""You are Joshua Roy. Answer based ONLY on the seminar content below. Be concise (1-3 sentences).

SEMINAR CONTENT:
{context[:1000]}

USER: {message}

JOSHUA:"""
        else:
            prompt = f"""You are Joshua Roy. Be honest - you don't have seminar content about this specific topic yet.

USER: {message}

JOSHUA:"""

        try:
            resp = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                json={"prompt": prompt, "max_tokens": 300, "temperature": 0.7},
                timeout=20
            )
            if resp.status_code == 200:
                response = resp.json()["result"]["response"]
                print(f"🤖 AI responded ({len(response)} chars)", flush=True)
                return response
            else:
                print(f"Cloudflare error: {resp.status_code}", flush=True)
                return "I'm here. What's on your mind?"
        except Exception as e:
            print(f"AI error: {e}", flush=True)
            return "Tell me more about that."

twin = CloudflareTwin()

# ============================================
# TELEGRAM HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    print(f"📨 Received: {user_message[:100]}", flush=True)
    response = twin.respond(user_message)
    await update.message.reply_text(response[:4000])
    print("✅ Replied", flush=True)

# ============================================
# FLASK HEALTH CHECK
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "Bot is alive ✅", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False)

# ============================================
# MAIN - POLLING MODE
# ============================================
if __name__ == "__main__":
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start Flask health check in background
    threading.Thread(target=run_flask, daemon=True).start()

    print("\n🚀 Starting bot with Cloudflare AI...", flush=True)
    print(f"📊 Brain status: {'LOADED' if collection else 'FALLBACK MODE'}", flush=True)
    
    # Start polling
    app.run_polling(drop_pending_updates=True)
