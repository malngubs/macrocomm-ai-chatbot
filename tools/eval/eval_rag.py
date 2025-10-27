# tools/eval/eval_rag.py
# ---------------------------------------------------------------
# Simple offline evaluator for Macrocomm RAG
# - Loads questions from eval/questions.jsonl
# - Runs retrieval and full generation
# - Scores: retrieval_hit@k, answer_keyword_score, latency_ms
# - Optional LLM-as-judge with Gemini if GEMINI_API_KEY is set
#
# Usage (PowerShell):
#   conda activate macrocomm-rag
#   python .\tools\eval\eval_rag.py
#
# Output:
#   runtime/eval_YYYYMMDD_HHMMSS.csv  and a console summary
# ---------------------------------------------------------------

import json, time, csv, re, os
from pathlib import Path
from datetime import datetime

# Import your pipeline pieces
from data.ingestion import retriever  # your Chroma retriever
from src.memory.store import MemoryStore
from src.workflow.graph import app as agent_app  # LangGraph app

MEM = MemoryStore()  # read/write same SQLite as server

EVAL_FILE = Path("eval/questions.jsonl")
RUNTIME   = Path("runtime"); RUNTIME.mkdir(exist_ok=True)

K = int(os.getenv("EVAL_K", "5"))  # top-k for retrieval

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()

def contains_all(text: str, must_include: list[str]) -> float:
    """Return fraction of required keywords present in text."""
    tx = normalize(text)
    if not must_include: return 1.0
    hits = sum(1 for term in must_include if normalize(term) in tx)
    return hits / len(must_include)

def run_agent_with_memory(user_id: str, question: str) -> str:
    """Same pattern you use in the server (memory-aware call)."""
    mem_ctx = MEM.build_context_snippet(user_id=user_id, max_turns=8, max_chars=1600)
    FORMAT_INSTRUCTION = (
        "Format your final answer as a compact numbered checklist, one step per line. "
        "Start each line with '1.', '2.', '3.' etc. Avoid long paragraphs."
    )
    if mem_ctx:
        augmented = (
            "Use the following user-specific context if relevant (do not repeat it verbatim):\n"
            f"{mem_ctx}\n\n"
            f"User question: {question.strip()}\n\n{FORMAT_INSTRUCTION}"
        )
    else:
        augmented = f"{question.strip()}\n\n{FORMAT_INSTRUCTION}"

    result = None
    for out in agent_app.stream(
        {"question": augmented, "documents": [], "web_search": False, "generation": "", "traces": []}
    ):
        for _, v in out.items(): result = v

    ans = result["generation"] if isinstance(result, dict) and "generation" in result else str(result)
    MEM.add_message(user_id, "user", question)
    MEM.add_message(user_id, "assistant", ans)
    return ans

def optional_llm_judge(question: str, ref: list[str], answer: str) -> float | None:
    """
    If GEMINI_API_KEY is set, ask Gemini to grade the answer on 0..1.
    ref (list[str]) is 'must_include' keywords (we pass them as guidance).
    Returns float or None.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        # lightweight judge via Google Generative AI
        from langchain_google_genai import ChatGoogleGenerativeAI
        judge = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.2)
        prompt = (
            "You are a strict grader. Score the student's answer for the given question 0..1.\n"
            "Consider correctness and completeness only (ignore style). "
            f"If the answer satisfies the following key points {ref}, score higher.\n\n"
            f"Question:\n{question}\n\nAnswer:\n{answer}\n\n"
            "Return ONLY a number between 0 and 1."
        )
        resp = judge.invoke(prompt)
        try:
            score = float(re.findall(r"0(?:\.\d+)?|1(?:\.0+)?", str(resp.content))[0])
            return max(0.0, min(1.0, score))
        except:
            return None
    except Exception:
        return None

def main():
    if not EVAL_FILE.exists():
        print(f"[eval] Missing {EVAL_FILE}. Create it first (see README).")
        return

    rows = []
    for line in EVAL_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        rows.append(json.loads(line))

    out_path = RUNTIME / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    print(f"[eval] Loaded {len(rows)} questions; writing {out_path}")

    fields = ["id","retrieval_hit@"+str(K),"keyword_score","judge_score","latency_ms"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()

        hits = 0; kw_sum = 0.0; judge_sum = 0.0; judge_count = 0; lat_sum = 0.0
        for i, r in enumerate(rows, 1):
            qid = r.get("id", f"q{i}")
            q   = r["question"]
            must = r.get("must_include", [])
            hint = (r.get("doc_hint") or "").lower()

            # --- retrieval ---
            docs = retriever.vectorstore.similarity_search_with_score(q, k=K)
            doc_paths = [getattr(d[0], "metadata", {}).get("source","").lower() for d in docs]
            hit = any(hint and hint in p for p in doc_paths)
            hit_val = 1 if hit else 0

            # --- generation ---
            t0 = time.perf_counter()
            ans = run_agent_with_memory("eval:user", q)
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)

            kw = contains_all(ans, must)

            judge = optional_llm_judge(q, must, ans)
            if judge is not None:
                judge_sum += judge; judge_count += 1

            lat_sum += latency_ms
            hits += hit_val; kw_sum += kw

            w.writerow({
                "id": qid,
                "retrieval_hit@"+str(K): hit_val,
                "keyword_score": round(kw, 3),
                "judge_score": ("" if judge is None else round(judge, 3)),
                "latency_ms": latency_ms
            })

    n = len(rows)
    print("\n[eval] Summary")
    print(f"  Retrieval hit@{K}: {hits}/{n} = {hits/n:.2f}")
    print(f"  Keyword score   : {kw_sum/n:.2f}")
    if judge_count:
        print(f"  Judge score     : {judge_sum/judge_count:.2f} (on {judge_count} judged)")
    print(f"  Avg latency     : {lat_sum/n:.1f} ms")
    print(f"\n[eval] Done → {out_path}")

if __name__ == "__main__":
    main()
