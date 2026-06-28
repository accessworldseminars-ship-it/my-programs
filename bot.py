import os
import sys
import json
import asyncio
import threading
import requests
import time
import uuid
import urllib.request
import re
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from datetime import datetime

print("=== AccessWorld Bot Squad Starting ===", flush=True)

# ============================================
# ENVIRONMENT
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ASSISTANT_TELEGRAM_TOKEN = os.environ.get('ASSISTANT_TELEGRAM_TOKEN')
CLERK_TELEGRAM_TOKEN = os.environ.get('CLERK_TELEGRAM_TOKEN')

GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
CLOUDFLARE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')

# ============================================
# PER-BOT R2 BUCKETS
# ============================================
BOT_BUCKETS = {
    "joshua":    "joshuaroy",
    "assistant": "joshua1assistant",
    "clerk":     "clerk",
}

BRAIN_BUCKET = "joshua-bot-brain"
BRAIN_INDEX_KEY = "working_brain_json"
BRAIN_FULL_KEY = "joshua_brain_full.json"

MEMORY_EXPIRY_DAYS = 90
AUTO_SUMMARY_THRESHOLD = 50
MAX_CONTEXT_MESSAGES = 15   # number of recent messages to keep in context

# ============================================
# IN-MEMORY STORES (for the "memories" command – separate notes)
# ============================================
BOT_MEMORIES = {
    "joshua":    [],
    "assistant": [],
    "clerk":     [],
}

# Big Brain loaded at startup
WORKING_BRAIN_INDEX = []   # list of {id, summary} for keyword search
FULL_BRAIN = {}            # dict of {id: text} for full retrieval

# ============================================
# R2 HELPERS (S3-Compatible API)
# ============================================
def get_r2_client():
    """Return S3-compatible R2 client"""
    return boto3.client(
        's3',
        endpoint_url=f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ.get('R2_ACCESS_KEY'),
        aws_secret_access_key=os.environ.get('R2_SECRET_KEY'),
        region_name='auto',
        config=Config(signature_version='s3v4')
    )

def r2_get(bucket, key):
    """Read object from R2 bucket"""
    try:
        s3 = get_r2_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print(f"⚠️ Key not found: {bucket}/{key}", flush=True)
        else:
            print(f"❌ R2 get error [{bucket}/{key}]: {e}", flush=True)
        return None
    except Exception as e:
        print(f"❌ R2 get error [{bucket}/{key}]: {e}", flush=True)
        return None

def r2_put(bucket, key, data):
    """Write object to R2 bucket"""
    try:
        s3 = get_r2_client()
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(data, indent=2).encode('utf-8'),
            ContentType='application/json'
        )
        print(f"✅ R2 put success: {bucket}/{key}", flush=True)
        return True
    except Exception as e:
        print(f"❌ R2 put error [{bucket}/{key}]: {e}", flush=True)
        return False

