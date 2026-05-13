import os
import sys
import json
import asyncio
import threading
import requests
import urllib.request
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import time

print("=== AccessWorld Bot Squad Starting ===", flush=True)

# ============================================
# ENVIRONMENT
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ASSISTANT_TELEGRAM_TOKEN = os.environ.get('ASSISTANT_TELEGRAM_TOKEN')
CLERK_TELEGRAM_TOKEN = os.environ.get('CLERK_TELEGRAM_TOKEN')
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
            print(f"🧠 Brain loaded: {len(brain)} entries", flush=True)
            return brain
        print(f"❌ R2 load failed: {resp.status_code}", flush=True)
        return []
    except Exception as e:
        print(f"❌ Brain load error: {e}", flush=True)
        return []

WORKING_BRAIN = load_working_brain()

# ============================================
# LOAD CLERK LINKS FROM GITHUB REPO
# ============================================
# CORRECTED URL - pointing to the raw file in my-programs repo
CLERK_LINKS_URL = "https://raw.githubusercontent.com/accessworldseminars-ship-it/my-programs/main/clerk_links.json"

def load_clerk_links():
    try:
        print(f"🔗 Loading clerk links from: {CLERK_LINKS_URL}", flush=True)
        with urllib.request.urlopen(CLERK_LINKS_URL, timeout=15) as response:
            links = json.loads(response.read().decode())
            total_links = sum(len(v) for v in links.values()) if isinstance(links, dict) else 0
            print(f"🔗 Clerk links loaded successfully: {total_links} links across {len(links)} categories", flush=True)
            return links
    except urllib.error.HTTPError as e:
        print(f"❌ Clerk links HTTP error: {e.code} - {e.reason}", flush=True)
        return {}
    except urllib.error.URLError as e:
        print(f"❌ Clerk links URL error: {e.reason}", flush=True)
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ Clerk links JSON parse error: {e}", flush=True)
        return {}
    except Exception as e:
        print(f"❌ Clerk links error: {e}", flush=True)
        return {}

CLERK_LINKS = load_clerk_links()

# ============================================
# SHARED FUNCTIONS
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
    matches = search_working_brain(message, top_k=top_k)
    context_parts = []
    for match in matches:
        full_text = fetch_full_entry(match["id"])
        if full_text:
            context_parts.append(full_text)
    return "\n\n".join(context_parts) if context_parts else ""

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
        print(f"❌ Groq status: {resp.status_code} - {resp.text}", flush=True)
        return None
    except Exception as e:
        print(f"❌ Groq error: {e}", flush=True)
        return None

# ============================================
# JOSHUA ROY BOT - NATURAL & DIRECT
# ============================================
def joshua_response(message):
    context = get_context(message, top_k=3)
    prompt = f"""You are Joshua Roy, an Australian Results Coach with 12 years experience.
You specialise in NLP and Nervous System Reprogramming (NSR).

IMPORTANT - Your speaking style:
- Speak plain, natural English
- NEVER use "mate" or "fair dinkum" or any stereotypical Aussie slang
- Just be warm, direct, and straight to the point
- 1-3 sentences unless more is truly needed
- Sound like a professional coach

Context from your seminars:
{context[:1000]}

User: {message}
Joshua:"""
    return groq_call(prompt, max_tokens=300, temperature=0.7) or "Tell me more about that."

# ============================================
# ASSISTANT BOT - PRACTICAL & EFFICIENT
# ============================================
def assistant_response(message):
    context = get_context(message, top_k=5)
    prompt = f"""You are a sharp personal assistant to Joshua Roy, an Australian Results Coach
specialising in NLP and Nervous System Reprogramming (NSR).
You know his entire body of seminar content, coaching methodology, and business (AccessWorld Seminars).

IMPORTANT - Your speaking style:
- Professional, direct, and efficient
- No slang or casual Australian expressions
- Just help him plan sessions, organise content, draft copy, brainstorm ideas
- Be practical and get straight to the point

Relevant content from his seminars:
{context[:1500]}

Joshua: {message}
Assistant:"""
    return groq_call(prompt, max_tokens=500, temperature=0.5) or "Something went wrong, try again."

# ============================================
# CLERK BOT - LINK & ADMIN ASSISTANT
# ============================================
def clerk_response(message):
    context = get_context(message, top_k=5)
    
    links_str = json.dumps(CLERK_LINKS, indent=2)
    
    prompt = f"""You are the Clerk — a sharp, no-nonsense personal admin assistant for Joshua Roy,
founder of AccessWorld Seminars in Brisbane, Australia.

You have access to ALL of Joshua's business links, resources, and tools below.
When Joshua asks for a link, find the right one and give it to him instantly.
When he asks for help with admin, drafting, planning, or organising — get it done.

YOUR COMPLETE LINK LIBRARY (from my-programs/clerk_links.json):
{links_str[:3500]}

RELEVANT KNOWLEDGE:
{context[:800]}

Be direct. No fluff. If he asks for a link — give just the link and a one-line description.
If he asks for help with a task — do it efficiently.

Joshua: {message}
Clerk:"""
    return groq_call(prompt, max_tokens=600, temperature=0.3) or "On it — try again in a moment."

