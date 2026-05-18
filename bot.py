import os
import sys
import json
import asyncio
import threading
import requests
import time
import uuid
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

GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
CLOUDFLARE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://mldzkzrljaxudemfpbkh.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_TOKEN')

# ============================================
# PER-BOT R2 BUCKETS
# Each bot has its OWN memory bucket — nothing is shared
# ============================================
BOT_BUCKETS = {
    "joshua":    "joshuaroy",
    "assistant": "joshua1assistant",
    "clerk":     "clerk",
}

MEMORY_EXPIRY_DAYS = 90
AUTO_SUMMARY_THRESHOLD = 50

# ============================================
# IN-MEMORY STORES (per-bot, loaded at startup)
# ============================================
# Structure: { bot_name: [memory_entry, ...] }
BOT_MEMORIES = {
    "joshua":    [],
    "assistant": [],
    "clerk":     [],
}

# Conversation history per user per bot
# Structure: { bot_name: { user_id: [{"role": ..., "content": ...}, ...] } }
CONVERSATION_HISTORY = {
    "joshua":    {},
    "assistant": {},
    "clerk":     {},
}

MAX_HISTORY_TURNS = 20  # keep last 20 exchanges per user

# ============================================
# R2 HELPERS
# ============================================
def r2_get(bucket, key):
    try:
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/r2/buckets/{bucket}/objects/{key}"
        resp = requests.get(url, headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}, timeout=30)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception as e:
        print(f"❌ R2 get error [{bucket}/{key}]: {e}", flush=True)
        return None

def r2_put(bucket, key, data):
    try:
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/r2/buckets/{bucket}/objects/{key}"
        resp = requests.put(
            url,
            headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"},
            data=json.dumps(data, indent=2).encode("utf-8"),
            timeout=30
        )
        if resp.status_code not in (200, 204):
            print(f"❌ R2 put failed [{bucket}/{key}]: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"❌ R2 put error [{bucket}/{key}]: {e}", flush=True)

# ============================================
# LOAD / SAVE PER-BOT MEMORIES
# ============================================
def load_bot_memories(bot_name):
    bucket = BOT_BUCKETS[bot_name]
    raw = r2_get(bucket, "memories.json")
    if raw:
        try:
            BOT_MEMORIES[bot_name] = json.loads(raw)
            print(f"🧠 {bot_name}: {len(BOT_MEMORIES[bot_name])} memories loaded", flush=True)
        except Exception as e:
            print(f"❌ {bot_name} memory parse error: {e}", flush=True)
            BOT_MEMORIES[bot_name] = []
    else:
        BOT_MEMORIES[bot_name] = []
        print(f"🧠 {bot_name}: no existing memories", flush=True)

def save_bot_memories(bot_name):
    bucket = BOT_BUCKETS[bot_name]
    r2_put(bucket, "memories.json", BOT_MEMORIES[bot_name])
    print(f"💾 {bot_name}: {len(BOT_MEMORIES[bot_name])} memories saved", flush=True)

def load_all_memories():
    for bot_name in BOT_BUCKETS:
        load_bot_memories(bot_name)

# ============================================
# SUPABASE SEARCH (Big Brain — read only)
# ============================================
def supabase_search(query, limit=3):
    """Full-text search in Supabase for seminar content."""
    if not SUPABASE_KEY or not SUPABASE_URL:
        return []
    try:
        # Use Supabase full-text search on your existing table
        # Adjust 'seminar_content' and column names to match your actual table
        url = f"{SUPABASE_URL}/rest/v1/seminar_content"
        resp = requests.get(
            url,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
            },
            params={
                "select": "content,source",
                "content": f"fts.websearch_to_tsquery.{query}",
                "limit": limit,
            },
            timeout=10
        )
        if resp.status_code == 200:
            results = resp.json()
            return [r.get("content", "") for r in results if r.get("content")]
        else:
            print(f"⚠️ Supabase search returned {resp.status_code}", flush=True)
            return []
    except Exception as e:
        print(f"❌ Supabase search error: {e}", flush=True)
        return []

# ============================================
# SEMANTIC SEARCH (per-bot)
# ============================================
def semantic_search(query, bot_name, top_k=5):
    query_words = set(query.lower().split())
    scored = []
    for entry in BOT_MEMORIES[bot_name]:
        text = (entry.get("summary", "") + " " + entry.get("text", "")).lower()
        score = sum(1 for word in query_words if word in text)
        if score > 0:
            scored.append((score, entry))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [e for _, e in scored[:top_k]]

