"""
scripts/verify_schema.py — Verify MongoDB collections and indexes.

Run from the project root:
    python scripts/verify_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app

def verify():
    from app.extensions import db
    
    collections = db.list_collection_names()
    print(f"Found {len(collections)} collections: {collections}\n")
    
    for coll_name in collections:
        print(f"Collection: {coll_name}")
        
        # Count documents
        count = db[coll_name].count_documents({})
        print(f"  Documents: {count}")
        
        # List indexes
        indexes = db[coll_name].index_information()
        print(f"  Indexes ({len(indexes)}):")
        for idx_name, idx_info in indexes.items():
            print(f"    - {idx_name}: {idx_info['key']}")
            
        print()

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        verify()
