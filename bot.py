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

print("=== AccessWorld Bot Squad Starting (Advanced Memory) ===", flush=True)

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

# R2 Configuration
R2_BUCKET = "joshua-bot-brain"
R2_OBJECT = "working_brain_json"
TOPICS_OBJECT = "brain_topics.json"
SUMMARY_OBJECT = "brain_summaries.json"

# Per-bot workspace buckets
BOT_BUCKETS = {
    "joshua": "joshuaroy",
    "assistant": "joshua1assistant",
    "clerk": "clerk",
}

# Memory configuration
MEMORY_EXPIRY_DAYS = 90
AUTO_SUMMARY_THRESHOLD = 50

print(f"Joshua Bot: {'✅' if TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Assistant Bot: {'✅' if ASSISTANT_TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Clerk Bot: {'✅' if CLERK_TELEGRAM_TOKEN else '❌'}", flush=True)
print(f"Groq: {'✅' if GROQ_API_KEY else '❌'}", flush=True)

# ============================================
# R2 HELPERS
# ============================================
def r2_get_object(bucket, key):
    try:
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/r2/buckets/{bucket}/objects/{key}"
        resp = requests.get(url, headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}, timeout=30)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception as e:
        print(f"❌ R2 get error: {e}", flush=True)
        return None

def r2_put_object(bucket, key, data_bytes, content_type="application/json"):
    try:
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/r2/buckets/{bucket}/objects/{key}"
        resp = requests.put(url, headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": content_type}, data=data_bytes, timeout=30)
        if resp.status_code not in (200, 204):
            print(f"❌ R2 put failed: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"❌ R2 put error: {e}", flush=True)

# ============================================
# MEMORY STRUCTURES
# ============================================
WORKING_BRAIN = []
BRAIN_TOPICS = {}
BRAIN_SUMMARIES = []

def load_working_brain():
    global WORKING_BRAIN, BRAIN_TOPICS, BRAIN_SUMMARIES
    try:
        raw = r2_get_object(R2_BUCKET, R2_OBJECT)
        if raw:
            WORKING_BRAIN = json.loads(raw)
            print(f"🧠 Brain loaded: {len(WORKING_BRAIN)} entries", flush=True)
        
        topics_raw = r2_get_object(R2_BUCKET, TOPICS_OBJECT)
        if topics_raw:
            BRAIN_TOPICS = json.loads(topics_raw)
            print(f"📂 Topics loaded: {len(BRAIN_TOPICS)} categories", flush=True)
        
        summaries_raw = r2_get_object(R2_BUCKET, SUMMARY_OBJECT)
        if summaries_raw:
            BRAIN_SUMMARIES = json.loads(summaries_raw)
            print(f"📝 Summaries loaded: {len(BRAIN_SUMMARIES)}", flush=True)
    except Exception as e:
        print(f"❌ Brain error: {e}", flush=True)

def save_working_brain():
    try:
        r2_put_object(R2_BUCKET, R2_OBJECT, json.dumps(WORKING_BRAIN, indent=2).encode("utf-8"))
        r2_put_object(R2_BUCKET, TOPICS_OBJECT, json.dumps(BRAIN_TOPICS, indent=2).encode("utf-8"))
        r2_put_object(R2_BUCKET, SUMMARY_OBJECT, json.dumps(BRAIN_SUMMARIES, indent=2).encode("utf-8"))
        print(f"💾 Memory saved: {len(WORKING_BRAIN)} entries", flush=True)
    except Exception as e:
        print(f"❌ Save error: {e}", flush=True)

# ⭐ CRITICAL: Load brain BEFORE bots start
load_working_brain()

# ============================================
# SEMANTIC SEARCH
# ============================================
def semantic_search(query, top_k=5):
    query_words = set(query.lower().split())
    scored = []
    
    for entry in WORKING_BRAIN:
        summary = entry.get("summary", "").lower()
        text = entry.get("text", "").lower()
        combined = f"{summary} {text}"
        
        score = sum(1 for word in query_words if word in combined)
        
        for topic in entry.get("topics", []):
            if topic in query.lower():
                score += 3
        
        if score > 0:
            scored.append((score, entry))
    
    scored.sort(reverse=True, key=lambda x: x[0])
    return [e for _, e in scored[:top_k]]

# ============================================
# AUTO-SUMMARIZATION
# ============================================
def auto_summarize():
    if len(WORKING_BRAIN) > 0 and len(WORKING_BRAIN) % AUTO_SUMMARY_THRESHOLD == 0:
        print(f"📝 Auto-summarizing...", flush=True)
        recent = WORKING_BRAIN[-AUTO_SUMMARY_THRESHOLD:]
        summary_text = "\n".join([m.get("summary", "") for m in recent])
        
        prompt = f"Summarize these key memories into 3-5 bullet points:\n\n{summary_text}\n\nKey themes:"
        
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "max_tokens": 300},
                timeout=20
            )
            if resp.status_code == 200:
                summary = resp.json()["choices"][0]["message"]["content"].strip()
                BRAIN_SUMMARIES.append({
                    "timestamp": int(time.time()),
                    "memory_range": f"{len(WORKING_BRAIN) - AUTO_SUMMARY_THRESHOLD + 1}-{len(WORKING_BRAIN)}",
                    "summary": summary
                })
                save_working_brain()
        except Exception as e:
            print(f"❌ Auto-summarize error: {e}", flush=True)