def get_context(message, bot_name, top_k=3):
    # Search bot's own R2 memories
    local_matches = semantic_search(message, bot_name, top_k=top_k)
    local_text = "\n\n".join([m.get("text", "") for m in local_matches])

    # Also search Supabase Big Brain for seminar content
    supabase_matches = supabase_search(message, limit=2)
    supabase_text = "\n\n".join(supabase_matches)

    combined = []
    if local_text:
        combined.append(f"[Your memories]\n{local_text}")
    if supabase_text:
        combined.append(f"[Seminar content]\n{supabase_text}")
    return "\n\n".join(combined)

# ============================================
# CONVERSATION HISTORY MANAGEMENT
# ============================================
def get_history(bot_name, user_id):
    return CONVERSATION_HISTORY[bot_name].get(str(user_id), [])

def add_to_history(bot_name, user_id, role, content):
    uid = str(user_id)
    if uid not in CONVERSATION_HISTORY[bot_name]:
        CONVERSATION_HISTORY[bot_name][uid] = []
    CONVERSATION_HISTORY[bot_name][uid].append({"role": role, "content": content})
    # Trim to last MAX_HISTORY_TURNS exchanges (each exchange = 2 messages)
    if len(CONVERSATION_HISTORY[bot_name][uid]) > MAX_HISTORY_TURNS * 2:
        CONVERSATION_HISTORY[bot_name][uid] = CONVERSATION_HISTORY[bot_name][uid][-(MAX_HISTORY_TURNS * 2):]

def clear_history(bot_name, user_id):
    CONVERSATION_HISTORY[bot_name][str(user_id)] = []

# ============================================
# MEMORY STORE / RECALL / DELETE
# ============================================
def store_memory(text, bot_name):
    """Store a memory in this bot's private bucket only."""
    memory_id = str(uuid.uuid4())[:8]  # stable unique ID, not an index
    entry = {
        "id": memory_id,
        "summary": text[:160],
        "text": text,
        "bot": bot_name,
        "ts": int(time.time()),
    }
    BOT_MEMORIES[bot_name].append(entry)
    save_bot_memories(bot_name)
    return memory_id

def delete_memory(memory_id, bot_name):
    """Delete by stable UUID, not by index."""
    original = len(BOT_MEMORIES[bot_name])
    BOT_MEMORIES[bot_name] = [m for m in BOT_MEMORIES[bot_name] if m.get("id") != memory_id]
    if len(BOT_MEMORIES[bot_name]) < original:
        save_bot_memories(bot_name)
        return True
    return False

def is_remember_intent(text):
    text = text.lower().strip()
    return (
        text.startswith("/remember") or
        any(p in text for p in ["remember this", "remember that", "save this", "note this", "don't forget"])
    )

def is_recall_intent(text):
    text = text.lower().strip()
    return (
        text.startswith(("/recall", "/search", "/find")) or
        any(p in text for p in ["tell me", "remind me", "what do you know about", "do you remember"])
    )

def extract_memory_content(text):
    """Strip command/trigger phrases, return just the content to remember."""
    result = text
    for cmd in ["/remember"]:
        result = result.replace(cmd, "")
    for phrase in ["remember this", "remember that", "save this", "note this", "don't forget"]:
        result = result.replace(phrase, "")
    return result.strip()

# ============================================
# CLEANUP
# ============================================
def cleanup_expired_memories(bot_name):
    expiry = int(time.time()) - (MEMORY_EXPIRY_DAYS * 24 * 3600)
    original = len(BOT_MEMORIES[bot_name])
    BOT_MEMORIES[bot_name] = [m for m in BOT_MEMORIES[bot_name] if m.get("ts", 0) >= expiry]
    removed = original - len(BOT_MEMORIES[bot_name])
    if removed:
        save_bot_memories(bot_name)
    return removed

