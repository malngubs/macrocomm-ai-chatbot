# server/api_server.py
# FastAPI app for Macrocomm Assistant -- production-friendly minimal server
# -----------------------------------------------------------------------
# - Centralised paths (_effective_paths)
# - TXT corpus loader + CHUNKED BM25 retriever (sharp policy lookup)
# - /chat supports k, temperature, top_p tuning
# - /debug/retrieve for retrieval inspection
# - /admin/reindex to rebuild the in-memory index after TXT changes
# - Serves /static and /brand.json for the desktop wrapper
#
# Dev run:
#   conda activate macrocomm-rag
#   uvicorn server.api_server:app --host 127.0.0.1 --port 8000 --reload

from __future__ import annotations

import os
import re
import json
import time
import math
import random
from dataclasses import dataclass
from pathlib import Path
from collections import Counter
from typing import Callable, Dict, List, Tuple

# --- FastAPI & static serving -------------------------------------------------
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# --- OpenAI minimal wrapper (official SDK v1) ---------------------------------
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # clear error if SDK missing

# ============================================================================
# 1) PATHS & FILE IO
# ============================================================================
def _effective_paths() -> Dict[str, str]:
    """
    Canonical central place for paths.
    We standardise on <repo_root>/corp_docs/txt for the corpus.
    To remain backward compatible, if that doesn't exist we fall back to <repo_root>/txt.
    """
    root = Path(__file__).resolve().parent.parent
    # New canonical location
    corp_txt = root / "corp_docs" / "txt"
    # Legacy location (kept for backward compatibility during the transition)
    legacy_txt = root / "txt"
    # Decide which to use
    chosen_txt = corp_txt if corp_txt.exists() else legacy_txt
    return {
        "root": str(root),
        "txt_dir": str(chosen_txt),            # <- retrieval reads from here
        "chroma_dir": str(root / "db" / "chroma"),
    }