# ============================================
# TOPIC EXTRACTION
# ============================================
def extract_topics(text):
    prompt = f"Extract 1-3 main topics from this text. Return ONLY comma-separated keywords:\n\nText: {text[:300]}\n\nTopics:"
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "max_tokens": 50, "temperature": 0.3},
            timeout=10
        )
        if resp.status_code == 200:
            topics_text = resp.json()["choices"][0]["message"]["content"].strip()
            return [t.strip().lower() for t in topics_text.split(",")[:3]]
    except Exception as e:
        print(f"❌ Topic extraction error: {e}", flush=True)
    return ["general"]

def add_to_topics(memory_id, topics):
    for topic in topics:
        if topic not in BRAIN_TOPICS:
            BRAIN_TOPICS[topic] = []
        if memory_id not in BRAIN_TOPICS[topic]:
            BRAIN_TOPICS[topic].append(memory_id)

# ============================================
# MEMORY EXPIRY
# ============================================
def cleanup_expired_memories():
    expiry_time = int(time.time()) - (MEMORY_EXPIRY_DAYS * 24 * 60 * 60)
    original_count = len(WORKING_BRAIN)
    
    WORKING_BRAIN[:] = [m for m in WORKING_BRAIN if m.get("ts", 0) >= expiry_time]
    
    for topic in list(BRAIN_TOPICS.keys()):
        BRAIN_TOPICS[topic] = [mid for mid in BRAIN_TOPICS[topic] 
                               if any(m.get("id") == mid for m in WORKING_BRAIN)]
        if not BRAIN_TOPICS[topic]:
            del BRAIN_TOPICS[topic]
    
    if len(WORKING_BRAIN) < original_count:
        save_working_brain()
        return original_count - len(WORKING_BRAIN)
    return 0

# ============================================
# AUTO-RECALL
# ============================================
def auto_recall(message):
    text = message.lower().strip()
    if len(text) < 10 or text.startswith("/"):
        return None
    
    recall_keywords = ["what", "how", "when", "where", "who", "why", "tell", "explain", "describe"]
    is_question = any(text.startswith(kw) for kw in recall_keywords) or "?" in text
    
    if is_question:
        relevant = semantic_search(text, top_k=3)
        if relevant:
            msg = "💡 **Related memory:**\n\n"
            for mem in relevant[:1]:
                msg += mem.get("summary", "")
            return msg
    return None