# ============================================
# GROQ CALL (with conversation history)
# ============================================
def groq_call(system_prompt, conversation_history, max_tokens=400, temperature=0.7):
    """
    Pass the full conversation history so Groq has context across turns.
    conversation_history: list of {"role": "user"/"assistant", "content": "..."}
    """
    try:
        messages = [{"role": "system", "content": system_prompt}] + conversation_history
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=25
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        print(f"❌ Groq error: {resp.status_code} {resp.text[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"❌ Groq exception: {e}", flush=True)
        return None

# ============================================
# BOT SYSTEM PROMPTS
# ============================================
def joshua_system(context):
    return f"""You are Joshua Roy, an Australian Results Coach with 12+ years experience in NLP and Nervous System Reprogramming (NSR).

VOICE:
- Modern Brisbane Australian — grounded, direct, warm
- Never "G'day", "cobber", "bogan" or cartoon Aussie
- "mate" rarely, not every message
- Professional coach tone with real-world clarity
- Speak from genuine experience

EXPERTISE:
- NLP (Neuro-Linguistic Programming)
- Nervous System Reprogramming (NSR)
- Results coaching — practical, no fluff

RULES:
- 1-4 sentences unless deeper explanation is needed
- Direct and actionable
- Remember the full conversation — refer back to earlier points naturally

RELEVANT CONTEXT FROM YOUR SEMINARS AND MEMORY:
{context[:1500] if context else "None available."}"""

def assistant_system(context):
    return f"""You are Joshua Roy's personal AI assistant. You handle his internal operations.

STYLE:
- Direct, practical, efficient — no fluff
- Action-focused: tasks, planning, systems
- Australian English
- You remember the full conversation — refer back naturally

CAPABILITIES:
- Planning & drafting
- Task management
- Systems improvement
- Research and analysis

RELEVANT CONTEXT:
{context[:1500] if context else "None available."}"""

def clerk_system(context, links_str):
    return f"""You are the Clerk — no-nonsense admin assistant for Joshua Roy.

RESPONSIBILITIES:
- Find and provide links instantly from the library below
- Admin help: drafting, planning, organising
- Direct, no fluff, one-line descriptions with links
- You remember the full conversation — refer back naturally

LINK LIBRARY:
{links_str}

RELEVANT CONTEXT:
{context[:800] if context else "None available."}"""

# ============================================
# LOAD CLERK LINKS
# ============================================
def load_clerk_links():
    try:
        url = "https://raw.githubusercontent.com/accessworldseminars-ship-it/my-programs/main/clerk_links.json"
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Clerk links error: {e}", flush=True)
        return {}

CLERK_LINKS = load_clerk_links()

# ============================================
# COMMAND HANDLERS
# ============================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_name: str):
    mem_count = len(BOT_MEMORIES[bot_name])
    msgs = {
        "joshua":    f"Hey. Joshua Roy here. 🧠 I've got {mem_count} memories stored.\n/memories — see what I remember\n/forget <id> — delete a memory\n/clear — reset this conversation",
        "assistant": f"Assistant ready. {mem_count} memories available.\n/memories — see stored memories\n/forget <id> — delete a memory\n/clear — reset conversation",
        "clerk":     f"Clerk ready. {mem_count} memories. {sum(len(v) for v in CLERK_LINKS.values()) if CLERK_LINKS else 0} links loaded.\n/memories — see stored memories\n/forget <id> — delete",
    }
    await update.message.reply_text(msgs.get(bot_name, "Ready."))

async def cmd_memories(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_name: str):
    query = " ".join(context.args) if context.args else ""
    memories = BOT_MEMORIES[bot_name]

    if not memories:
        await update.message.reply_text(f"📭 No memories stored for {bot_name}.")
        return

    if query:
        results = semantic_search(query, bot_name, top_k=5)
        if not results:
            await update.message.reply_text(f"🔍 Nothing found for '{query}'.")
            return
        msg = f"🔍 Found {len(results)} match(es) for '{query}':\n\n"
        for m in results:
            msg += f"ID: {m['id']}\n{m['summary'][:100]}\n📅 {time.strftime('%Y-%m-%d', time.localtime(m['ts']))}\n\n"
    else:
        recent = memories[-10:]
        msg = f"🧠 {bot_name} memories ({len(memories)} total) — last 10:\n\n"
        for m in recent:
            msg += f"ID: {m['id']}\n{m['summary'][:100]}\n📅 {time.strftime('%Y-%m-%d', time.localtime(m['ts']))}\n\n"

    await update.message.reply_text(msg[:4000])

async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_name: str):
    if not context.args:
        await update.message.reply_text("Usage: /forget <memory-id>\nGet the ID from /memories")
        return
    memory_id = context.args[0]
    if delete_memory(memory_id, bot_name):
        await update.message.reply_text(f"🗑️ Deleted memory {memory_id}.")
    else:
        await update.message.reply_text(f"❌ No memory found with ID: {memory_id}")

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_name: str):
    """Reset conversation history for this user."""
    user_id = update.message.from_user.id
    clear_history(bot_name, user_id)
    await update.message.reply_text("🔄 Conversation reset. Fresh start.")

async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_name: str):
    removed = cleanup_expired_memories(bot_name)
    await update.message.reply_text(f"🗑️ Removed {removed} expired memories from {bot_name}.")

