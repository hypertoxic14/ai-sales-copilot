import firebase_admin
from firebase_admin import credentials, firestore, auth
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

key_path = Path(__file__).resolve().parents[2] / os.getenv("FIREBASE_KEY_PATH", "firebase_key.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(str(key_path))
    firebase_admin.initialize_app(cred)

db = firestore.client()

def verify_token(id_token: str) -> dict:
    """Verify Firebase ID token with clock skew tolerance."""
    try:
        decoded = auth.verify_id_token(
            id_token,
            clock_skew_seconds=60  # allow 60 second clock difference
        )
        return decoded
    except Exception as e:
        raise ValueError(f"Invalid token: {e}")

def get_user_profile(uid: str) -> dict:
    doc = db.collection("users").document(uid).get()
    return doc.to_dict() if doc.exists else None

def update_user_profile(uid: str, data: dict):
    db.collection("users").document(uid).update(data)