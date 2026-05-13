import os
import sys
import json
import asyncio
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

print("=== Joshua AI Twin Bot Starting ===", flush=True)

# ============================================
# ENVIRONMENT
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
CLOUDFLARE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
SUPABASE_URL = "https://mldzkzrljaxudemfpbkh.supabase.co"
SUPABASE_KEY = os.environ.get('SUPABASE_TOKEN')
R2_BUCKET = "joshua-bot-brain"
R2_OBJECT = "working_brain_json"

print(f"Telegram: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Groq: {'✅' if GROQ_API_KEY else '❌'}", flush=True)
print(f"Supabase: {'✅' if SUPABASE_KEY else '❌'}", flush=True)

# ============================================
# LOAD WORKING BRAIN FROM CLOUDFLARE R2
# ============================================
def load_working_brain():
    try:
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{CLOUDFLARE_ACCOUNT_ID}/r2/buckets/{R2_BUCKET}/objects/{R2_OBJECT}"
        )
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
            timeout=30
        )
        if resp.status_code == 200:
            brain = json.loads(resp.content)
            print(f"🧠 Working brain loaded: {len(brain)} entries", flush=True)
            return brain
        else:
            print(f"❌ R2 load failed: {resp.status_code}", flush=True)
            return []
    except Exception as e:
        print(f"❌ Brain load error: {e}", flush=True)
        return []

WORKING_BRAIN = load_working_brain()

# ============================================
# SEARCH WORKING BRAIN (RAM)
# ============================================
def search_working_brain(query, top_k=3):
    query_words = set(query.lower().split())
    scored = []
    for entry in WORKING_BRAIN:
        summary = entry.get("summary", "").lower()
        score = sum(1 for word in query_words if word in summary)
        if score > 0:
            scored.append((score, entry))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [e for _, e in scored[:top_k]]

# ============================================
# FETCH FULL ENTRY FROM SUPABASE
# ============================================
def fetch_full_entry(entry_id):
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/brain?id=eq.{entry_id}&select=text",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}"
            },
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data[0].get("text", "")
    except Exception as e:
        print(f"❌ Supabase fetch error: {e}", flush=True)
    return ""

# ============================================
# GROQ RESPONSE WITH LLAMA 3.3
# ============================================
def get_groq_response(message, context_text):
    prompt = f"""You are Joshua Roy, an Australian Results Coach with 12 years experience. 
You specialise in NLP and Nervous System Reprogramming (NSR).
Speak naturally, directly, and in plain Australian English. 
Be warm but straight to the point. 1-3 sentences max unless more is needed.

Context from your seminars:
{context_text[:1000]}

User: {message}
Joshua:"""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.7
            },
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        print(f"❌ Groq status: {resp.status_code}", flush=True)
        print(f"Response: {resp.text}", flush=True)
        return "Tell me more about that."
    except Exception as e:
        print(f"❌ Groq error: {e}", flush=True)
        return "I'm here. What's on your mind?"

# ============================================
# MAIN RESPONSE PIPELINE
# ============================================
def build_response(message):
    # Step 1 - Search working brain in RAM
    matches = search_working_brain(message, top_k=3)
    print(f"📚 RAM matches: {len(matches)}", flush=True)

    # Step 2 - Fetch full entries from Supabase
    context_parts = []
    for match in matches:
        full_text = fetch_full_entry(match["id"])
        if full_text:
            context_parts.append(full_text)

    context_text = "\n\n".join(context_parts) if context_parts else "No specific context found."

    # Step 3 - Get Groq response with Llama 3.3
    return get_groq_response(message, context_text)

# ============================================
# TELEGRAM HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Hey, it's Josh. What's on your mind?\n\n🧠 Brain loaded: {len(WORKING_BRAIN):,} entries\n🤖 Model: Llama 3.3 70B"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📨 {update.message.text[:50]}", flush=True)
    await update.message.chat.send_action(action="typing")
    response = build_response(update.message.text)
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
    return {"status": "healthy", "brain_entries": len(WORKING_BRAIN), "model": "llama-3.3-70b-versatile"}, 200

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

    print("🌐 Starting Flask...", flush=True)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    import time
    time.sleep(1)

    print("🚀 Bot starting with Llama 3.3 70B...", flush=True)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
    app.run_polling(drop_pending_updates=True)
