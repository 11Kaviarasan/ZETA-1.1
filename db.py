"""
db.py — Zeta AI Database Layer
MongoDB via pymongo / motor (sync)
"""

import os, uuid, hashlib, secrets, logging
from datetime import datetime, timedelta

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
import bcrypt

logger = logging.getLogger("zeta.db")

# ─── Connection ──────────────────────────────────────────────────────────────

_client: MongoClient = None
_db = None

def get_db():
    global _client, _db
    if _db is None:
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/zetaai")
        _client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        _db = _client[os.getenv("MONGO_DB_NAME", "zetaai")]
        logger.info("MongoDB connected")
    return _db

# ─── Schema Bootstrap ────────────────────────────────────────────────────────

def bootstrap_schema():
    db = get_db()

    # users
    db.users.create_index("email", unique=True)
    db.users.create_index("username")

    # sessions
    db.sessions.create_index("token", unique=True)
    db.sessions.create_index("expires_at", expireAfterSeconds=0)

    # conversations
    db.conversations.create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])

    # messages / knowledge
    db.knowledge.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    db.knowledge.create_index("conv_id")

    # api_keys
    db.api_keys.create_index("key", unique=True)
    db.api_keys.create_index("user_id")

    # subscriptions
    db.subscriptions.create_index("user_id", unique=True)

    # payments
    db.payments.create_index("user_id")
    db.payments.create_index("razorpay_payment_id")

    # feedback
    db.feedback.create_index("knowledge_id")

    logger.info("DB schema bootstrap complete")

# ─── Users ───────────────────────────────────────────────────────────────────

def create_user(email: str, username: str, password: str) -> dict:
    db = get_db()
    email = email.lower().strip()

    if db.users.find_one({"email": email}):
        raise ValueError("Email already registered.")

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user_id = str(uuid.uuid4())
    now = datetime.utcnow()

    doc = {
        "user_id":    user_id,
        "email":      email,
        "username":   username.strip(),
        "password":   pw_hash,
        "created_at": now,
        "updated_at": now,
        "is_active":  True,
    }
    db.users.insert_one(doc)

    # create default basic subscription
    db.subscriptions.update_one(
        {"user_id": user_id},
        {"$setOnInsert": {
            "user_id": user_id,
            "plan":    "basic",
            "cycle":   None,
            "created_at": now,
            "updated_at": now,
        }},
        upsert=True,
    )

    logger.info(f"New user: {email}")
    return _clean(doc)


def authenticate_user(email: str, password: str):
    db = get_db()
    doc = db.users.find_one({"email": email.lower().strip()})
    if not doc:
        return None
    if not bcrypt.checkpw(password.encode(), doc["password"].encode()):
        return None
    return _clean(doc)


def get_user_by_id(user_id: str):
    doc = get_db().users.find_one({"user_id": user_id})
    return _clean(doc) if doc else None

# ─── Sessions ────────────────────────────────────────────────────────────────

def create_session(user_id: str) -> str:
    db = get_db()
    token = secrets.token_urlsafe(48)
    db.sessions.insert_one({
        "token":      token,
        "user_id":    user_id,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(days=30),
    })
    return token


def validate_session(token: str):
    if not token:
        return None
    doc = get_db().sessions.find_one({
        "token": token,
        "expires_at": {"$gt": datetime.utcnow()},
    })
    return doc["user_id"] if doc else None


def delete_session(token: str):
    get_db().sessions.delete_one({"token": token})


def delete_all_sessions(user_id: str):
    get_db().sessions.delete_many({"user_id": user_id})

# ─── Subscriptions ───────────────────────────────────────────────────────────

def get_subscription(user_id: str) -> dict:
    doc = get_db().subscriptions.find_one({"user_id": user_id})
    if not doc:
        return {"user_id": user_id, "plan": "basic", "cycle": None}
    return _clean(doc)


def upgrade_subscription(user_id: str, plan: str, cycle: str, order_id: str):
    now = datetime.utcnow()
    cycle_days = 365 if cycle == "yearly" else 30
    get_db().subscriptions.update_one(
        {"user_id": user_id},
        {"$set": {
            "plan":        plan,
            "cycle":       cycle,
            "order_id":    order_id,
            "starts_at":   now,
            "expires_at":  now + timedelta(days=cycle_days),
            "updated_at":  now,
        }},
        upsert=True,
    )


