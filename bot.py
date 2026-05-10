import os
import sys
import traceback
import threading
import zipfile
import boto3
import requests
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===")
print(f"Python version: {sys.version}")

# ============================================
# ENVIRONMENT VARIABLES (set in Render)
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
BUCKET_NAME = "joshua-bot-brain"

print(f"R2 Bucket: {BUCKET_NAME}")
print(f"Account ID: {ACCOUNT_ID[:10]}..." if ACCOUNT_ID else "Account ID: MISSING")

# ============================================
# DOWNLOAD AND EXTRACT BRAIN
# ============================================
def download_and_extract_brain():
    """Downloads bot_brain.zip from Cloudflare R2 and extracts it"""
    
    if os.path.exists('./bot_brain') and os.path.exists('./bot_brain/chroma.sqlite3'):
        print("✅ Brain already exists")
        return True
    
    print("📥 Downloading bot_brain.zip from Cloudflare R2...")
    
    try:
        # Create R2 client
        s3 = boto3.client(
            's3',
            endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name='auto'
        )
        
        # Download zip
        zip_path = '/tmp/bot_brain.zip'
        s3.download_file(BUCKET_NAME, 'bot_brain.zip', zip_path)
        
        size_mb = os.path.getsize(zip_path) / 1024 / 1024
        print(f"✅ Downloaded {size_mb:.1f} MB")
        
        # Extract
        print("📦 Extracting brain...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall('./')
        
        # Verify extraction
        if os.path.exists('./bot_brain') and os.path.exists('./bot_brain/chroma.sqlite3'):
            print("✅ Extraction complete")
            return True
        else:
            print("❌ Extraction failed: Expected './bot_brain/chroma.sqlite3' not found")
            return False
            
    except Exception as e:
        print(f"❌ Download/extract error: {e}")
        return False

# ============================================
# LOAD CHROMADB BRAIN
# ============================================
print("\n📚 Loading brain database...")

brain_loaded = download_and_extract_brain()
collection = None

if brain_loaded:
    try:
        import chromadb
        brain_db = chromadb.PersistentClient(path="./bot_brain")
        collection = brain_db.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks")
    except Exception as e:
        print(f"❌ Failed to load ChromaDB collection: {e}")
        collection = None
else:
    print("⚠️ Brain not available, running in fallback mode")

# ============================================
# YOUR PERSONALITY (for Cloudflare AI)
# ============================================
PERSONALITY = """You are Joshua Roy. Be CONCISE. 1-3 sentences max.
Short answers. Ask questions back. Never say "as an AI".
End with "Right?" or "Make sense?" when appropriate."""

# ============================================
# CLOUDFLARE AI TWIN
# ============================================
class CloudflareTwin:
    def __init__(self):
        self.model = "@cf/meta/llama-3.1-8b-instruct"
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{self.model}"
    
    def search_brain(self, query):
        if collection is None:
            return ""
        try:
            results = collection.query(query_texts=[query], n_results=3)
            if results['documents'] and results['documents'][0]:
                return "\n".join(results['documents'][0][:3])
        except Exception as e:
            print(f"Search error: {e}")
        return ""
    
    def respond(self, user_message):
        context = self.search_brain(user_message)
        
        prompt = f"""{PERSONALITY}

Context from my seminars: {context}

User: {user_message}

Concise response (1-3 sentences):"""
        
        try:
            response = requests.post(
                self.base_url,
                headers={"Authorization": f"Bearer {os.environ.get('CLOUDFLARE_API_TOKEN')}"},
                json={"prompt": prompt, "max_tokens": 200, "temperature": 0.6},
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()["result"]["response"]
            else:
                return f"AI Error: {response.status_code}"
        except Exception as e:
            return f"Error: {str(e)[:100]}"

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
# FLASK HEALTH CHECK (Keeps bot alive)
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health_check():
    return "✅ Bot is alive!", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=8080, debug=False)

# ============================================
# MAIN
# ============================================
def main():
    print("\n🚀 Starting Joshua's AI Twin...")
    
    # Start health server
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ Health check server running on port 8080")
    
    # Start Telegram bot
    app = Application.builder().token(TELEGRAM_TOKEN).build()
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