# ============================================
# MAIN MESSAGE HANDLER
# ============================================
def make_handlers(bot_name, response_func_name):
    """Returns (start, message_handler) coroutine functions for a given bot."""

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await cmd_start(update, context, bot_name)

    async def memories(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await cmd_memories(update, context, bot_name)

    async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await cmd_forget(update, context, bot_name)

    async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await cmd_clear(update, context, bot_name)

    async def cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await cmd_cleanup(update, context, bot_name)

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_text = update.message.text or ""
        user_id = update.message.from_user.id
        print(f"📨 [{bot_name}] user={user_id}: {user_text[:60]}", flush=True)
        await update.message.chat.send_action(action="typing")

        # --- 1. REMEMBER intent ---
        if is_remember_intent(user_text):
            content = extract_memory_content(user_text)
            if content:
                mem_id = store_memory(content, bot_name)
                await update.message.reply_text(f"✅ Remembered (ID: {mem_id}):\n{content[:100]}")
            else:
                await update.message.reply_text("What do you want me to remember? Just tell me.")
            return

        # --- 2. RECALL intent ---
        if is_recall_intent(user_text):
            query = user_text
            for cmd in ["/recall", "/search", "/find", "tell me", "remind me", "what do you know about", "do you remember"]:
                query = query.replace(cmd, "")
            query = query.replace("?", "").strip()
            results = semantic_search(query, bot_name, top_k=5) if query else BOT_MEMORIES[bot_name][-5:]
            if not results:
                await update.message.reply_text("🔍 Nothing stored on that.")
                return
            msg = f"🔍 {len(results)} result(s):\n\n"
            for m in results:
                msg += f"ID: {m['id']}\n{m['summary'][:120]}\n\n"
            await update.message.reply_text(msg[:4000])
            return

        # --- 3. NORMAL RESPONSE with context + history ---
        context_text = get_context(user_text, bot_name)
        history = get_history(bot_name, user_id)

        # Build system prompt based on bot type
        if bot_name == "joshua":
            system = joshua_system(context_text)
        elif bot_name == "assistant":
            system = assistant_system(context_text)
        else:
            system = clerk_system(context_text, json.dumps(CLERK_LINKS, indent=2))

        # Add user message to history BEFORE calling Groq
        add_to_history(bot_name, user_id, "user", user_text)
        updated_history = get_history(bot_name, user_id)

        response = groq_call(system, updated_history, max_tokens=400)
        if not response:
            response = "Something went wrong on my end. Try again."

        # Add assistant reply to history
        add_to_history(bot_name, user_id, "assistant", response)

        await update.message.reply_text(response[:4000])

    return start, handle_message, memories, forget, clear, cleanup

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
        "memories": {bot: len(mems) for bot, mems in BOT_MEMORIES.items()},
        "bots": list(BOT_BUCKETS.keys()),
    }, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================
# MAIN
# ============================================
async def run_all_bots():
    time.sleep(3)

    # Cleanup expired memories on startup
    for bot_name in BOT_BUCKETS:
        removed = cleanup_expired_memories(bot_name)
        if removed:
            print(f"🗑️ {bot_name}: removed {removed} expired memories", flush=True)

    bots = [
        (TELEGRAM_TOKEN,           "joshua"),
        (ASSISTANT_TELEGRAM_TOKEN, "assistant"),
        (CLERK_TELEGRAM_TOKEN,     "clerk"),
    ]

    apps = []
    for token, name in bots:
        if not token:
            print(f"⚠️ Skipping {name} — no token", flush=True)
            continue

        start_h, msg_h, mem_h, forget_h, clear_h, cleanup_h = make_handlers(name, name)

        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("start",    start_h))
        app.add_handler(CommandHandler("memories", mem_h))
        app.add_handler(CommandHandler("recall",   mem_h))
        app.add_handler(CommandHandler("search",   mem_h))
        app.add_handler(CommandHandler("forget",   forget_h))
        app.add_handler(CommandHandler("clear",    clear_h))
        app.add_handler(CommandHandler("cleanup",  cleanup_h))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_h))
        app.add_error_handler(error_handler)

        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print(f"🚀 {name} bot running — {len(BOT_MEMORIES[name])} memories", flush=True)
        apps.append(app)

    print(f"\n✅ {len(apps)} bots running", flush=True)
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing!", flush=True)
        sys.exit(1)

    load_all_memories()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)

    print("🚀 Starting bots...", flush=True)
    asyncio.run(run_all_bots())