def cancel_subscription(user_id: str):
    get_db().subscriptions.update_one(
        {"user_id": user_id},
        {"$set": {
            "plan":       "basic",
            "cycle":      None,
            "cancelled_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }},
    )

# ─── Conversations ───────────────────────────────────────────────────────────

def create_conversation(user_id: str, title: str = "New Conversation", model: str = "zeta-4-turbo") -> str:
    db = get_db()
    conv_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db.conversations.insert_one({
        "conv_id":    conv_id,
        "user_id":    user_id,
        "title":      title[:120],
        "model":      model,
        "created_at": now,
        "updated_at": now,
    })
    return conv_id


def get_user_conversations(user_id: str) -> list:
    docs = get_db().conversations.find(
        {"user_id": user_id},
        sort=[("updated_at", DESCENDING)],
        limit=80,
    )
    return [_clean(d) for d in docs]


def update_conversation_title(conv_id: str, title: str):
    get_db().conversations.update_one(
        {"conv_id": conv_id},
        {"$set": {"title": title[:120], "updated_at": datetime.utcnow()}},
    )


def get_conversation_messages(conv_id: str) -> list:
    docs = get_db().knowledge.find(
        {"conv_id": conv_id, "type": {"$in": ["chat", "api"]}},
        sort=[("created_at", ASCENDING)],
        limit=200,
    )
    return [_clean(d) for d in docs]

# ─── Knowledge / Messages ────────────────────────────────────────────────────

def save_knowledge(question: str, answer: str, conv_id, user_id,
                   source: str = "gemini", msg_type: str = "chat",
                   tokens: int = 0) -> str:
    db = get_db()
    kid = str(uuid.uuid4())
    now = datetime.utcnow()
    doc = {
        "knowledge_id": kid,
        "conv_id":      conv_id,
        "user_id":      user_id,
        "question":     question,
        "answer":       answer,
        "source":       source,
        "type":         msg_type,
        "tokens":       tokens,
        "created_at":   now,
    }
    db.knowledge.insert_one(doc)

    # bump conversation updated_at
    if conv_id:
        get_db().conversations.update_one(
            {"conv_id": conv_id},
            {"$set": {"updated_at": now}},
        )
    return kid

# ─── API Keys ────────────────────────────────────────────────────────────────

def generate_api_key(user_id: str, label: str = "Default Key") -> dict:
    db = get_db()
    raw_key = "zeta_live_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now = datetime.utcnow()

    # revoke existing
    db.api_keys.update_many(
        {"user_id": user_id},
        {"$set": {"revoked": True, "revoked_at": now}},
    )

    doc = {
        "key_id":     str(uuid.uuid4()),
        "user_id":    user_id,
        "label":      label,
        "api_key":    raw_key,          # stored plaintext for display-once
        "key_hash":   key_hash,
        "revoked":    False,
        "created_at": now,
    }
    db.api_keys.insert_one(doc)
    return _clean(doc)


def get_api_key_info(user_id: str):
    doc = get_db().api_keys.find_one(
        {"user_id": user_id, "revoked": False},
        sort=[("created_at", DESCENDING)],
    )
    if not doc:
        return None
    # Mask key for listing
    key = doc.get("api_key", "")
    doc["api_key"] = key[:14] + "..." + key[-4:] if len(key) > 18 else key
    return _clean(doc)


def validate_api_key(raw_key: str):
    doc = get_db().api_keys.find_one({"api_key": raw_key, "revoked": False})
    if not doc:
        return None
    return {"user_id": doc["user_id"], "label": doc.get("label")}


def revoke_api_key(user_id: str):
    get_db().api_keys.update_many(
        {"user_id": user_id},
        {"$set": {"revoked": True, "revoked_at": datetime.utcnow()}},
    )

# ─── Payments ────────────────────────────────────────────────────────────────

def save_payment(user_id, payment_id, order_id, signature, amount, plan, cycle):
    get_db().payments.insert_one({
        "user_id":             user_id,
        "razorpay_payment_id": payment_id,
        "razorpay_order_id":   order_id,
        "razorpay_signature":  signature,
        "amount_paise":        amount,
        "plan":                plan,
        "cycle":               cycle,
        "created_at":          datetime.utcnow(),
    })

# ─── Feedback ────────────────────────────────────────────────────────────────

def save_feedback(knowledge_id: str, rating: int, user_id, comment: str = ""):
    get_db().feedback.insert_one({
        "knowledge_id": knowledge_id,
        "user_id":      user_id,
        "rating":       rating,
        "comment":      comment,
        "created_at":   datetime.utcnow(),
    })

# ─── Stats (admin) ───────────────────────────────────────────────────────────

def get_stats() -> dict:
    db = get_db()
    return {
        "users":         db.users.count_documents({}),
        "conversations": db.conversations.count_documents({}),
        "messages":      db.knowledge.count_documents({}),
        "pro_users":     db.subscriptions.count_documents({"plan": "pro"}),
        "api_keys":      db.api_keys.count_documents({"revoked": False}),
    }

# ─── Internal helper ────────────────────────────────────────────────────────

def _clean(doc: dict) -> dict:
    if doc is None:
        return {}
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("password", None)
    return doc
