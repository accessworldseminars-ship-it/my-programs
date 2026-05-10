# bot.py - Deploy to Render with Cloudflare AI
import os
import requests
import chromadb
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

# Environment variables (set these in Render)
8617451522:AAExnoaNqz0p3EqiFo9uxItmsK5X8uxAdIc = os.environ.get('TELEGRAM_TOKEN')
Account id - b0df134265310242988cca17a4611c30  = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
cfat_pzV3Tdb7RzmEYwaUzfeYQX9URvXrrJzln9Jt0Jmndd758840 = os.environ.get('CLOUDFLARE_API_TOKEN')

# Cloudflare AI model
MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"

# Load your brain from Google Drive (mounted path)
print("📚 Loading brain database...")
brain_db = chromadb.PersistentClient(path="/app/bot_brain")
collection = brain_db.get_collection("my_brain")
print(f"✅ Brain loaded! {collection.count():,} chunks")

class CloudflareTwin:
    def __init__(self):
        self.account_id = CLOUDFLARE_ACCOUNT_ID
        self.api_token = CLOUDFLARE_API_TOKEN
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{MODEL}"
    
    def search_brain(self, query, n_results=3):
        try:
            results = collection.query(query_texts=[query], n_results=n_results)
            if results['documents'] and results['documents'][0]:
                return "\n".join(results['documents'][0][:3])
        except Exception as e:
            print(f"Search error: {e}")
        return ""
    
    def respond(self, user_message):
        context = self.search_brain(user_message)
        
        prompt = f"""You are Joshua Roy - seminar leader, life coach. Be CONCISE. 1-3 sentences max.
Short answers. Ask questions back. Never say "as an AI".

Context from my seminars: {context}

User: {user_message}

Concise response:"""
        
        try:
            response = requests.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_token}"},
                json={
                    "prompt": prompt,
                    "max_tokens": 200,
                    "temperature": 0.6
                },
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()["result"]["response"]
            else:
                return f"API Error: {response.status_code}"
        except Exception as e:
            return f"Error: {str(e)[:100]}"

twin = CloudflareTwin()

# Telegram handlers
async def start(update, context):
    await update.message.reply_text("Hey, it's Josh. What's on your mind?")

async def handle_message(update, context):
    try:
        response = twin.respond(update.message.text)
        await update.message.reply_text(response[:4000])
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)[:100]}")

# Main bot
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot is running on Render with Cloudflare AI!")
    app.run_polling()

if __name__ == "__main__":
    main()
