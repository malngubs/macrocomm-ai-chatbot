# server/api_server.py
# FastAPI app for Macrocomm Assistant — minimal, self-contained server
# -------------------------------------------------------------------
# - Single source of truth for important paths (_effective_paths)
# - Simple file-based retriever (no extra deps)
# - Clean /chat, /debug/retrieve, /admin/reindex endpoints
# - British English, no markdown markers, optional tasteful humour
# - OpenAI-only for generation
#
# NOTE:
#   * Put your TXT corpus in:   <repo_root>/txt/*.txt
#   * Vector store dir (if you later add one): <repo_root>/db/chroma
#   * Set OPENAI_API_KEY in environment before running.
#
# Run dev server:
#   conda activate macrocomm-rag
#   python -m uvicorn server.api_server:app --host 127.0.0.1 --port 8000

from __future__ import annotations

import os
import re
import json
import time
import random
from pathlib import Path
from collections import Counter
from typing import Callable, Dict, List, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# --- OpenAI minimal wrapper (official SDK v1) ------------------------
try:
    from openai import OpenAI
except Exception as e:  # pragma: no cover
    OpenAI = None  # We’ll error clearly if SDK missing.

# --------------------------------------------------------------------
# 1) PATHS & UTILITIES
# --------------------------------------------------------------------
def _effective_paths() -> Dict[str, str]:
    """
    Canonical central place for paths. (Replaces old get_active_paths.)
    """
    root = Path(__file__).resolve().parent.parent
    return {
        "root": str(root),
        "txt_dir": str(root / "txt"),
        "chroma_dir": str(root / "db" / "chroma"),
        # Add more here if you later reintroduce a persistent vector DB
    }