# ============================================
# PER-BOT WORKSPACE
# ============================================
def load_workspace(bucket):
    workspace = {}
    files = ["habits.json", "patterns.json", "workflows.json", "temp_prefs.json", "ongoing_projects.json"]
    for f in files:
        key = f"workspace/{f}"
        raw = r2_get_object(bucket, key)
        workspace[f] = json.loads(raw) if raw else []
    return workspace

def save_workspace(bucket, workspace):
    for filename, data in workspace.items():
        key = f"workspace/{filename}"
        r2_put_object(bucket, key, json.dumps(data, indent=2).encode("utf-8"))

def route_workspace_memory(message, workspace):
    text = message.lower()
    if "every day" in text or "i usually" in text:
        workspace["habits.json"].append({"text": message, "ts": int(time.time())})
        return "habits"
    if "i always" in text or "i tend to" in text:
        workspace["patterns.json"].append({"text": message, "ts": int(time.time())})
        return "patterns"
    if "step" in text or "process" in text or "workflow" in text:
        workspace["workflows.json"].append({"text": message, "ts": int(time.time())})
        return "workflows"
    if "for now" in text or "temporary" in text:
        workspace["temp_prefs.json"].append({"text": message, "ts": int(time.time())})
        return "temp_prefs"
    if "working on" in text or "project" in text:
        workspace["ongoing_projects.json"].append({"text": message, "ts": int(time.time())})
        return "ongoing_projects"
    return None

# ============================================
# STORE & RECALL
# ============================================
def store_in_working_brain(message, bot_name):
    text = message.lower().strip()
    
    is_remember_command = text.startswith("/remember")
    is_remember_phrase = any(phrase in text for phrase in ["remember this", "remember that", "save this", "note this", "don't forget"])
    
    if is_remember_command or is_remember_phrase:
        content = message
        if is_remember_command:
            content = content.replace("/remember", "").strip()
        for phrase in ["remember this", "remember that", "save this", "note this", "don't forget"]:
            content = content.replace(phrase, "").strip()
        if not content:
            content = message
        
        topics = extract_topics(content)
        memory_id = len(WORKING_BRAIN) + 1
        
        WORKING_BRAIN.append({
            "id": memory_id,
            "summary": content[:160],
            "text": content,
            "source_bot": bot_name,
            "ts": int(time.time()),
            "topics": topics,
            "access_count": 0
        })
        add_to_topics(memory_id, topics)
        save_working_brain()
        auto_summarize()
        return content
    return False

def recall_from_working_brain(message, bot_name):
    text = message.lower().strip()
    
    is_recall_command = text.startswith(("/recall", "/search", "/find"))
    is_ask_phrase = any(phrase in text for phrase in ["tell me", "remind me", "what do you know about", "do you remember"])
    
    if not (is_recall_command or is_ask_phrase):
        return None
    
    query = message
    for cmd in ["/recall", "/search", "/find"]:
        query = query.replace(cmd, "").strip()
    for phrase in ["tell me", "remind me", "what do you know about", "do you remember"]:
        query = query.replace(phrase, "").strip()
    query = query.replace("?", "").strip()
    
    if not query:
        recent = WORKING_BRAIN[-5:] if WORKING_BRAIN else []
        if not recent:
            return "📭 No memories stored yet."
        msg = "📋 **Recent memories:**\n\n"
        for i, m in enumerate(recent, 1):
            msg += f"{i}. {m.get('summary', '')}\n"
        return msg
    
    matches = semantic_search(query, top_k=5)
    if not matches:
        return f"🔍 Nothing found about '{query}'."
    
    for m in matches:
        m["access_count"] = m.get("access_count", 0) + 1
    save_working_brain()
    
    msg = f"🔍 **Found {len(matches)} memory(ies):**\n\n"
    for i, m in enumerate(matches, 1):
        msg += f"{i}. {m.get('summary', '')}\n\n"
    return msg

def get_context(message, top_k=3):
    matches = semantic_search(message, top_k=top_k)
    return "\n\n".join([m.get("text", "") for m in matches]) if matches else ""

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
# GROQ CALL
# ============================================
def groq_call(prompt, max_tokens=300, temperature=0.7):
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": temperature},
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        return None
    except Exception as e:
        print(f"❌ Groq error: {e}", flush=True)
        return None

