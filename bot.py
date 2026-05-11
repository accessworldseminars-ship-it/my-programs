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

# ============================================
# ENVIRONMENT
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'joshua-bot-brain')

print(f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Cloudflare: {'✅' if CLOUDFLARE_API_TOKEN else '❌'}", flush=True)

# ============================================
# LOAD BRAIN
# ============================================
collection = None
brain_temp_dir = None

def load_brain():
    global collection, brain_temp_dir

    try:
        print("📥 Loading brain...", flush=True)

        brain_temp_dir = tempfile.mkdtemp()
        brain_path = os.path.join(brain_temp_dir, 'bot_brain')
        os.makedirs(brain_path, exist_ok=True)

        # Download from R2
        s3 = boto3.client('s3',
            endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name='auto'
        )

        zip_path = '/tmp/bot_brain.zip'
        s3.download_file(BUCKET_NAME, 'bot_brain.zip', zip_path)
        print("✅ Downloaded", flush=True)

        # Extract and show full directory tree
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(brain_path)
            all_files = z.namelist()
        print(f"✅ Extracted {len(all_files)} files", flush=True)

        # DEBUG: Show exactly what's in brain_path
        print(f"📁 brain_path = {brain_path}", flush=True)
        for root, dirs, files in os.walk(brain_path):
            level = root.replace(brain_path, '').count(os.sep)
            indent = ' ' * 2 * level
            print(f"{indent}{os.path.basename(root)}/", flush=True)
            subindent = ' ' * 2 * (level + 1)
            for file in files:
                print(f"{subindent}{file}", flush=True)

        # Find where chroma.sqlite3 actually lives
        chroma_db_path = None
        for root, dirs, files in os.walk(brain_path):
            if 'chroma.sqlite3' in files:
                chroma_db_path = root
                break

        if chroma_db_path is None:
            print("❌ chroma.sqlite3 not found anywhere in extracted files!", flush=True)
            return

        print(f"🔍 Using ChromaDB path: {chroma_db_path}", flush=True)

        # Connect to ChromaDB
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=chroma_db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # List available collections before trying to get one
        available = client.list_collections()
        print(f"📚 Available collections: {[c.name for c in available]}", flush=True)

        collection = client.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks", flush=True)

        os.remove(zip_path)

    except Exception as e:
        print(f"❌ Brain error: {e}", flush=True)
        traceback.print_exc()

load_brain()

# ============================================
# CLEAR TELEGRAM WEBHOOK/CONFLICTS
# ============================================
async def clear_telegram_conflicts():
    """Clear any existing webhook or polling sessions"""
    try:
        print("🧹 Clearing Telegram conflicts...", flush=True)
        temp_app = Application.builder().token(TELEGRAM_TOKEN).build()
        await temp_app.initialize()
        
        # Delete webhook and drop pending updates
        await temp_app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook cleared", flush=True)
        
        await temp_app.shutdown()
        print("✅ Conflicts cleared", flush=True)
    except Exception as e:
        print(f"⚠️ Conflict clearance warning: {e}", flush=True)

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
                if results and results.get('documents'):
                    context = "\n\n".join(results['documents'][0])
                    print(f"📚 Found {len(results['documents'][0])} chunks", flush=True)
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
                return resp.json()["result"]["response"]
            return "I'm here. What's on your mind?"
        except Exception as e:
            print(f"AI error: {e}", flush=True)
            return "Tell me more about that."

twin = CloudflareTwin()

# ============================================
# HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brain_status = f"✅ Brain loaded: {collection.count():,} chunks" if collection else "⚠️ Running without brain"
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
    """Handle errors"""
    print(f"❌ Error: {context.error}", flush=True)
    if update and update.message:
        await update.message.reply_text("Sorry, I hit a glitch. Try again?")

# ============================================
# FLASK HEALTH
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    status = "healthy" if collection else "degraded"
    count = collection.count() if collection else 0
    return {"status": status, "brain_loaded": collection is not None, "chunks": count}, 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False)

# ============================================
# CLEANUP ON SHUTDOWN
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
# MAIN - POLLING
# ============================================
if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!", flush=True)
        sys.exit(1)
    
    # Run conflict clearance
    try:
        asyncio.run(clear_telegram_conflicts())
    except RuntimeError:
        # If already in event loop, create new
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(clear_telegram_conflicts())
    
    # Build application
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    # Start Flask in background
    threading.Thread(target=run_flask, daemon=True).start()
    
    print("="*50, flush=True)
    print("🚀 Starting bot with Cloudflare AI...", flush=True)
    print(f"📊 Brain status: {'✅ LOADED' if collection else '⚠️ FALLBACK MODE'}", flush=True)
    if collection:
        print(f"📚 Memory: {collection.count():,} knowledge chunks", flush=True)
    print("="*50, flush=True)
    
    # Start polling with proper settings to prevent conflicts
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],  # Only listen for messages
        stop_signals=None  # Prevent signal conflicts
    )