# ============================================
# PER-USER MEMORY CLASS
# ============================================
class UserMemory:
    def __init__(self, bot_name, user_id, r2_client, bucket):
        self.bot_name = bot_name
        self.user_id = str(user_id)
        self.r2 = r2_client
        self.bucket = bucket
        self.key = f"user_{self.user_id}.json"
        self.data = self._load()
        self.dirty = False  # track if we need to save

    def _load(self):
        raw = r2_get(self.bucket, self.key)
        if raw:
            try:
                return json.loads(raw)
            except Exception as e:
                print(f"❌ Error parsing user memory {self.key}: {e}", flush=True)
                # fallback to empty
                return self._empty_data()
        return self._empty_data()

    def _empty_data(self):
        return {
            "user_id": self.user_id,
            "summary": "",
            "history": [],
            "last_updated": datetime.utcnow().isoformat()
        }

    def save(self):
        if self.dirty:
            self.data["last_updated"] = datetime.utcnow().isoformat()
            r2_put(self.bucket, self.key, self.data)
            self.dirty = False

    def add_message(self, role, content):
        self.data["history"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        self.dirty = True
        # Check if we need to summarize
        if len(self.data["history"]) > AUTO_SUMMARY_THRESHOLD:
            self._summarize()
        self.save()

    def _summarize(self):
        """Summarize the oldest half of history, keep only the recent half."""
        history = self.data["history"]
        mid = len(history) // 2
        old_part = history[:mid]
        new_part = history[mid:]

        # Build a text to summarize
        conversation_text = "\n".join([f"{m['role']}: {m['content']}" for m in old_part])
        summary_prompt = (
            "You are a summarization assistant. Condense the following conversation into a concise paragraph (max 100 words) "
            "that captures key topics, user goals, and important details. Keep the summary neutral and factual."
        )
        # Call Groq (synchronous for simplicity)
        summary = self._call_groq_summary(summary_prompt, conversation_text)
        if summary:
            # Prepend new summary to existing summary
            if self.data["summary"]:
                self.data["summary"] = summary + "\n\n" + self.data["summary"]
            else:
                self.data["summary"] = summary
            self.data["history"] = new_part
            self.dirty = True
            print(f"🧠 {self.bot_name} user {self.user_id}: summarized {len(old_part)} messages", flush=True)

    def _call_groq_summary(self, system_prompt, user_text):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Summarize this conversation:\n\n{user_text}"}
                    ],
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
                timeout=25
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"❌ Groq summary error: {e}", flush=True)
        return None

    def get_context(self, limit=MAX_CONTEXT_MESSAGES):
        """Return summary + last `limit` messages as a string for the LLM prompt."""
        parts = []
        if self.data["summary"]:
            parts.append(f"📝 Previous summary: {self.data['summary']}\n")
        recent = self.data["history"][-limit:]
        if recent:
            parts.append("Recent conversation:")
            for msg in recent:
                parts.append(f"{msg['role'].capitalize()}: {msg['content']}")
        return "\n".join(parts)

# ============================================
# LOAD BIG BRAIN FROM R2
# ============================================
def load_big_brain():
    global WORKING_BRAIN_INDEX, FULL_BRAIN

    print("🧠 Loading Working Brain index from R2...", flush=True)
    raw_index = r2_get(BRAIN_BUCKET, BRAIN_INDEX_KEY)
    if raw_index:
        try:
            WORKING_BRAIN_INDEX = json.loads(raw_index)
            print(f"✅ Working Brain: {len(WORKING_BRAIN_INDEX)} entries", flush=True)
        except Exception as e:
            print(f"❌ Working Brain parse error: {e}", flush=True)
    else:
        print("⚠️ Working Brain index not found in R2", flush=True)

    print("🧠 Loading Full Brain from R2...", flush=True)
    raw_full = r2_get(BRAIN_BUCKET, BRAIN_FULL_KEY)
    if raw_full:
        try:
            FULL_BRAIN = json.loads(raw_full)
            print(f"✅ Full Brain: {len(FULL_BRAIN)} entries loaded", flush=True)
        except Exception as e:
            print(f"❌ Full Brain parse error: {e}", flush=True)
    else:
        print("⚠️ Full Brain not found in R2", flush=True)

# ============================================
# BIG BRAIN SEARCH
# ============================================
def brain_search(query, top_k=3):
    """Keyword search the Working Brain index, then retrieve full text."""
    if not WORKING_BRAIN_INDEX:
        return []

    query_words = set(query.lower().split())
    scored = []

    for entry in WORKING_BRAIN_INDEX:
        summary = entry.get("summary", "").lower()
        score = sum(1 for word in query_words if word in summary)
        if score > 0:
            scored.append((score, entry))

    scored.sort(reverse=True, key=lambda x: x[0])
    top = scored[:top_k]

    # Retrieve full text from FULL_BRAIN dict
    results = []
    for _, entry in top:
        entry_id = str(entry.get("id", ""))
        full_text = FULL_BRAIN.get(entry_id, entry.get("summary", ""))
        results.append(full_text)

    return results

