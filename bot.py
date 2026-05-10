import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')

# Basic /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm Joshua's AI Twin Bot. The full AI brain is being connected. For now, I'm alive and responding!")

# Echo for all other messages
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.reply_text(f"You said: {user_message}\n\n(The AI is not yet connected, but the bot is running perfectly on Render!)")

def main():
    print("🤖 Minimal bot is starting...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("✅ Bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
