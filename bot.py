import os
import sys
import traceback
import zipfile
import boto3
import requests
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting ===", flush=True)

# ============================================
# ENVIRONMENT VARIABLES
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
GROK_API_KEY = os.environ.get('GROK_API_KEY')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'joshua-bot-brain')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')

print(f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}")
print(f"Grok API: {'✅' if GROK_API_KEY else '❌'}")

# ============================================
# DOWNLOAD + LOAD BRAIN
# ============================================
collection = None

def download_brain():
    if os.path.exists('./bot_brain/chroma.sqlite3'):
        print("✅ Brain already exists")
        return True
    print("📥 Downloading brain from R2...")
    try:
        s3 = boto3.client('s3',
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

        with zipfile.ZipFile('/tmp/brain.zip', 'r') as z:
            z.extractall('./')
        print("✅ Extracted")
        return True
    except Exception as e:
        print(f"❌ Download failed: {e}")
        traceback.print_exc()
        return False

if download_brain():
    try:
        import chromadb
        client = chromadb.PersistentClient(path="./bot_brain")
        collection = client.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks")
    except Exception as e:
        print(f"❌ Brain load error: {e}")
        traceback.print_exc()

# ============================================
# GROK TWIN
# ============================================
class GrokTwin:
    def __init__(self):
        self.url = "https://api.x.ai/v1/chat/completions"

    def respond(self, message: str):
        context = ""
        if collection:
            try:
                results = collection.query(query_texts=[message], n_results=3)
                if results and results.get('documents'):
                    context = "\n\n".join(results['documents'][0])
            except:
                pass

        prompt = f"""You are Joshua Roy. Speak naturally, confidently, and concisely (1-3 sentences max).
Context from your seminars: {context[:700]}
User: {message}
Joshua:"""

        try:
            resp = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "grok-3-70b-8192",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.75,
                    "max_tokens": 500
                },
                timeout=25
            )
            if resp.status_code == 200:
                return resp.json()['choices'][0]['message']['content']
            return "I'm here. What's on your mind?"
        except Exception as e:
            print(f"Grok error: {e}")
            return "Tell me more about that."

twin = GrokTwin()

# ============================================
# HANDLERS
# ============================================
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
    return "Bot is alive ✅", 200

@flask_app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        asyncio.run(application.process_update(update))
    except Exception as e:
        print(f"Webhook error: {e}")
    return "OK", 200

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    global application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Set webhook
    if RENDER_URL:
        webhook_url = f"{RENDER_URL.rstrip('/')}/webhook/{TELEGRAM_TOKEN}"
        try:
            asyncio.run(application.bot.set_webhook(webhook_url, drop_pending_updates=True))
            print(f"✅ Webhook set: {webhook_url}")
        except Exception as e:
            print(f"Webhook warning: {e}")

    print(f"📊 Brain: LOADED | AI: Grok 70B")
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
