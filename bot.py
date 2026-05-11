import os
import sys
import traceback
import asyncio
import numpy as np
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext import ContextTypes

print("=== Joshua AI Twin Bot Starting (SQLite Edition) ===", flush=True)

# ============================================
# ENVIRONMENT
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')

print(f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Cloudflare: {'✅' if CLOUDFLARE_API_TOKEN else '❌'}", flush=True)

# ============================================
# LOAD SQLITE BRAIN
# ============================================
from semantic_search import SemanticSearcher
searcher = SemanticSearcher()
print(f"🧠 SQLite brain loaded with {len(searcher.ids):,} chunks", flush=True)

# ============================================
# EMBEDDING FUNCTION
# (Replace this with your real embedding model)
# ============================================
def embed_text(text: str):
    # TODO: Replace with Cloudflare embeddings or HF embeddings
    # For now, random vector for testing
    return np.random.rand(768).astype(np.float32)

# ============================================
# CLOUDFLARE AI TWIN
# ============================================
import requests

class CloudflareTwin:
    def __init__(self):
        self.url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"
        )

    def respond(self, message: str):
        # --- Semantic Search ---
        context = ""
        try:
            emb = embed_text(message)
            results = searcher.search(emb, top_k=3)
            if results:
                context = "\n\n".join([r["content"] for r in results])
                print(f"📚 Found {len(results)} chunks", flush=True)
        except Exception as e:
            print(f"Search error: {e}", flush=True)

        # --- Build Prompt ---
        prompt = f"""You are Joshua Roy. Speak naturally, confidently, and concisely (1–3 sentences).

Context from your seminars:
{context[:700]}

User: {message}
Joshua:"""

        # --- Cloudflare Llama ---
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

            print(f"AI API status: {resp.status_code}", flush=True)
            return "I'm here. What's on your mind?"

        except Exception as e:
            print(f"AI error: {e}", flush=True)
            return "Tell me more about that."

twin = CloudflareTwin()

# ============================================
# TELEGRAM HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Hey, it's Josh. What's on your mind?\n\n🧠 Brain: {len(searcher.ids):,} chunks"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📨 Received: {update.message.text[:50]}...", flush=True)
    await update.message.chat.send_action(action="typing")

    response = twin.respond(update.message.text)
    await update.message.reply_text(response[:4000])
    print("✅ Replied", flush=True)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ Error: {context.error}", flush=True)

# ============================================
# FLASK HEALTH ENDPOINT
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return {
        "status": "healthy",
        "chunks": len(searcher.ids)
    }, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!", flush=True)
        sys.exit(1)

    # Start Flask in background thread
    print("🌐 Starting Flask health server...", flush=True)
    import threading
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    import time
    time.sleep(1)

    print("=" * 50, flush=True)
    print("🚀 Starting bot...", flush=True)
    print(f"📊 Brain: {len(searcher.ids):,} chunks", flush=True)
    print("=" * 50, flush=True)

    # Telegram event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
    app.run_polling(drop_pending_updates=True)
