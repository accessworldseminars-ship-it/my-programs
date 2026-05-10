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
GROK_API_KEY = os.environ.get('GROK_API_KEY')  # NEW
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'joshua-bot-brain')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')

print(f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}")
print(f"R2: {'✅' if R2_ACCESS_KEY else '❌'}")
print(f"Grok API: {'✅' if GROK_API_KEY else '❌'}")
print(f"Render URL: {RENDER_URL}")

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

        with zipfile.ZipFile('/tmp/brain.zip', 'r') as zip_ref:
            zip_ref.extractall('./')
        print("✅ Extracted")
        return True
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return False

# ============================================
# LOAD BRAIN
# ============================================
collection = None

print("\n📚 Loading brain...")
if download_brain():
    try:
        import chromadb
        client = chromadb.PersistentClient(path="./bot_brain")
        collection = client.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks")
    except Exception as e:
        print(f"❌ Brain error: {e}")
        collection = None

if collection is None:
    print("⚠️ FALLBACK MODE - no brain")

# ============================================
# GROK AI TWIN (70B)
# ============================================
class GrokTwin:
    def __init__(self):
        self.api_key = GROK_API_KEY
        self.url = "https://api.x.ai/v1/chat/completions"
        
        if not self.api_key:
            print("⚠️ GROK_API_KEY not found! Using fallback responses.")

    def respond(self, message):
        # Search brain for context
        context = ""
        if collection:
            try:
                results = collection.query(query_texts=[message], n_results=3)
                if results and results['documents']:
                    context = "\n\n".join(results['documents'][0])
                    print(f"📚 Found {len(results['documents'][0])} relevant chunks")
            except Exception as e:
                print(f"Search error: {e}")

        # System prompt - Joshua's personality
        system_prompt = """You are Joshua Roy - a sharp, experienced, no-nonsense coach and entrepreneur.
        
        Rules:
        - Speak like the real Joshua: direct, confident, slightly witty, and concise
        - Use natural spoken language - no corporate or AI-sounding phrases
        - Keep replies to 2-4 sentences max unless asked for more
        - Reference your own seminars and content when relevant using the context
        - Ask questions back to keep the conversation going
        - Never say "as an AI" or "I don't have personal experience" - you ARE Joshua
        
        You've been coaching for years. You've seen it all. Get to the point."""

        user_prompt = f"""Context from Joshua's seminars:
{context[:1500]}

User's message: {message}

Respond as Joshua (concise, direct, natural):"""

        payload = {
            "model": "grok-3-70b-8192",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.75,
            "max_tokens": 512
        }

        try:
            resp = requests.post(
                self.url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=25
            )
            
            if resp.status_code == 200:
                response = resp.json()['choices'][0]['message']['content']
                print(f"🤖 Grok responded ({len(response)} chars)")
                return response
            else:
                print(f"Grok API error: {resp.status_code} - {resp.text[:200]}")
                return self._fallback_response(message)
                
        except Exception as e:
            print(f"Grok request failed: {e}")
            return self._fallback_response(message)
    
    def _fallback_response(self, message):
        """Fallback when Grok is unavailable"""
        return "I hear you. Let's come back to that. What else is on your mind?"

twin = GrokTwin()

# ============================================
# TELEGRAM HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey, it's Josh. I'm running on Grok 70B now – much sharper. "
        "What's on your mind?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    print(f"📨 User: {user_message[:100]}")
    
    response = twin.respond(user_message)
    await update.message.reply_text(response)

# ============================================
# FLASK + WEBHOOK
# ============================================
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "OK", 200

@flask_app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), app.bot)
    app.process_update(update)
    return "OK", 200

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("\n🚀 Starting Joshua AI Twin with Grok 70B...")
    
    # Set webhook
    webhook_url = f"{RENDER_URL}/webhook/{TELEGRAM_TOKEN}"
    app.bot.set_webhook(webhook_url)
    print(f"✅ Webhook set to: {webhook_url}")
    
    # Start Flask
    port = int(os.environ.get("PORT", 8080))
    print(f"📊 Brain status: {'LOADED' if collection else 'FALLBACK'}")
    print(f"🤖 AI Engine: GROK 70B")
    print(f"✅ Bot live on port {port}")
    
    flask_app.run(host='0.0.0.0', port=port)
