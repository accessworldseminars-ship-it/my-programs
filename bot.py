import os
import sys
import traceback
import zipfile
import boto3
import requests
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===", flush=True)

# ============================================
# ENV VARS
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GROK_API_KEY = os.environ.get('GROK_API_KEY')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'joshua-bot-brain')

print(f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)

# ============================================
# BRAIN
# ============================================
collection = None

def load_brain():
    global collection
    try:
        if not os.path.exists('./bot_brain/chroma.sqlite3'):
            print("📥 Downloading brain...", flush=True)
            s3 = boto3.client('s3', endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
                              aws_access_key_id=R2_ACCESS_KEY, aws_secret_access_key=R2_SECRET_KEY, region_name='auto')
            s3.download_file(BUCKET_NAME, 'bot_brain.zip', '/tmp/brain.zip')
            
            if os.path.exists('./bot_brain'):
                import shutil
                shutil.rmtree('./bot_brain')
            with zipfile.ZipFile('/tmp/brain.zip', 'r') as z:
                z.extractall('./')
            print("✅ Extracted", flush=True)

        import chromadb
        client = chromadb.PersistentClient(path="./bot_brain")
        collection = client.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks", flush=True)
    except Exception as e:
        print(f"❌ Brain error: {e}", flush=True)

load_brain()

# ============================================
# GROK
# ============================================
class GrokTwin:
    def respond(self, message: str):
        context = ""
        if collection:
            try:
                results = collection.query(query_texts=[message], n_results=3)
                if results and results.get('documents'):
                    context = "\n\n".join(results['documents'][0])
            except:
                pass

        try:
            resp = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "grok-3-70b-8192",
                    "messages": [{"role": "user", "content": f"You are Joshua Roy. Be concise.\nContext: {context[:600]}\n\nUser: {message}"}],
                    "temperature": 0.75,
                    "max_tokens": 400
                },
                timeout=25
            )
            return resp.json()['choices'][0]['message']['content'] if resp.status_code == 200 else "I'm here."
        except:
            return "Tell me more about that."

twin = GrokTwin()

# ============================================
# HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📨 Message received: {update.message.text}", flush=True)
    response = twin.respond(update.message.text)
    await update.message.reply_text(response[:4000])
    print("✅ Replied to user", flush=True)

# ============================================
# FLASK (Health only)
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "Bot is alive ✅", 200

# ============================================
# MAIN - POLLING MODE
# ============================================
if __name__ == "__main__":
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Starting bot with Polling...", flush=True)
    print("📊 Brain: LOADED | AI: Grok 70B", flush=True)

    # Health server in background
    import threading
    def run_flask():
        port = int(os.environ.get("PORT", 8080))
        flask_app.run(host='0.0.0.0', port=port, debug=False)
    threading.Thread(target=run_flask, daemon=True).start()

    # Start polling
    app.run_polling(drop_pending_updates=True)
