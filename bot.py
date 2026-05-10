import os
import threading
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

# ============================================
# TELEGRAM BOT SETUP
# ============================================

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')

# Simple responses for now - we'll add AI/brain later
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey! I'm Joshua's AI Twin Bot. 🤖\n\n"
        "I'm alive and running on Render! Send me any message."
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    response = f"You said: {user_message}\n\n(Full AI brain coming soon!)"
    await update.message.reply_text(response)

# ============================================
# FLASK HEALTH CHECK SERVER (Keeps bot alive)
# ============================================

flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health_check():
    return "✅ Bot is alive and running!", 200

def run_flask():
    # Run Flask on port 8080 (Render expects this)
    flask_app.run(host='0.0.0.0', port=8080, debug=False)

# ============================================
# MAIN FUNCTION
# ============================================

def main():
    # Start Flask health server in background
    print("Starting health check server on port 8080...")
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Telegram bot
    print("🤖 Starting Telegram bot...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
