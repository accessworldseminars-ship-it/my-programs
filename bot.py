import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')

async def start(update, context):
    await update.message.reply_text("Hello! I'm Joshua's AI Twin Bot. I'm alive and running on Render!")

async def echo(update, context):
    user_message = update.message.text
    await update.message.reply_text(f"You said: {user_message}")

def main():
    print("Bot is starting...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("Bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
