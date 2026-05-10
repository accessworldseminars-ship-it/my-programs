import os
import boto3
import chromadb
import subprocess
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

# ============================================
# ENVIRONMENT VARIABLES (Set in Render)
# ============================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
BUCKET_NAME = "joshua-bot-brain"

# ============================================
# DOWNLOAD AND EXTRACT RAR
# ============================================
def download_and_extract_brain():
    """Downloads chroma.rar from R2 and extracts it"""
    
    if os.path.exists('./bot_brain'):
        print("✅ Brain already exists")
        return
    
    print("📥 Downloading chroma.rar from Cloudflare R2...")
    
    # Connect to R2
    s3 = boto3.client(
        's3',
        endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        region_name='auto'
    )
    
    # Download RAR file
    os.makedirs('/tmp/bot_brain', exist_ok=True)
    rar_path = '/tmp/bot_brain/chroma.rar'
    s3.download_file(BUCKET_NAME, 'chroma.rar', rar_path)
    print("✅ Download complete")
    
    # Extract RAR (requires unrar)
    print("📦 Extracting brain...")
    extract_path = './bot_brain'
    os.makedirs(extract_path, exist_ok=True)
    
    # Use unrar command (install if needed)
    subprocess.run(['unrar', 'x', rar_path, extract_path], check=True)
    
    print("✅ Brain ready!")

# You'll need to install unrar - add to Dockerfile or start script
# For Render, add: RUN apt-get update && apt-get install -y unrar

# ============================================
# LOAD YOUR BRAIN
# ============================================
def load_brain():
    try:
        brain_db = chromadb.PersistentClient(path="./bot_brain")
        collection = brain_db.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks")
        return collection
    except Exception as e:
        print(f"⚠️ Brain not found, downloading first...")
        download_and_extract_brain()
        brain_db = chromadb.PersistentClient(path="./bot_brain")
        collection = brain_db.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks")
        return collection

# Download on startup
collection = load_brain()

# Rest of your bot code...
