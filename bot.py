import os
import zipfile
import boto3
import threading
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

# ============================================
# ENVIRONMENT VARIABLES (Set in Render)
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
BUCKET_NAME = "joshua-bot-brain"

# ============================================
# DOWNLOAD BRAIN FROM R2
# ============================================
def download_brain():
    """Downloads chroma.zip from R2 and extracts it"""
    
    if os.path.exists('./bot_brain'):
        print("✅ Brain already exists")
        return True
    
    print("📥 Downloading chroma.zip from Cloudflare R2...")
    
    # Connect to R2
    s3 = boto3.client(
        's3',
        endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        region_name='auto'
    )
    
    # Download zip file
    zip_path = '/tmp/chroma.zip'
    try:
        s3.download_file(BUCKET_NAME, 'bot_brain.zip', zip_path)
        print(f"✅ Downloaded {os.path.getsize(zip_path) / 1024 / 1024:.1f} MB")
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return False
    
    # Extract zip
    print("📦 Extracting brain...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall('./')
        print("✅ Extraction complete")
        
        # Verify brain loaded
        import chromadb
        test_client = chromadb.PersistentClient(path="./bot_brain")
        test_client.get_collection("my_brain")
        print("✅ Brain verified!")
        return True
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        return False

# ============================================
# LOAD BRAIN (DOWNLOAD IF NEEDED)
# ============================================
print("🚀 Starting Joshua's AI Twin...")

# Download brain if not exists
if not os.path.exists('./bot_brain'):
    success = download_brain()
    if not success:
        print("⚠️ Continuing without brain...")

# Try to load brain
try:
    import chromadb
    brain_db = chromadb.PersistentClient(path="./bot_brain")
    collection = brain_db.get_collection("my_brain")
    print(f"✅ Brain loaded! {collection.count():,} chunks")
    BRAIN_READY = True
except:
    print("⚠️ Brain not loaded - using fallback mode")
    BRAIN_READY = False
    collection = None

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
        self.model = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{self.model}"
    
    def respond(self, user_message):
        # Search brain if available
        context = ""
        if BRAIN_READY and collection:
            try:
                results = collection.query(query_texts=[user_message], n_results=3)
                if results['documents'] and results['documents'][0]:
                    context = "\n".join(results['documents'][0][:3])
            except:
                pass
        
        prompt = f"""{PERSONALITY}

Context from my seminars: {context}

User: {user_message}

Concise response (1-3 sentences):"""
        
        try:
            import requests
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
async def start(update, context):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update, context):
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
    # Start health server
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Telegram bot
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Bot is running on Render with Cloudflare AI!")
    print(f"📊 Brain status: {'LOADED' if BRAIN_READY else 'FALLBACK MODE'}")
    app.run_polling()

if __name__ == "__main__":
    main()
