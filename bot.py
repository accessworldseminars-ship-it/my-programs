import os
import sys
import traceback
import zipfile
import boto3
import requests
import asyncio
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, filters

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
print(f"Cloudflare API: {'✅' if CLOUDFLARE_API_TOKEN else '❌'}")
print(f"Account ID: {'✅' if ACCOUNT_ID else '❌'}")
print(f"Render URL: {RENDER_URL}")

# ============================================
# DOWNLOAD BRAIN FROM R2
# ============================================
collection = None

def download_brain():
    if os.path.exists('./bot_brain/chroma.sqlite3'):
        print("✅ Brain already exists locally")
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
        return True
    except Exception as e:
        print(f"❌ Download failed: {e}")
        traceback.print_exc()
        return False

# ============================================
# LOAD BRAIN
# ============================================
print("\n📚 Loading brain...")
if download_brain():
    try:
        import chromadb
        print(f"✅ ChromaDB imported")
        
        client = chromadb.PersistentClient(path="./bot_brain")
        print("✅ ChromaDB client created")
        
        collections = client.list_collections()
        print(f"Available collections: {[c.name for c in collections]}")
        
        if collections:
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
    print("⚠️ Could not download brain")

# ============================================
# CLOUDFLARE AI TWIN
# ============================================
class CloudflareTwin:
    def __init__(self):
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"
        print("✅ Cloudflare AI ready")

    def respond(self, message: str):
        # Search brain for relevant context
        context = ""
        if collection:
            try:
                results = collection.query(query_texts=[message], n_results=3)
                if results and results['documents'] and len(results['documents'][0]) > 0:
                    context_parts = []
                    for doc in results['documents'][0]:
                        if doc and len(doc.strip()) > 50:
                            context_parts.append(doc.strip()[:600])
                    context = "\n\n".join(context_parts[:3])
                    print(f"📚 Found {len(context_parts)} relevant chunks")
                else:
                    print("📚 No relevant chunks found")
            except Exception as e:
                print(f"Search error: {e}")

        # Build prompt
        if context:
            prompt = f"""You are Joshua Roy, a coach and seminar leader. Answer based ONLY on the seminar content below.

SEMINAR CONTENT:
{context}

USER: {message}

JOSHUA (concise, natural, 1-3 sentences):"""
        else:
            prompt = f"""You are Joshua Roy. The user's question doesn't match your seminar content directly.

USER: {message}

JOSHUA (be honest, say you don't have that in your seminars, ask them to rephrase):"""

        try:
            resp = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                json={
                    "prompt": prompt,
                    "max_tokens": 250,
                    "temperature": 0.7
                },
                timeout=25
            )
            if resp.status_code == 200:
                response = resp.json()['result']['response']
                print(f"🤖 AI responded ({len(response)} chars)")
                return response
            else:
                print(f"Cloudflare error: {resp.status_code}")
                return "I'm here. What's on your mind?"
        except Exception as e:
            print(f"Cloudflare request failed: {e}")
            return "Tell me more about that."

twin = CloudflareTwin()

# ============================================
# TELEGRAM HANDLERS
# ============================================
async def start(update: Update, context):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update: Update, context):
    user_message = update.message.text
    print(f"📨 User: {user_message[:100]}")
    response = twin.respond(user_message)
    await update.message.reply_text(response[:4000])

# ============================================
# SETUP DISPATCHER
# ============================================
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ============================================
# FLASK WEBHOOK APP
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "✅ Bot is alive!", 200

@flask_app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, bot)
        dispatcher.process_update(update)
        return "OK", 200
    except Exception as e:
        print(f"Webhook error: {e}")
        traceback.print_exc()
        return "OK", 200

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    # Set webhook at startup
    if RENDER_URL and TELEGRAM_TOKEN:
        webhook_url = f"{RENDER_URL.rstrip('/')}/webhook/{TELEGRAM_TOKEN}"
        try:
            # Clear any existing webhook/polling
            asyncio.run(bot.delete_webhook(drop_pending_updates=True))
            asyncio.run(bot.set_webhook(webhook_url))
            print(f"✅ Webhook set to: {webhook_url}")
        except Exception as e:
            print(f"Webhook setup warning: {e}")
    
    print(f"📊 Brain: {'LOADED' if collection else 'FALLBACK MODE'}")
    print(f"🤖 AI Engine: Cloudflare Llama 3.1 (8B)")
    print(f"✅ Bot is ready!")
    
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