def _read_txt_files(txt_dir: Path) -> List[Tuple[str, str]]:
    """Load all *.txt files; return (filename, text) pairs."""
    docs: List[Tuple[str, str]] = []
    if not txt_dir.exists():
        return docs
    for p in sorted(txt_dir.glob("*.txt")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                docs.append((p.name, text))
        except Exception:
            # skip unreadable files
            pass
    return docs

# ============================================================================
# 2) CHUNKED BM25 RETRIEVER  (replaces old cosine BoW)
# ============================================================================
@dataclass
class Chunk:
    source: str      # original filename
    text: str        # chunk text
    tokens: List[str]

def _tokenise_norm(s: str) -> List[str]:
    """Lowercase alnum/hyphen tokens for robust matching."""
    return re.findall(r"[a-z0-9][a-z0-9\-]+", s.lower())

def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 200) -> List[str]:
    """
    Split long documents into overlapping chunks at paragraph boundaries.
    - Keeps paragraphs together where possible
    - Overlap preserves context across boundaries
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf, buf_len = [], [], 0
    for p in paras:
        if buf_len + len(p) + 2 <= max_chars:
            buf.append(p); buf_len += len(p) + 2
        else:
            if buf:
                chunks.append("\n\n".join(buf))
            if chunks and overlap > 0:
                tail = chunks[-1][-overlap:]
                buf = [tail, p]; buf_len = len(tail) + 2 + len(p)
            else:
                buf = [p]; buf_len = len(p)
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks

class BM25Index:
    """Tiny BM25 over Chunk[] with k1/b hyper-params."""
    def __init__(self, chunks: List[Chunk], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.chunks = chunks
        self.N = len(chunks)
        self.df = Counter()
        for ch in chunks:
            for t in set(ch.tokens):
                self.df[t] += 1
        self.avgdl = (sum(len(ch.tokens) for ch in chunks) / max(1, self.N)) if self.N else 0.0

    def score(self, q_tokens: List[str], ch: Chunk) -> float:
        tf = Counter(ch.tokens)
        dl = len(ch.tokens) or 1
        s = 0.0
        for t in q_tokens:
            if t not in self.df:
                continue
            idf = math.log(1 + (self.N - self.df[t] + 0.5) / (self.df[t] + 0.5))
            f = tf[t]
            denom = f + self.k1 * (1 - self.b + self.b * (dl / self.avgdl if self.avgdl else 1.0))
            s += idf * (f * (self.k1 + 1)) / max(1e-9, denom)
        return s

    def search(self, query: str, k: int = 5) -> List[Tuple[float, Chunk]]:
        q = _tokenise_norm(query)
        scored = [(self.score(q, ch), ch) for ch in self.chunks]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:max(1, k)]

def build_bm25_retriever() -> Callable[[str, int], List[Dict[str, str]]]:
    """Build BM25 over chunked TXT corpus; returns (query,k)->[{source,text,score}]."""
    paths = _effective_paths()
    txt_dir = Path(paths["txt_dir"])
    raw_docs = _read_txt_files(txt_dir)

    chunks: List[Chunk] = []
    for src, text in raw_docs:
        for ch in _chunk_text(text):
            chunks.append(Chunk(source=src, text=ch, tokens=_tokenise_norm(ch)))

    index = BM25Index(chunks)

    def _retrieve(query: str, k: int = 5) -> List[Dict[str, str]]:
        hits = index.search(query, k=k)
        return [{"source": ch.source, "text": ch.text, "score": float(score)} for score, ch in hits]

    return _retrieve

# ============================================================================
# 3) HUMOUR (kept as-is, lightly)
# ============================================================================
_DIRECTOR_KEYWORDS = {
    "elton": ["elton chettiar", "chettiar", "sky daddy", "sky dzaddy"],
    "coo": ["chief operating officer", "operations head"],
    "ceo": ["chief executive officer"],
    "cfo": ["chief financial officer"],
}
_HUMOUR_LINES = {
    "elton": [
        "He's also known as 'Sky Daddy'--allegedly once parted the Orange River and still made the 08:00 stand-up.",
        "Rumour has it he once killed a lion with his bare hands--HR insists it was a very large house cat.",
        "Word on the street is he can debug spreadsheets by staring at them sternly.",
    ],
    "ceo": [
        "Legend says the CEO's calendar runs on 'Sivi Standard Time'--always three steps ahead.",
        "Apparently the CEO once negotiated with a South African thunderstorm and won.",
    ],
    "coo": [
        "The COO is rumoured to be able to schedule meetings into next week's weather forecast.",
        "They say the COO keeps operations smoother than the N1 at 3 a.m.",
    ],
    "cfo": [
        "The CFO can spot a rounding error from across the boardroom.",
        "Legend claims the CFO once balanced a budget and a pap pot at the same time.",
    ],
}
def _inject_humor(answer: str, user_query: str) -> str:
    """Occasionally inject hardcoded humor (50% chance) for variety."""
    # Only inject hardcoded humor 50% of the time for variety
    if random.random() > 0.5:
        return answer
    
    q = user_query.lower()
    for key, aliases in _DIRECTOR_KEYWORDS.items():
        if key in q or any(a in q for a in aliases):
            lines = _HUMOUR_LINES.get(key, [])
            if lines:
                line = random.choice(lines)
                if line not in answer:
                    return f"{answer}\n\n{line}"
    return answer

# ============================================================================
# 4) OPENAI CALL
# ============================================================================
def call_openai(messages: List[Dict[str, str]], temperature: float = 0.2, top_p: float = 0.9) -> str:
    """Minimal Chat Completions call (official SDK v1)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment.")
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK not installed. `pip install openai`")

    client = OpenAI(api_key=api_key)
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        top_p=top_p,
        messages=messages,
    )
    text = resp.choices[0].message.content or ""
    return text.strip()

# ============================================================================
# 5) FASTAPI APP + STATIC
# ============================================================================
app = FastAPI(title="Macrocomm Assistant API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# static mount for desktop wrapper
_repo_root = Path(__file__).resolve().parents[1]
_static_dir = _repo_root / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir), html=True), name="static")
    print(f"[INFO] Serving static from: {_static_dir}")
else:
    print(f"[WARN] Static dir not found: {_static_dir} -- /static/* will 404")

@app.get("/brand.json")
def brand_json():
    p = _static_dir / "brand" / "brand.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"brand.json not found at {p}")
    return FileResponse(str(p), media_type="application/json")

# ============================================================================
# 6) LIFECYCLE & HEALTH
# ============================================================================
retriever: Callable[[str, int], List[Dict[str, str]]] | None = None

