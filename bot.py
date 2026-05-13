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
ACARDOOR_TELEGRAM_TOKEN = os.environ.get('ACARDOOR_TELEGRAM_TOKEN')
TODOLIST_TELEGRAM_TOKEN = os.environ.get('TODOLIST_TELEGRAM_TOKEN')
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
print(f"Acardoor Bot: {'✅' if ACARDOOR_TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Todolist Bot: {'✅' if TODOLIST_TELEGRAM_TOKEN else '❌'}", flush=True)
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
    prompt = f"""You are a sharp personal assistant to Joshua Roy, founder of AccessWorld Seminars Brisbane.
You know his entire body of work — NLP, NSR, coaching frameworks, business operations.
Help him plan sessions, organise content, draft copy, brainstorm, and review material.
Be direct, practical, efficient. No fluff.

Relevant knowledge:
{context[:1500]}

Joshua: {message}
Assistant:"""
    return groq_call(prompt, max_tokens=500, temperature=0.5) or "Something went wrong, try again."

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

def acardoor_response(message):
    context = get_context(message, top_k=3)
    prompt = f"""You are Acardoor — a systems improvement specialist for Joshua Roy and AccessWorld Seminars.
Your job is to help Joshua build better systems, workflows, and processes for his business and life.
Think like an operations expert. Identify inefficiencies, suggest improvements, create step-by-step processes.
Be practical, specific, and direct. Focus on what can be implemented immediately.

Relevant knowledge:
{context[:1000]}

Joshua: {message}
Acardoor:"""
    return groq_call(prompt, max_tokens=500, temperature=0.5) or "Let me think about that system — try again."

def todolist_response(message):
    context = get_context(message, top_k=2)
    prompt = f"""You are the Productivity Bot for Joshua Roy — a no-nonsense task and productivity assistant.
Help Joshua stay on track, prioritise tasks, manage his time, and get things done.
You understand his business (AccessWorld Seminars), his coaching work, and his church responsibilities.
Be direct, energetic, and action-focused. Break big tasks into small steps. Keep him moving forward.

Relevant context:
{context[:800]}

Joshua: {message}
Productivity Bot:"""
    return groq_call(prompt, max_tokens=400, temperature=0.6) or "Let's get moving — try again."

# ============================================
# TELEGRAM HANDLERS
# ============================================
def make_start(bot_name, brain_count):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        messages = {
            "joshua": f"Hey, it's Josh. What's on your mind?\n\n🧠 Brain: {brain_count:,} entries",
            "assistant": f"Hey Josh — assistant ready.\n\n🧠 Brain: {brain_count:,} entries\n\nWhat do you need?",
            "clerk": f"Clerk ready, Josh.\n\n🔗 {sum(len(v) for v in CLERK_LINKS.values()) if CLERK_LINKS else 0} links loaded\n\nWhat do you need?",
            "acardoor": f"Acardoor online, Josh.\n\n🔧 Systems improvement ready.\n\nWhat needs fixing or building?",
            "todolist": f"Productivity bot ready, Josh.\n\n✅ Let's get things done.\n\nWhat's on your list?"
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
        "bots": ["joshua", "assistant", "clerk", "acardoor", "todolist"]
    }, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================
# RUN ALL BOTS
# ============================================
async def run_all_bots():
    time.sleep(3)

    bots = [
        (TELEGRAM_TOKEN, "joshua", joshua_response),
        (ASSISTANT_TELEGRAM_TOKEN, "assistant", assistant_response),
        (CLERK_TELEGRAM_TOKEN, "clerk", clerk_response),
        (ACARDOOR_TELEGRAM_TOKEN, "acardoor", acardoor_response),
        (TODOLIST_TELEGRAM_TOKEN, "todolist", todolist_response),
    ]

    apps = []
    for token, name, response_func in bots:
        if not token:
            print(f"⚠️ Skipping {name} — no token", flush=True)
            continue
        app = Application.builder().token(token).build()
        # FIXED: No 'await' here - make_start returns a function, don't await it
        app.add_handler(CommandHandler("start", make_start(name, len(WORKING_BRAIN))))
        # FIXED: No 'await' here - make_handler returns a function, don't await it
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, make_handler(response_func, name)))
        app.add_error_handler(error_handler)
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print(f"🚀 {name} bot running", flush=True)
        apps.append(app)

    print(f"✅ {len(apps)} bots running", flush=True)

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
