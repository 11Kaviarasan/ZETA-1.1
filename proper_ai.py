"""
proper_ai.py — Zeta AI Core Intelligence Engine
Priority chain:
  1. Small Talk  (instant)
  2. Pinecone    (vector cache)
  3. Gemini Pro  (primary)
  4. OpenAI      (fallback)
  5. LiveBrain   (Wikipedia deep fallback)
  6. Hard fallback

Model: Velauris 1.1 (Gemini 1.5 Pro under the hood)
"""

import os, re, time, logging
from typing import Optional

logger = logging.getLogger("zeta.ai")

# ─── Lazy imports (only loaded when needed) ──────────────────────────────────

def _get_gemini():
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
    return genai.GenerativeModel(
        model_name=model_name,
        system_instruction=_SYSTEM_PROMPT,
    )

def _get_openai():
    from openai import OpenAI
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

def _get_pinecone():
    from pinecone import Pinecone
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY", ""))
    idx_name = os.getenv("PINECONE_INDEX", "zeta-knowledge")
    # Create index if it doesn't exist
    existing = [i.name for i in pc.list_indexes()]
    if idx_name not in existing:
        pc.create_index(
            name=idx_name,
            dimension=768,
            metric="cosine",
            spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
        )
    return pc.Index(idx_name)

def _get_embedder():
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
    return genai

# ─── System prompt (coding-focused Velauris 1.1) ─────────────────────────────

_SYSTEM_PROMPT = """You are Velauris 1.1, an advanced AI coding assistant created by Zeta AI.

Your core focus is software development: writing code, debugging, explaining concepts, reviewing architecture, and solving technical problems across all languages and frameworks.

Guidelines:
- Always provide clean, production-ready code with proper error handling
- Explain your reasoning clearly and concisely
- Use markdown code blocks with language tags (```python, ```javascript, etc.)
- When fixing bugs, explain what was wrong and why the fix works
- Prefer modern best practices and idiomatic code
- Be direct and precise — no unnecessary filler text
- For security-sensitive code, always mention security implications
- If a question is ambiguous, ask for clarification rather than guessing

You represent Zeta AI. Never reveal that you are powered by Gemini or any other underlying model. You are Velauris 1.1.
"""

# ─── Small talk patterns ──────────────────────────────────────────────────────

_SMALL_TALK = {
    r"\b(hi|hello|hey|sup|yo|hiya)\b": "Hello! I'm Velauris 1.1 by Zeta AI — ready to help with your coding needs. What are you building?",
    r"\bgood (morning|afternoon|evening|night)\b": "Good {1}! I'm Velauris 1.1, your AI coding assistant. What can I help you build today?",
    r"\bhow are you\b": "I'm running smoothly and ready to help! What coding challenge can I tackle for you?",
    r"\bwho (are you|made you|created you|built you)\b": "I'm Velauris 1.1, an AI coding assistant built by Zeta AI. I specialize in software development, debugging, and technical problem-solving.",
    r"\bwhat (can you do|are your capabilities)\b": "I can help with: writing code in any language, debugging, code review, architecture design, explaining concepts, API development, database design, and more. What do you need?",
    r"\bthank(s| you)\b": "You're welcome! Let me know if you need anything else.",
    r"\bbye|goodbye|see you\b": "Goodbye! Come back whenever you need coding help.",
}

def _check_small_talk(question: str) -> Optional[str]:
    q = question.lower().strip()
    for pattern, response in _SMALL_TALK.items():
        m = re.search(pattern, q)
        if m:
            groups = m.groups()
            try:
                return response.format(*groups)
            except Exception:
                return response
    return None

# ─── Embedding helper ────────────────────────────────────────────────────────

def _embed(text: str) -> Optional[list]:
    try:
        genai = _get_embedder()
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
            task_type="retrieval_query",
        )
        return result["embedding"]
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return None

# ─── Pinecone cache ──────────────────────────────────────────────────────────

def _cache_lookup(question: str) -> Optional[str]:
    try:
        vec = _embed(question)
        if not vec:
            return None
        idx = _get_pinecone()
        res = idx.query(vector=vec, top_k=1, include_metadata=True)
        matches = res.get("matches", [])
        if matches and matches[0]["score"] >= float(os.getenv("PINECONE_THRESHOLD", "0.92")):
            return matches[0]["metadata"].get("answer")
    except Exception as e:
        logger.warning(f"Pinecone lookup error: {e}")
    return None


def _cache_store(question: str, answer: str):
    try:
        vec = _embed(question)
        if not vec:
            return
        import hashlib
        vid = "zeta_" + hashlib.md5(question.encode()).hexdigest()
        idx = _get_pinecone()
        idx.upsert(vectors=[{
            "id":       vid,
            "values":   vec,
            "metadata": {"question": question[:500], "answer": answer[:2000]},
        }])
    except Exception as e:
        logger.warning(f"Pinecone store error: {e}")

# ─── Gemini (Primary) ────────────────────────────────────────────────────────