# ============================================
# BOT RESPONSES
# ============================================
def joshua_response(message):
    context = get_context(message, top_k=3)
    prompt = Speak in Joshua’s real voice:
- modern Australian English
- city Aussie, not country/NT slang
- no “G’day”, “how ya goin’”, “mate”, “cobber”, or cartoon Aussie phrases
- natural, grounded, direct
- warm but not cheesy
- conversational but not slangy
- professional coach tone with real-world clarity
- talk like a normal Australian who lives in Brisbane, not a stereotype
- use "mate" and "ya" very rarely keep it 98% professional

Context: {context[:1000]}

User: {message}
Joshua:"""
    return groq_call(prompt) or "Tell me more about that."

def assistant_response(message):
    context = get_context(message, top_k=5)
    prompt = f"""You are Joshua's AI assistant. Direct, practical, efficient.

Context: {context[:1500]}

Joshua: {message}
Assistant:"""
    return groq_call(prompt, max_tokens=500, temperature=0.5) or "On it."

def clerk_response(message):
    context = get_context(message, top_k=3)
    links_str = json.dumps(CLERK_LINKS, indent=2)
    prompt = f"""You are the Clerk. You have Joshua's link library.

LINKS: {links_str}
CONTEXT: {context[:800]}

Joshua: {message}
Clerk:"""
    return groq_call(prompt, max_tokens=600, temperature=0.3) or "On it."

# ============================================
# COMMAND HANDLERS
# ============================================
async def show_memories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else ""
    if query:
        result = recall_from_working_brain(f"/search {query}", "system")
        await update.message.reply_text(result[:4000] if result else f"No memories found")
        return
    
    if not WORKING_BRAIN:
        await update.message.reply_text("📭 No memories yet.")
        return
    
    recent = WORKING_BRAIN[-10:]
    msg = f"🧠 **Memory Vault ({len(WORKING_BRAIN)} total)**\n\n"
    for i, m in enumerate(recent, 1):
        msg += f"{i}. {m.get('summary', '')[:80]}\n"
        msg += f"   📅 {time.strftime('%Y-%m-%d', time.localtime(m.get('ts', 0)))}\n"
        if m.get("topics"):
            msg += f"   📂 {', '.join(m.get('topics', []))}\n"
        msg += "\n"
    await update.message.reply_text(msg[:4000])

async def show_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BRAIN_TOPICS:
        await update.message.reply_text("📂 No topics yet.")
        return
    
    msg = "📂 **Topics:**\n\n"
    for topic, count in sorted(BRAIN_TOPICS.items(), key=lambda x: x[1], reverse=True):
        msg += f"• {topic}: {count} memories\n"
    await update.message.reply_text(msg[:4000])

async def show_summaries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BRAIN_SUMMARIES:
        await update.message.reply_text("📝 No summaries yet.")
        return
    
    msg = "📝 **Auto-Summaries**\n\n"
    for s in BRAIN_SUMMARIES[-5:]:
        msg += f"📅 {time.strftime('%Y-%m-%d', time.localtime(s.get('timestamp', 0)))}\n"
        msg += f"{s.get('summary', '')}\n\n"
    await update.message.reply_text(msg[:4000])

async def memory_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"📊 **Memory Stats**\n\n"
    msg += f"🧠 Entries: {len(WORKING_BRAIN)}\n"
    msg += f"📂 Topics: {len(BRAIN_TOPICS)}\n"
    msg += f"📝 Summaries: {len(BRAIN_SUMMARIES)}\n"
    msg += f"🗑️ Expiry: {MEMORY_EXPIRY_DAYS} days\n"
    await update.message.reply_text(msg)

async def forget_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /forget <number>")
        return
    
    try:
        index = int(context.args[0]) - 1
        if 0 <= index < len(WORKING_BRAIN):
            removed = WORKING_BRAIN.pop(index)
            save_working_brain()
            await update.message.reply_text(f"🗑️ Forgot: {removed.get('summary', '')[:100]}")
        else:
            await update.message.reply_text("Invalid index.")
    except ValueError:
        await update.message.reply_text("Usage: /forget <number>")

async def cleanup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deleted = cleanup_expired_memories()
    await update.message.reply_text(f"🗑️ Cleaned up {deleted} expired memories.")

# ============================================
# TELEGRAM HANDLERS
# ============================================
def make_start(bot_name):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        messages = {
            "joshua": f"Hey, it's Josh. 🧠 {len(WORKING_BRAIN)} memories\n/topics - Browse topics\n/summaries - View summaries",
            "assistant": f"Assistant ready. 🧠 {len(WORKING_BRAIN)} memories available",
            "clerk": f"Clerk ready. 🔗 {sum(len(v) for v in CLERK_LINKS.values()) if CLERK_LINKS else 0} links"
        }
        await update.message.reply_text(messages.get(bot_name, "Ready."))
    return start

def make_handler(response_func, bot_name):
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_text = update.message.text or ""
        print(f"📨 {bot_name}: {user_text[:50]}", flush=True)
        await update.message.chat.send_action(action="typing")
        
        # 1. RECALL (explicit)
        recall_result = recall_from_working_brain(user_text, bot_name)
        if recall_result:
            await update.message.reply_text(recall_result[:4000])
            return
        
        # 2. AUTO-RECALL (implicit)
        auto_result = auto_recall(user_text)
        if auto_result:
            await update.message.reply_text(auto_result[:4000])
            return
        
        # 3. STORE
        stored = store_in_working_brain(user_text, bot_name)
        if stored:
            await update.message.reply_text(f"✅ I'll remember: {stored[:100]}")
            return
        
        # 4. NORMAL RESPONSE
        response = response_func(user_text)
        await update.message.reply_text(response[:4000])
        
        # 5. WORKSPACE MEMORY
        bucket = BOT_BUCKETS.get(bot_name)
        if bucket:
            workspace = load_workspace(bucket)
            if route_workspace_memory(user_text, workspace):
                save_workspace(bucket, workspace)
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
        "topics": len(BRAIN_TOPICS),
        "summaries": len(BRAIN_SUMMARIES),
        "bots": ["joshua", "assistant", "clerk"],
        "features": ["semantic_search", "auto_summaries", "topic_folders", "auto_recall", "memory_expiry"]
    }, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================
# MAIN - RUN ALL BOTS
# ============================================
async def run_all_bots():
    time.sleep(3)
    cleanup_expired_memories()
    
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
        
        # Add command handlers
        app.add_handler(CommandHandler("start", make_start(name)))
        app.add_handler(CommandHandler("memories", show_memories))
        app.add_handler(CommandHandler("recall", show_memories))
        app.add_handler(CommandHandler("search", show_memories))
        app.add_handler(CommandHandler("topics", show_topics))
        app.add_handler(CommandHandler("summaries", show_summaries))
        app.add_handler(CommandHandler("stats", memory_stats))
        app.add_handler(CommandHandler("forget", forget_memory))
        app.add_handler(CommandHandler("cleanup", cleanup_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, make_handler(response_func, name)))
        app.add_error_handler(error_handler)
        
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print(f"🚀 {name} bot running", flush=True)
        apps.append(app)
    
    print(f"\n✅ {len(apps)} bots running with ADVANCED MEMORY", flush=True)
    print(f"🧠 Working Brain: {len(WORKING_BRAIN)} memories", flush=True)
    print(f"📂 Topics: {len(BRAIN_TOPICS)} categories", flush=True)
    print(f"📝 Summaries: {len(BRAIN_SUMMARIES)}", flush=True)
    
    while True:
        await asyncio.sleep(1)

# ============================================
# ENTRY POINT
# ============================================
if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing!", flush=True)
        sys.exit(1)
    
    # Start Flask health check in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)
    
    print("🚀 Starting advanced memory system...", flush=True)
    asyncio.run(run_all_bots())
