import os
import json
import requests

ASSISTANT_TELEGRAM_TOKEN = os.environ.get('ASSISTANT_TELEGRAM_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
SUPABASE_URL = "https://mldzkzrljaxudemfpbkh.supabase.co"
SUPABASE_KEY = os.environ.get('SUPABASE_TOKEN')
CLOUDFLARE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN')
R2_BUCKET = "joshua-bot-brain"
R2_OBJECT = "working_brain_json"

print(f"Assistant Bot - Telegram: {'✅' if ASSISTANT_TELEGRAM_TOKEN else '❌'}", flush=True)

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
            print(f"🧠 Assistant brain loaded: {len(brain)} entries", flush=True)
            return brain
        print(f"❌ R2 load failed: {resp.status_code}", flush=True)
        return []
    except Exception as e:
        print(f"❌ Brain load error: {e}", flush=True)
        return []

WORKING_BRAIN = load_working_brain()

# ============================================
# SEARCH WORKING BRAIN
# ============================================
def search_working_brain(query, top_k=5):
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
        print(f"❌ Supabase error: {e}", flush=True)
    return ""

# ============================================
# GROQ ASSISTANT RESPONSE
# ============================================
def get_assistant_response(message, context_text):
    prompt = f"""You are a sharp personal assistant to Joshua Roy, an Australian Results Coach 
specialising in NLP and Nervous System Reprogramming (NSR). 

You know his entire body of seminar content, coaching methodology, and business (AccessWorld Seminars).
You help him plan sessions, organise content, draft copy, brainstorm ideas, and review material.
Be direct, practical, and efficient. You know his voice and his work inside out.

Relevant content from his seminars:
{context_text[:1500]}

Joshua: {message}
Assistant:"""

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
                "max_tokens": 500,
                "temperature": 0.5
            },
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        print(f"❌ Groq status: {resp.status_code} - {resp.text}", flush=True)
        return "Something went wrong, try again."
    except Exception as e:
        print(f"❌ Groq error: {e}", flush=True)
        return "Error connecting to AI."

# ============================================
# MAIN RESPONSE PIPELINE
# ============================================
def build_assistant_response(message):
    matches = search_working_brain(message, top_k=5)
    print(f"📚 Assistant RAM matches: {len(matches)}", flush=True)
    context_parts = []
    for match in matches:
        full_text = fetch_full_entry(match["id"])
        if full_text:
            context_parts.append(full_text)
    context_text = "\n\n".join(context_parts) if context_parts else "No specific context found."
    return get_assistant_response(message, context_text)
