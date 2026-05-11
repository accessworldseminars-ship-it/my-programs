def load_brain():
    global collection, brain_temp_dir
    
    try:
        print("📥 Loading brain...", flush=True)
        
        brain_temp_dir = tempfile.mkdtemp()
        brain_path = os.path.join(brain_temp_dir, 'bot_brain')
        os.makedirs(brain_path, exist_ok=True)
        
        # Download from R2
        s3 = boto3.client('s3',
            endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name='auto'
        )
        
        zip_path = '/tmp/bot_brain.zip'
        s3.download_file(BUCKET_NAME, 'bot_brain.zip', zip_path)
        print(f"✅ Downloaded", flush=True)
        
        # Extract
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(brain_path)
            all_files = z.namelist()
        print(f"✅ Extracted {len(all_files)} files", flush=True)
        
        # DEBUG: Show exactly what's in brain_path
        print(f"📁 brain_path = {brain_path}", flush=True)
        for root, dirs, files in os.walk(brain_path):
            level = root.replace(brain_path, '').count(os.sep)
            indent = ' ' * 2 * level
            print(f"{indent}{os.path.basename(root)}/", flush=True)
            subindent = ' ' * 2 * (level + 1)
            for file in files:
                print(f"{subindent}{file}", flush=True)
        
        # Connect to ChromaDB - try brain_path first, then subdirectory
        import chromadb
        from chromadb.config import Settings
        
        # Check if chroma.sqlite3 is directly in brain_path or one level deeper
        sqlite_in_root = os.path.exists(os.path.join(brain_path, 'chroma.sqlite3'))
        print(f"🔍 chroma.sqlite3 in brain_path: {sqlite_in_root}", flush=True)
        
        # Find the actual chroma.sqlite3 location
        chroma_db_path = brain_path
        if not sqlite_in_root:
            # Look one level deeper
            for item in os.listdir(brain_path):
                candidate = os.path.join(brain_path, item)
                if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, 'chroma.sqlite3')):
                    chroma_db_path = candidate
                    print(f"🔍 Found chroma.sqlite3 in subdirectory: {chroma_db_path}", flush=True)
                    break
        
        client = chromadb.PersistentClient(
            path=chroma_db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # List available collections before trying to get one
        available = client.list_collections()
        print(f"📚 Available collections: {[c.name for c in available]}", flush=True)
        
        collection = client.get_collection("my_brain")
        print(f"✅ Brain loaded! {collection.count():,} chunks", flush=True)
        
        os.remove(zip_path)
        
    except Exception as e:
        print(f"❌ Brain error: {e}", flush=True)
        traceback.print_exc()
