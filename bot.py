import os
import sys
import traceback
import zipfile
import boto3
import requests
import threading
import shutil
import tempfile
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===", flush=True)
print(f"Python version: {sys.version}", flush=True)

# ============================================
# ENVIRONMENT CHECK
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'joshua-bot-brain')

# Print status (mask secrets)
print(f"TELEGRAM_TOKEN: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"CLOUDFLARE_API_TOKEN: {'✅' if CLOUDFLARE_API_TOKEN else '❌'}", flush=True)
print(f"CLOUDFLARE_ACCOUNT_ID: {'✅' if ACCOUNT_ID else '❌'}", flush=True)
print(f"R2_ACCESS_KEY: {'✅' if R2_ACCESS_KEY else '❌'}", flush=True)
print(f"R2_SECRET_KEY: {'✅' if R2_SECRET_KEY else '❌'}", flush=True)
print(f"BUCKET_NAME: {BUCKET_NAME}", flush=True)

# ============================================
# LOAD BRAIN WITH ERROR HANDLING
# ============================================
collection = None
brain_temp_dir = None

def load_brain():
    global collection, brain_temp_dir
    
    try:
        print("📥 Loading brain...", flush=True)
        
        # Check if we have R2 credentials
        if not all([R2_ACCESS_KEY, R2_SECRET_KEY, ACCOUNT_ID]):
            print("⚠️ Missing R2 credentials - running without brain", flush=True)
            return
        
        brain_temp_dir = tempfile.mkdtemp()
        brain_path = os.path.join(brain_temp_dir, 'bot_brain')
        os.makedirs(brain_path, exist_ok=True)
        
        # Download from R2
        print("Connecting to R2...", flush=True)
        s3 = boto3.client('s3',
            endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name='auto'
        )
        
        zip_path = '/tmp/bot_brain.zip'
        print(f"Downloading from bucket: {BUCKET_NAME}", flush=True)
        s3.download_file(BUCKET_NAME, 'bot_brain.zip', zip_path)
        print("✅ Downloaded brain.zip", flush=True)
        
        # Extract
        print("Extracting...", flush=True)
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(brain_path)
            print(f"✅ Extracted {len(z.namelist())} files", flush=True)
        
        # Find chroma.sqlite3
        chroma_db_path = None
        for root, dirs, files in os.walk(brain_path):
            if 'chroma.sqlite3' in files:
                chroma_db_path = root
                break
        
        if chroma_db_path is None:
            print("❌ chroma.sqlite3 not found!", flush=True)
            # List what we have
            print("Files in extracted directory:", flush=True)
            for root, dirs, files in os.walk(brain_path):
                for file in files:
                    print(f"  - {os.path.join(root, file)}", flush=True)
            return
        
        print(f"🔍 Found database at: {chroma_db_path}", flush=True)
        
        # Import ChromaDB with error handling
        print("Importing chromadb...", flush=True)
        try:
            import chromadb
            from chromadb.config import Settings
            print(f"✅ ChromaDB version: {chromadb.__version__}", flush=True)
        except ImportError as e:
            print(f"❌ Failed to import chromadb: {e}", flush=True)
            return
        
        # Connect to ChromaDB
        print("Connecting to ChromaDB...", flush=True)
        client = chromadb.PersistentClient(
            path=chroma_db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=False
            )
        )
        
        # List available collections
        available = client.list_collections()
        print(f"📚 Available collections: {[c.name for c in available]}", flush=True)
        
        if not available:
            print("❌ No collections found!", flush=True)
            return
        
        # Get the first collection (or specifically 'my_brain')
        collection = client.get_collection(available[0].name)
        print(f"✅ Brain loaded! {collection.count():,} chunks from '{available[0].name}'", flush=True)
        
        # Clean up
        os.remove(zip_path)
        
    except Exception as e:
        print(f"❌ Brain error: {e}", flush=True)
        traceback.print_exc(file=sys.stdout)

load_brain()

# ============================================
# CLOUDFLARE AI TWIN
# ============================================
class CloudflareTwin:
    def __init__(self):
        if not all([CLOUDFLARE_API_TOKEN, ACCOUNT_ID]):
            print("⚠️ Cloudflare AI not configured", flush=True)
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"

    def respond(self, message: str):
        if not all([CLOUDFLARE_API_TOKEN, ACCOUNT_ID]):
            return "AI service not configured. Please check environment variables."
        
        context = ""
        if collection:
            try:
                results = collection.query(query_texts=[message], n_results=3)
                if results and results.get('documents'):
                    context = "\n\n".join(results['documents'][0])
                    print(f"📚 Found {len(results['documents'][0])} relevant chunks", flush=True)
            except Exception as e:
                print(f"Search error: {e}", flush=True)
        
        prompt = f"""You are Joshua Roy. Speak naturally, confidently, and concisely (1-3 sentences).
        
Context from your seminars: {context[:700]}

User: {message}

Joshua:"""

        try:
            resp = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                json={"prompt": prompt, "max_tokens": 300, "temperature": 0.7},
                timeout=20
            )
            if resp.status_code == 200:
                response = resp.json()["result"]["response"]
                if len(response) > 500:
                    response = response[:500] + "..."
                return response
            print(f"AI API error: {resp.status_code}", flush=True)
            return "I'm here. What's on your mind?"
        except Exception as e:
            print(f"AI error: {e}", flush=True)
            return "Tell me more about that."

twin = CloudflareTwin()

# ============================================
# HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brain_status = f"✅ Brain loaded: {collection.count():,} seminar chunks" if collection else "⚠️ Running without knowledge base"
    await update.message.reply_text(
        f"Hey, it's Josh. What's on your mind?\n\n{brain_status}"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📨 Received: {update.message.text[:50]}...", flush=True)
    
    # Send typing indicator
    await update.message.chat.send_action(action="typing")
    
    response = twin.respond(update.message.text)
    await update.message.reply_text(response[:4000])
    print("✅ Replied", flush=True)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ Error: {context.error}", flush=True)

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
# CLEANUP
# ============================================
import atexit
def cleanup():
    global brain_temp_dir
    if brain_temp_dir and os.path.exists(brain_temp_dir):
        try:
            shutil.rmtree(brain_temp_dir)
            print("🧹 Cleaned up temp files", flush=True)
        except:
            pass

atexit.register(cleanup)

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    try:
        print("\n" + "="*50, flush=True)
        print("Starting bot...", flush=True)
        print(f"Flask port: {os.environ.get('PORT', 8080)}", flush=True)
        print("="*50 + "\n", flush=True)
        
        # Start Flask in background
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        print("✅ Flask server started", flush=True)
        
        # Small delay to let Flask start
        import time
        time.sleep(1)
        
        # Check Telegram token
        if not TELEGRAM_TOKEN:
            print("❌ TELEGRAM_TOKEN not set! Exiting.", flush=True)
            sys.exit(1)
        
        # Create event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Build application
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_error_handler(error_handler)
        
        print("🚀 Starting polling...", flush=True)
        app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        print(f"❌ Fatal error: {e}", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