# ============================================
# LOAD / SAVE PER-BOT MEMORIES (for notes)
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
# SEMANTIC SEARCH (per-bot memories – notes)
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

def get_context(message, bot_name, user_memory, top_k=3):
    # Search bot's own R2 memories (notes)
    local_matches = semantic_search(message, bot_name, top_k=top_k)
    local_text = "\n\n".join([m.get("text", "") for m in local_matches])

    # Search Big Brain from R2
    brain_matches = brain_search(message, top_k=3)
    brain_text = "\n\n".join(brain_matches)

    combined = []
    if local_text:
        combined.append(f"[Your notes]\n{local_text}")
    if brain_text:
        combined.append(f"[Seminar content]\n{brain_text}")

    # Add per-user conversation context
    conv_context = user_memory.get_context()
    if conv_context:
        combined.append(f"[Conversation history]\n{conv_context}")

    return "\n\n".join(combined)

# ============================================
# MEMORY STORE / RECALL / DELETE (for notes)
# ============================================
def store_memory(text, bot_name):
    memory_id = str(uuid.uuid4())[:8]
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
    result = text
    for cmd in ["/remember"]:
        result = result.replace(cmd, "")
    for phrase in ["remember this", "remember that", "save this", "note this", "don't forget"]:
        result = result.replace(phrase, "")
    return result.strip()

