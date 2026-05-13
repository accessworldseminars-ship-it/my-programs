import os
import sys
import json
import asyncio
import threading
import requests
import time
import urllib.request
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

print("=== AccessWorld Bot Squad Starting ===", flush=True)

# ============================================
# ENVIRONMENT
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ASSISTANT_TELEGRAM_TOKEN = os.environ.get('ASSISTANT_TELEGRAM_TOKEN')
CLERK_TELEGRAM_TOKEN = os.environ.get('CLERK_TELEGRAM_TOKEN')
# REMOVED: ACARDOOR_TELEGRAM_TOKEN, TODOLIST_TELEGRAM_TOKEN
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
CLOUDFLARE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
SUPABASE_URL = "https://mldzkzrljaxudemfpbkh.supabase.co"
SUPABASE_KEY = os.environ.get('SUPABASE_TOKEN')
R2_BUCKET = "joshua-bot-brain"
R2_OBJECT = "working_brain_json"

print(f"Joshua Bot: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Assistant Bot: {'✅' if ASSISTANT_TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Clerk Bot: {'✅' if CLERK_TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Groq: {'✅' if GROQ_API_KEY else '❌'}", flush=True)

# ============================================
# LOAD WORKING BRAIN
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
            print(f"🧠 Brain loaded: {len(brain)} entries", flush=True)
            return brain
        print(f"❌ R2 failed: {resp.status_code}", flush=True)
        return []
    except Exception as e:
        print(f"❌ Brain error: {e}", flush=True)
        return []

WORKING_BRAIN = load_working_brain()

# ============================================
# LOAD CLERK LINKS
# ============================================
def load_clerk_links():
    try:
        url = "https://raw.githubusercontent.com/accessworldseminars-ship-it/my-programs/main/clerk_links.json"
        with urllib.request.urlopen(url) as response:
            links = json.loads(response.read().decode())
            print(f"🔗 Clerk links loaded", flush=True)
            return links
    except Exception as e:
        print(f"❌ Clerk links error: {e}", flush=True)
        return {}

CLERK_LINKS = load_clerk_links()

# ============================================
# SHARED FUNCTIONS
# ============================================
def search_brain(query, top_k=3):
    query_words = set(query.lower().split())
    scored = []
    for entry in WORKING_BRAIN:
        summary = entry.get("summary", "").lower()
        score = sum(1 for word in query_words if word in summary)
        if score > 0:
            scored.append((score, entry))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [e for _, e in scored[:top_k]]

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
        print(f"❌ Supabase error: {e}", flush=True)
    return ""

def get_context(message, top_k=3):
    matches = search_brain(message, top_k=top_k)
    parts = []
    for match in matches:
        text = fetch_full_entry(match["id"])
        if text:
            parts.append(text)
    return "\n\n".join(parts) if parts else ""

def groq_call(prompt, max_tokens=300, temperature=0.7):
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
                "max_tokens": max_tokens,
                "temperature": temperature
            },
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        print(f"❌ Groq: {resp.status_code} {resp.text}", flush=True)
        return None
    except Exception as e:
        print(f"❌ Groq error: {e}", flush=True)
        return None

# ============================================
# BOT RESPONSE FUNCTIONS
# ============================================
def joshua_response(message):
    context = get_context(message, top_k=3)
    prompt = f"""You are Joshua Roy, an Australian Results Coach with 12 years experience.
You specialise in NLP and Nervous System Reprogramming (NSR).
Speak naturally, directly, and in plain Australian English.
Be warm but straight to the point. 1-3 sentences unless more is needed.
Never use surfer slang. Sound like a real coach who has been through hard times.

Context from your seminars:
{context[:1000]}

User: {message}
Joshua:"""
    return groq_call(prompt, max_tokens=300, temperature=0.7) or "Tell me more about that."

