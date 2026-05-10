import os
import threading
import requests
import chromadb
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

# ============================================
# ENVIRONMENT VARIABLES
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CLOUDFLARE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')

# ============================================
# LOAD YOUR BRAIN
# ============================================
print("📚 Loading brain database...")
brain_db = chromadb.PersistentClient(path="./bot_brain")
collection = brain_db.get_collection("my_brain")
print(f"✅ Brain loaded! {collection.count():,} chunks")

# ============================================
# YOUR PERSONALITY (CONCISE VERSION)
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
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{self.model}"
    
    def search_brain(self, query):
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
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
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
    user_msg = update.message.text
    response = twin.respond(user_msg)
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
    
    print("✅ Bot is running with Cloudflare AI!")
    app.run_polling()

if __name__ == "__main__":
    main()