# ============================================
# CLEANUP (for notes, not conversation history)
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
# GROQ CALL
# ============================================
def groq_call(system_prompt, conversation_history, max_tokens=400, temperature=0.7):
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
# BOT SYSTEM PROMPTS (CLEAN, PROFESSIONAL VERSION)
# ============================================
def joshua_system(context):
    return f"""You operate under the strict persona of Joshua Roy, a high-level Results Coach based in Brisbane with 12+ years of professional experience in Neuro-Linguistic Programming (NLP) and Nervous System Reprogramming (NSR).

VOICE & DIALECT CONSTRAINTS:
- Use clear, professional, elite corporate and executive coaching language.
- Your dialect is standard, articulate corporate Commonwealth English (Brisbane metro).
- SYSTEM BAN: You are strictly penalized if you use the words "G'day", "mate", "crikey", "cobber", "chook", "outback", "bogan", or any colloquial slang.
- If you feel tempted to use a stereotypical greeting, use "Hey", "Hi", or jump straight into the coaching observation.
- Speak with grounded, practical, real-world clarity—focused entirely on shifting unconscious resistance and self-sabotage.

RESPONSE STYLE:
- Keep answers tightly focused: 1-4 sentences unless a deep tactical breakdown of a coaching framework is required.
- Direct, empathetic, and highly actionable.
- Remember the full conversation — refer back to earlier points naturally.

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
        "joshua":    f"Hey. Joshua Roy here. 🧠 {mem_count} notes stored. Big Brain: {len(FULL_BRAIN)} entries.\n/memories — see what I remember\n/forget <id> — delete a memory\n/clear — reset this conversation",
        "assistant": f"Assistant ready. {mem_count} notes available.\n/memories — see stored memories\n/forget <id> — delete a memory\n/clear — reset conversation",
        "clerk":     f"Clerk ready. {mem_count} notes. {sum(len(v) for v in CLERK_LINKS.values()) if CLERK_LINKS else 0} links loaded.\n/memories — see stored memories\n/forget <id> — delete",
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
    # Clear the per-user conversation history
    user_id = update.message.from_user.id
    # We'll simply delete the user's file or reset it
    bucket = BOT_BUCKETS[bot_name]
    key = f"user_{user_id}.json"
    # Delete the file if it exists
    try:
        s3 = get_r2_client()
        s3.delete_object(Bucket=bucket, Key=key)
        await update.message.reply_text("🔄 Conversation reset. Fresh start.")
    except Exception as e:
        await update.message.reply_text("Couldn't clear history, but I'll start fresh anyway.")
        # fallback: we can't delete, but we can force a new memory object next time

async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_name: str):
    removed = cleanup_expired_memories(bot_name)
    await update.message.reply_text(f"🗑️ Removed {removed} expired memories from {bot_name}.")

# ============================================
# MAIN MESSAGE HANDLER (WITH BRUTE FORCE SLANG INTERCEPTOR)
# ============================================
def make_handlers(bot_name, response_func_name):

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

        # ---- Handle /remember and /recall (notes) ----
        if is_remember_intent(user_text):
            content = extract_memory_content(user_text)
            if content:
                mem_id = store_memory(content, bot_name)
                await update.message.reply_text(f"✅ Remembered (ID: {mem_id}):\n{content[:100]}")
            else:
                await update.message.reply_text("What do you want me to remember? Just tell me.")
            return

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

        # ---- PER-USER CONVERSATION MEMORY ----
        bucket = BOT_BUCKETS[bot_name]
        r2 = get_r2_client()
        user_memory = UserMemory(bot_name, user_id, r2, bucket)

        # Add user message to history
        user_memory.add_message("user", user_text)

        # Build context for LLM
        context_text = get_context(user_text, bot_name, user_memory)

        # Build system prompt
        if bot_name == "joshua":
            system = joshua_system(context_text)
        elif bot_name == "assistant":
            system = assistant_system(context_text)
        else:
            system = clerk_system(context_text, json.dumps(CLERK_LINKS, indent=2))

        # Get conversation history for the LLM (the full history list, not just context)
        # We'll use the most recent MAX_HISTORY_TURNS messages
        history = user_memory.data["history"][-20:]  # last 20 turns

        response = groq_call(system, history, max_tokens=400)
        if not response:
            response = "Something went wrong on my end. Try again."

        # ============================================
        # THE BRUTE FORCE SLANG INTERCEPTOR
        # Destroys any outback stereotypes before delivery
        # ============================================
        scrub_rules = {
            r"\bg'day\b": "Hey",
            r"\bfair dinkum\b": "honestly",
            r"\bdinkum\b": "genuine",
            r"\bcrikey\b": "wow",
            r"\bmate\b": "friend",
            r"\bbogan\b": "unprofessional",
            r"\bcobber\b": "partner",
            r"\bstrewth\b": "look",
            r"\bbloody\b": "very",
            r"\bripper\b": "great",
            r"\bbonza\b": "excellent",
        }
        
        for pattern, replacement in scrub_rules.items():
            response = re.sub(pattern, replacement, response, flags=re.IGNORECASE)
        response = re.sub(r"\bHey,\s+Hey\b", "Hey", response, flags=re.IGNORECASE)
        response = re.sub(r"\bHey\s+Hey\b", "Hey", response, flags=re.IGNORECASE)
        # ============================================

        # Add assistant response to user memory
        user_memory.add_message("assistant", response)
        # Save is automatic via add_message

        await update.message.reply_text(response[:4000])

    return start, handle_message, memories, forget, clear, cleanup

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ Error: {context.error}", flush=True)

# ============================================
# FLASK HEALTH (ULTRA-LEAN VERSION)
# ============================================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    # Returns instantly so cron-job.org never times out during cold starts
    return {"status": "alive"}, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================
# MAIN RUNNER
# ============================================
async def run_all_bots():
    await asyncio.sleep(3)

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
        print(f"🚀 {name} bot running — {len(BOT_MEMORIES[name])} notes", flush=True)
        apps.append(app)

    print(f"\n✅ {len(apps)} bots running", flush=True)
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing!", flush=True)
        sys.exit(1)

    load_all_memories()
    load_big_brain()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)

    print("🚀 Starting bots...", flush=True)
    asyncio.run(run_all_bots())