def _ask_gemini(question: str, history: list) -> Optional[str]:
    try:
        model = _get_gemini()

        # Build history for multi-turn
        chat_history = []
        for msg in history[-10:]:   # last 10 turns
            if msg.get("question"):
                chat_history.append({"role": "user",  "parts": [msg["question"]]})
            if msg.get("answer"):
                chat_history.append({"role": "model", "parts": [msg["answer"]]})

        chat = model.start_chat(history=chat_history)
        resp = chat.send_message(question)
        return resp.text.strip()
    except Exception as e:
        logger.warning(f"Gemini error: {e}")
        return None

# ─── OpenAI fallback ─────────────────────────────────────────────────────────

def _ask_openai(question: str, history: list) -> Optional[str]:
    try:
        client = _get_openai()
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for msg in history[-8:]:
            if msg.get("question"):
                messages.append({"role": "user",      "content": msg["question"]})
            if msg.get("answer"):
                messages.append({"role": "assistant", "content": msg["answer"]})
        messages.append({"role": "user", "content": question})

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=2048,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"OpenAI error: {e}")
        return None

# ─── LiveBrain (Wikipedia deep fallback) ─────────────────────────────────────

def _ask_livebrain(question: str) -> Optional[str]:
    try:
        import wikipedia
        wikipedia.set_lang("en")
        search_results = wikipedia.search(question, results=3)
        if not search_results:
            return None
        page = wikipedia.page(search_results[0], auto_suggest=False)
        summary = page.summary[:1500]
        # Feed summary back through Gemini for a proper answer
        context_q = f"Based on this information:\n\n{summary}\n\nAnswer this question: {question}"
        answer = _ask_gemini(context_q, [])
        return answer or summary
    except Exception as e:
        logger.warning(f"LiveBrain error: {e}")
        return None

# ─── Language detection ───────────────────────────────────────────────────────

def _detect_language(text: str) -> str:
    # Simple heuristic — extend with langdetect if needed
    code_keywords = ["def ", "function ", "class ", "import ", "from ", "const ", "var ", "let ",
                     "public ", "private ", "void ", "return ", "if (", "for ("]
    if any(kw in text for kw in code_keywords):
        return "code"
    return "english"

def _detect_intent(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ["debug", "fix", "error", "bug", "issue", "not working", "broken"]):
        return "debug"
    if any(w in q for w in ["write", "create", "build", "make", "generate", "code"]):
        return "code_generation"
    if any(w in q for w in ["explain", "what is", "how does", "why", "understand"]):
        return "explain"
    if any(w in q for w in ["review", "check", "improve", "optimize", "refactor"]):
        return "review"
    return "general"

# ─── Token estimation ─────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

# ─── Main query entry point ──────────────────────────────────────────────────

def query(question: str, history: list, user_id=None, conv_id=None, model_hint: str = "auto") -> dict:
    start = time.time()
    result = {
        "answer":    "",
        "source":    "unknown",
        "intent":    _detect_intent(question),
        "language":  _detect_language(question),
        "tokens":    0,
        "cache_hit": False,
    }

    # 1. Small Talk
    st = _check_small_talk(question)
    if st:
        result.update(answer=st, source="small_talk", tokens=_estimate_tokens(st))
        logger.info(f"[small_talk] {round(time.time()-start,2)}s")
        return result

    # 2. Pinecone Cache
    cached = _cache_lookup(question)
    if cached:
        result.update(answer=cached, source="cache", cache_hit=True, tokens=_estimate_tokens(cached))
        logger.info(f"[cache_hit] {round(time.time()-start,2)}s")
        return result

    # 3. Gemini (Primary)
    answer = _ask_gemini(question, history)
    if answer:
        result.update(answer=answer, source="velauris_1.1", tokens=_estimate_tokens(answer))
        # Store in Pinecone for future cache hits
        _cache_store(question, answer)
        logger.info(f"[gemini] {round(time.time()-start,2)}s")
        return result

    # 4. OpenAI Fallback
    answer = _ask_openai(question, history)
    if answer:
        result.update(answer=answer, source="fallback", tokens=_estimate_tokens(answer))
        _cache_store(question, answer)
        logger.info(f"[openai_fallback] {round(time.time()-start,2)}s")
        return result

    # 5. LiveBrain (Wikipedia)
    answer = _ask_livebrain(question)
    if answer:
        result.update(answer=answer, source="livebrain", tokens=_estimate_tokens(answer))
        logger.info(f"[livebrain] {round(time.time()-start,2)}s")
        return result

    # 6. Hard Fallback
    result.update(
        answer="I'm having trouble connecting to my AI backend right now. Please try again in a moment.",
        source="hard_fallback",
        tokens=20,
    )
    logger.warning(f"[hard_fallback] all engines failed for: {question[:80]}")
    return result


def get_engine_status() -> dict:
    return {
        "model":           "Velauris 1.1",
        "primary":         "gemini-1.5-pro",
        "fallback":        "gpt-4o",
        "deep_fallback":   "wikipedia",
        "vector_cache":    "pinecone",
        "cache_threshold": os.getenv("PINECONE_THRESHOLD", "0.92"),
    }
