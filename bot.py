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
# LOAD BRAIN - USING CORRECT COLLECTION ID
# ============================================
collection = None

def load_brain():
    global collection
    try:
        print("📥 Loading brain...", flush=True)
        
        # Download if not exists
        if not os.path.exists('./bot_brain/chroma.sqlite3'):
            s3 = boto3.client('s3',
                endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
                aws_access_key_id=R2_ACCESS_KEY,
                aws_secret_access_key=R2_SECRET_KEY,
                region_name='auto'
            )
            s3.download_file(BUCKET_NAME, 'bot_brain.zip', '/tmp/brain.zip')
            print("✅ Downloaded", flush=True)

            if os.path.exists('./bot_brain'):
                import shutil
                shutil.rmtree('./bot_brain')
            with zipfile.ZipFile('/tmp/brain.zip', 'r') as z:
                z.extractall('./')
            print("✅ Extracted", flush=True)

        import chromadb
        client = chromadb.PersistentClient(path="./bot_brain")
        
        # FIXED: Using the actual collection ID from your brain
        collection = client.get_collection("307af698-2f4f-45f1-9440-29e9a41e36ed")
        print(f"✅ Brain loaded! {collection.count():,} chunks", flush=True)
        
    except Exception as e:
        print(f"❌ Brain error: {e}", flush=True)
        traceback.print_exc()

load_brain()

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

    print("🚀 Starting bot with Cloudflare AI...", flush=True)
    print(f"📊 Brain status: {'LOADED' if collection else 'FALLBACK MODE'}", flush=True)
    
    # Start polling
    app.run_polling(drop_pending_updates=True)