# ============================================
# TELEGRAM HANDLERS - JOSHUA BOT
# ============================================
async def joshua_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Hey, Joshua here. What's on your mind?\n\n🧠 Brain loaded: {len(WORKING_BRAIN):,} entries\n🤖 Model: Llama 3.3 70B"
    )

async def joshua_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📨 Joshua Bot: {update.message.text[:50]}", flush=True)
    await update.message.chat.send_action(action="typing")
    response = joshua_response(update.message.text)
    await update.message.reply_text(response[:4000])
    print("✅ Joshua replied", flush=True)

# ============================================
# TELEGRAM HANDLERS - ASSISTANT BOT
# ============================================
async def assistant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Assistant ready. What do you need?\n\n🧠 Brain loaded: {len(WORKING_BRAIN):,} entries\n🤖 Model: Llama 3.3 70B"
    )

async def assistant_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📨 Assistant Bot: {update.message.text[:50]}", flush=True)
    await update.message.chat.send_action(action="typing")
    response = assistant_response(update.message.text)
    await update.message.reply_text(response[:4000])
    print("✅ Assistant replied", flush=True)

# ============================================
# TELEGRAM HANDLERS - CLERK BOT
# ============================================
async def clerk_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_links = sum(len(v) for v in CLERK_LINKS.values()) if isinstance(CLERK_LINKS, dict) else 0
    categories = len(CLERK_LINKS) if isinstance(CLERK_LINKS, dict) else 0
    await update.message.reply_text(
        f"Clerk ready, Josh.\n\n"
        f"Ask me for any link, help with admin, drafting, planning — whatever you need.\n\n"
        f"🔗 {total_links} links across {categories} categories\n"
        f"📁 Source: my-programs/clerk_links.json\n"
        f"🤖 Model: Llama 3.3 70B"
    )

async def clerk_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📨 Clerk Bot: {update.message.text[:50]}", flush=True)
    await update.message.chat.send_action(action="typing")
    response = clerk_response(update.message.text)
    await update.message.reply_text(response[:4000])
    print("✅ Clerk replied", flush=True)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ Error: {context.error}", flush=True)

# ============================================
# FLASK HEALTH ENDPOINT
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    total_links = sum(len(v) for v in CLERK_LINKS.values()) if isinstance(CLERK_LINKS, dict) else 0
    categories = len(CLERK_LINKS) if isinstance(CLERK_LINKS, dict) else 0
    return {
        "status": "healthy",
        "brain_entries": len(WORKING_BRAIN),
        "model": "llama-3.3-70b-versatile",
        "bots": ["joshua", "assistant", "clerk"],
        "clerk": {
            "links": total_links,
            "categories": categories,
            "source": "my-programs/clerk_links.json"
        }
    }, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================
# RUN ALL THREE BOTS
# ============================================
async def run_all_bots():
    time.sleep(3)

    # Joshua Bot
    joshua_app = Application.builder().token(TELEGRAM_TOKEN).build()
    joshua_app.add_handler(CommandHandler("start", joshua_start))
    joshua_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, joshua_message))
    joshua_app.add_error_handler(error_handler)

    # Assistant Bot
    assistant_app = Application.builder().token(ASSISTANT_TELEGRAM_TOKEN).build()
    assistant_app.add_handler(CommandHandler("start", assistant_start))
    assistant_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, assistant_message))
    assistant_app.add_error_handler(error_handler)

    # Clerk Bot
    clerk_app = Application.builder().token(CLERK_TELEGRAM_TOKEN).build()
    clerk_app.add_handler(CommandHandler("start", clerk_start))
    clerk_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, clerk_message))
    clerk_app.add_error_handler(error_handler)

    # Clear webhooks
    await joshua_app.bot.delete_webhook(drop_pending_updates=True)
    await assistant_app.bot.delete_webhook(drop_pending_updates=True)
    await clerk_app.bot.delete_webhook(drop_pending_updates=True)

    # Initialise all
    await joshua_app.initialize()
    await assistant_app.initialize()
    await clerk_app.initialize()

    await joshua_app.start()
    await assistant_app.start()
    await clerk_app.start()

    # Start polling all
    await joshua_app.updater.start_polling(drop_pending_updates=True)
    await assistant_app.updater.start_polling(drop_pending_updates=True)
    await clerk_app.updater.start_polling(drop_pending_updates=True)

    print("🚀 All three bots running with Llama 3.3 70B!", flush=True)
    print(f"   - Joshua: coaching bot", flush=True)
    print(f"   - Assistant: planning & drafting bot", flush=True)
    print(f"   - Clerk: links & admin bot (from my-programs/clerk_links.json)", flush=True)

    # Keep alive
    while True:
        await asyncio.sleep(1)

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!", flush=True)
        sys.exit(1)
    if not ASSISTANT_TELEGRAM_TOKEN:
        print("❌ ASSISTANT_TELEGRAM_TOKEN not set!", flush=True)
        sys.exit(1)
    if not CLERK_TELEGRAM_TOKEN:
        print("❌ CLERK_TELEGRAM_TOKEN not set!", flush=True)
        sys.exit(1)

    print("🌐 Starting Flask...", flush=True)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)

    print("🚀 Starting all three bots...", flush=True)
    asyncio.run(run_all_bots())