def _read_txt_files(txt_dir: Path) -> List[Tuple[str, str]]:
    """
    Load all *.txt files from txt_dir. Returns list of (source, text).
    """
    docs: List[Tuple[str, str]] = []
    if not txt_dir.exists():
        return docs
    for p in sorted(txt_dir.glob("*.txt")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                docs.append((p.name, text))
        except Exception:
            # Skip unreadable files
            pass
    return docs


# --------------------------------------------------------------------
# 2) TINY RETRIEVER (no external libs)
# --------------------------------------------------------------------
def _tokenise(s: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9]+", s.lower())


def _bow(vec: List[str]) -> Counter:
    return Counter(vec)


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    # dot
    dot = sum(a[t] * b[t] for t in set(a) & set(b))
    # norms
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def build_hybrid_retriever() -> Callable[[str, int], List[Dict[str, str]]]:
    """
    Super-light retriever: cosine similarity on bag-of-words.
    Returns a function(query, k) -> list of {source, text, score}.
    """
    paths = _effective_paths()
    txt_dir = Path(paths["txt_dir"])
    corpus = _read_txt_files(txt_dir)

    # Pre-tokenise for speed
    index: List[Tuple[str, str, Counter]] = []
    for src, text in corpus:
        index.append((src, text, _bow(_tokenise(text))))

    def _retrieve(query: str, k: int = 5) -> List[Dict[str, str]]:
        qv = _bow(_tokenise(query))
        scored: List[Tuple[float, str, str]] = []
        for src, text, tv in index:
            scored.append((_cosine(qv, tv), src, text))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: List[Dict[str, str]] = []
        for score, src, text in scored[: max(1, k)]:
            out.append({"source": src, "text": text, "score": float(score)})
        return out

    return _retrieve


# --------------------------------------------------------------------
# 3) HUMOUR INJECTION (tasteful & role-aware)
# --------------------------------------------------------------------
_DIRECTOR_KEYWORDS = {
    # normalised lower-case keys -> short synonyms/nicknames to detect
    "elton": ["elton chettiar", "chettiar", "sky daddy", "sky dzaddy"],
    "coo": ["chief operating officer", "operations head"],
    "ceo": ["chief executive officer"],
    "cfo": ["chief financial officer"],
    # add more as needed
}

_HUMOUR_LINES = {
    "elton": [
        "He’s also known as ‘Sky Daddy’—allegedly once parted the Orange River and still made the 08:00 stand-up.",
        "Rumour has it he once killed a lion with his bare hands—HR insists it was a very large house cat.",
        "Word on the street is he can debug spreadsheets by staring at them sternly.",
    ],
    "ceo": [
        "Legend says the CEO’s calendar runs on ‘Sivi Standard Time’—always three steps ahead.",
        "Apparently the CEO once negotiated with a South African thunderstorm and won.",
    ],
    "coo": [
        "The COO is rumoured to be able to schedule meetings into next week’s weather forecast.",
        "They say the COO keeps operations smoother than the N1 at 3 a.m.",
    ],
    "cfo": [
        "The CFO can spot a rounding error from across the boardroom.",
        "Legend claims the CFO once balanced a budget and a pap pot at the same time.",
    ],
}


def _inject_humor(answer: str, user_query: str) -> str:
    """
    Adds a single, light and appropriate humorous line if the query is
    about a Macrocomm person/role. Never offensive; South Africa-flavoured.
    """
    q = user_query.lower()
    chosen: List[str] = []

    # direct name checks
    for key, aliases in _DIRECTOR_KEYWORDS.items():
        if key in q or any(alias in q for alias in aliases):
            lines = _HUMOUR_LINES.get(key, [])
            if lines:
                chosen.append(random.choice(lines))

    # role-based extra check
    if "who is the coo" in q and "coo" not in chosen:
        lines = _HUMOUR_LINES.get("coo", [])
        if lines:
            chosen.append(random.choice(lines))
    if "who is the ceo" in q and "ceo" not in chosen:
        lines = _HUMOUR_LINES.get("ceo", [])
        if lines:
            chosen.append(random.choice(lines))

    if not chosen:
        return answer

    # Append one line max to keep things tight
    humour_line = chosen[0]
    if humour_line and humour_line not in answer:
        return f"{answer}\n\n{humour_line}"
    return answer


# --------------------------------------------------------------------
# 4) OPENAI CALL
# --------------------------------------------------------------------
def call_openai(messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
    """
    Minimal OpenAI completion call (Chat Completions).
    Requires OPENAI_API_KEY env set.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment.")

    if OpenAI is None:
        raise RuntimeError(
            "OpenAI SDK not installed. `pip install openai` (official v1 SDK)."
        )

    client = OpenAI(api_key=api_key)
    # Pick the model you’re using in the rest of your stack
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=messages,
    )
    text = resp.choices[0].message.content or ""
    return text.strip()


# --------------------------------------------------------------------
# 5) FASTAPI APP
# --------------------------------------------------------------------
app = FastAPI(title="Macrocomm Assistant API", version="1.0")

# CORS (relaxed for desktop wrapper / local testing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global retriever instance (rebuilt on /admin/reindex)
retriever: Callable[[str, int], List[Dict[str, str]]] | None = None


@app.on_event("startup")
def _startup() -> None:
    global retriever
    retriever = build_hybrid_retriever()


@app.get("/healthz")
def healthz():
    paths = _effective_paths()
    return JSONResponse(
        {"status": "ok", "paths": paths, "time": int(time.time())}
    )


# --------------------------------------------------------------------
# 6) DEBUG: show top-k retrieved chunks for a query
# --------------------------------------------------------------------
@app.get("/debug/retrieve")
def debug_retrieve(q: str, k: int = 5):
    """
    Return top-k retrieval results to verify coverage/grounding.
    """
    global retriever
    if retriever is None:
        raise HTTPException(status_code=503, detail="Retriever not ready.")

    docs = retriever(q, k=k)
    results = []
    for d in docs:
        results.append(
            {
                "source": d.get("source", "unknown"),
                "preview": (d.get("text", "") or "")[:500],
                "score": d.get("score", 0.0),
            }
        )
    return JSONResponse({"query": q, "k": k, "results": results})


# --------------------------------------------------------------------
# 7) MAIN CHAT ENDPOINT
# --------------------------------------------------------------------
@app.post("/chat")
def chat(payload: Dict):
    """
    POST body: {"message": "..."}
    Returns: {"answer": "...", "citations":[{source, preview}], "meta": {...}}
    """
    user_query = (payload or {}).get("message", "").strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Missing message.")

    global retriever
    if retriever is None:
        raise HTTPException(status_code=503, detail="Retriever not ready.")

    # 1) Internal retrieval
    docs = retriever(user_query, k=5)
    internal_ctx = "\n\n".join(d["text"].strip() for d in docs if d.get("text"))
    internal_cites = [
        {
            "source": d.get("source", "internal"),
            "preview": (d.get("text", "") or "")[:300],
        }
        for d in docs
    ]

    # 2) (Optional) web context — left blank in this minimal server
    web_ctx = ""

    # 3) Compose a clean prompt for British English and no markdown markers
    prompt = (
        "You are Macrocomm Assistant, a helpful, concise assistant.\n\n"
        "INTERNAL_CONTEXT:\n"
        f"{internal_ctx or '[none]'}\n\n"
        "WEB_CONTEXT:\n"
        f"{web_ctx or '[none]'}\n\n"
        "QUESTION:\n"
        f"{user_query}\n\n"
        "Instructions:\n"
        "- Use British English spelling and punctuation.\n"
        "- Prefer INTERNAL_CONTEXT for facts about Macrocomm people, roles and policies.\n"
        "- If the answer is unknown from the provided context, say you do not have that information.\n"
        "- Do not include raw citations or markdown markers such as **asterisks** or leading dashes.\n"
        "- Write clean paragraphs; bolding or styling will be handled by the client UI.\n"
    )

    answer_text = call_openai(
        messages=[
            {"role": "system", "content": "You are Macrocomm Assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,  # deterministic, reduces hallucinations
    )

    # 4) Tasteful humour if the question is about Macrocomm people/roles
    answer_text = _inject_humor(answer_text, user_query)

    return JSONResponse(
        {
            "answer": answer_text,
            "citations": internal_cites,  # UI can render these in “Sources”
            "meta": {"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini")},
        }
    )


# --------------------------------------------------------------------
# 8) ADMIN: REINDEX (rebuild retriever after you add files to /txt)
# --------------------------------------------------------------------
@app.post("/admin/reindex")
def reindex():
    """
    Rebuild the in-memory retriever. Use this after adding/removing files in /txt.
    If later you add a persistent vector DB, this is the place to trigger it.
    """
    global retriever
    try:
        retriever = build_hybrid_retriever()
        return JSONResponse({"status": "ok", "reindexed": True})
    except Exception as e:
        return JSONResponse(
            {"status": "error", "error": str(e)}, status_code=500
        )