@app.on_event("startup")
def _startup() -> None:
    global retriever
    retriever = build_bm25_retriever()  # <= NEW sharp retriever

@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok", "paths": _effective_paths(), "time": int(time.time())})

# ============================================================================
# 7) DEBUG: INSPECT RETRIEVAL
# ============================================================================
@app.get("/debug/retrieve")
def debug_retrieve(q: str, k: int = 6):
    """Return top-k retrieval results to verify coverage/grounding."""
    global retriever
    if retriever is None:
        raise HTTPException(status_code=503, detail="Retriever not ready.")
    docs = retriever(q, k=k)
    return JSONResponse({
        "query": q,
        "k": k,
        "results": [
            {"score": round(d["score"], 4), "source": d["source"], "preview": (d["text"][:600] if d["text"] else "")}
            for d in docs
        ]
    })

# ============================================================================
# 8) CHAT
# ============================================================================
@app.post("/chat")
def chat(payload: Dict):
    """
    POST body:
      {
        "message": "...",
        "k": 6,               # optional: top-k chunks to fetch (default 6)
        "temperature": 0.35,  # optional: creativity level (default 0.35)
        "top_p": 0.9          # optional: nucleus sampling (default 0.9)
      }
    """
    user_query = (payload or {}).get("message", "").strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Missing message.")

    k = int((payload or {}).get("k", 6))
    temperature = float((payload or {}).get("temperature", 0.35))
    top_p = float((payload or {}).get("top_p", 0.9))

    global retriever
    if retriever is None:
        raise HTTPException(status_code=503, detail="Retriever not ready.")

    # 1) Retrieve internal context
    docs = retriever(user_query, k=k)
    internal_ctx = "\n\n".join(d["text"].strip() for d in docs if d.get("text"))
    internal_cites = [
        {"source": d.get("source", "internal"), "score": round(d.get("score", 0.0), 4),
         "preview": (d.get("text", "") or "")[:300]}
        for d in docs
    ]

    # 2) Prompt - with dynamic tone based on query type
    q_lower = user_query.lower()
    
    # Detect if query is about executives/people
    is_about_executives = any(
        keyword in q_lower for keyword in 
        ["elton", "chettiar", "sky daddy", "ceo", "cfo", "coo", 
         "chief executive", "chief operating", "chief financial",
         "who is", "tell me about", "describe"]
    )
    
    base_instructions = (
        "- Use British English.\n"
        "- Answer strictly from INTERNAL_CONTEXT; if unknown, say so briefly.\n"
        "- Prefer 3–6 crisp sentences unless a short list is required.\n"
    )
    
    # Add humor hint for executive queries
    if is_about_executives:
        tone_instructions = (
            "- Be warm, personable, and professional.\n"
            "- When appropriate, add a light-hearted or playful comment about the person.\n"
            "- Make each response feel fresh and natural - vary your phrasing and humour.\n"
        )
    else:
        tone_instructions = "- Be clear, professional, and helpful.\n"
    
    prompt = (
        "You are Macrocomm Assistant, a helpful, professional assistant with a warm, approachable tone.\n\n"
        "INTERNAL_CONTEXT:\n"
        f"{internal_ctx or '[none]'}\n\n"
        "QUESTION:\n"
        f"{user_query}\n\n"
        "Instructions:\n"
        f"{base_instructions}"
        f"{tone_instructions}"
    )

    # 3) Generate
    answer_text = call_openai(
        messages=[{"role": "system", "content": "You are Macrocomm Assistant."},
                  {"role": "user", "content": prompt}],
        temperature=temperature,
        top_p=top_p,
    )
    answer_text = _inject_humor(answer_text, user_query)

    return JSONResponse({"answer": answer_text, "citations": internal_cites,
                         "meta": {"k": k, "temperature": temperature, "top_p": top_p,
                                  "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini")}})

# ============================================================================
# 9) ADMIN: REINDEX
# ============================================================================
@app.post("/admin/reindex")
def reindex():
    """Rebuild the in-memory BM25 index (call after adding/removing TXT files)."""
    global retriever
    try:
        retriever = build_bm25_retriever()
        return JSONResponse({"status": "ok", "reindexed": True})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)