def assistant_response(message):
    context = get_context(message, top_k=5)
    prompt = f"""You are Joshua's personal AI assistant. You handle ALL his internal operations:

**YOUR CAPABILITIES:**
1. PLANNING & DRAFTING - Session planning, content drafting, brainstorming
2. TASK MANAGEMENT - Help prioritise tasks, track what needs doing, break big things into steps
3. SYSTEMS IMPROVEMENT - Analyse workflows, identify inefficiencies, create step-by-step processes

**STYLE:**
- Direct, practical, efficient. No fluff.
- Action-focused. If he asks for a task list, give him one.
- If he asks for a system fix, analyse and suggest specific improvements.

**RELEVANT KNOWLEDGE (from seminars):**
{context[:1500]}

Joshua: {message}
Assistant:"""
    return groq_call(prompt, max_tokens=500, temperature=0.5) or "On it — try again in a moment."

def clerk_response(message):
    context = get_context(message, top_k=3)
    links_str = json.dumps(CLERK_LINKS, indent=2)
    prompt = f"""You are the Clerk — a no-nonsense admin assistant for Joshua Roy, AccessWorld Seminars Brisbane.
You have Joshua's complete link library below. When he asks for a link, find it and give it instantly.
When he needs admin help — drafting, planning, organising — get it done fast.
Be direct. No fluff. Links only when asked. One-line description with each link.

LINK LIBRARY:
{links_str}

RELEVANT KNOWLEDGE:
{context[:800]}

Joshua: {message}
Clerk:"""
    return groq_call(prompt, max_tokens=600, temperature=0.3) or "On it — try again in a moment."

# ============================================
# TELEGRAM HANDLERS
# ============================================
def make_start(bot_name, brain_count):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        messages = {
            "joshua": f"Hey, it's Josh. What's on your mind?\n\n🧠 Brain: {brain_count:,} entries",
            "assistant": f"Assistant ready, Josh.\n\n📋 Planning | ⚙️ Systems | ✅ Tasks\n\nWhat do you need?",
            "clerk": f"Clerk ready, Josh.\n\n🔗 {sum(len(v) for v in CLERK_LINKS.values()) if CLERK_LINKS else 0} links loaded\n\nWhat do you need?"
        }
        await update.message.reply_text(messages.get(bot_name, "Ready."))
    return start

def make_handler(response_func, bot_name):
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(f"📨 {bot_name}: {update.message.text[:50]}", flush=True)
        await update.message.chat.send_action(action="typing")
        response = response_func(update.message.text)
        await update.message.reply_text(response[:4000])
        print(f"✅ {bot_name} replied", flush=True)
    return handle_message

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ Error: {context.error}", flush=True)

# ============================================
# FLASK HEALTH
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return {
        "status": "healthy",
        "brain_entries": len(WORKING_BRAIN),
        "model": "llama-3.3-70b-versatile",
        "bots": ["joshua", "assistant", "clerk"]
    }, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================
# RUN ALL BOTS
# ============================================
async def run_all_bots():
    time.sleep(3)

    # ONLY 3 BOTS: Joshua, Assistant (now with tasks + systems), Clerk
    bots = [
        (TELEGRAM_TOKEN, "joshua", joshua_response),
        (ASSISTANT_TELEGRAM_TOKEN, "assistant", assistant_response),
        (CLERK_TELEGRAM_TOKEN, "clerk", clerk_response),
    ]

    apps = []
    for token, name, response_func in bots:
        if not token:
            print(f"⚠️ Skipping {name} — no token", flush=True)
            continue
        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("start", make_start(name, len(WORKING_BRAIN))))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, make_handler(response_func, name)))
        app.add_error_handler(error_handler)
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print(f"🚀 {name} bot running", flush=True)
        apps.append(app)

    print(f"✅ {len(apps)} bots running (Joshua, Assistant, Clerk)", flush=True)

    while True:
        await asyncio.sleep(1)

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing!", flush=True)
        sys.exit(1)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)

    print("🚀 Starting all bots...", flush=True)
    asyncio.run(run_all_bots())
