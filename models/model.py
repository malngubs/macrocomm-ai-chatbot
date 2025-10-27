# models/model.py
# ----------------
# Gemini-first model router using the LangChain Gemini wrapper.
# Falls back to local Llama *only if available*; otherwise returns a clear message.
# This avoids the previous SDK invocation mismatch that silently triggered fallback.

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # read .env (GOOGLE_API_KEY / GEMINI_API_KEY)

@dataclass
class GeminiConfig:
    # Prefer GOOGLE_API_KEY (used broadly in LangChain examples)
    api_key: str = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    model_fast: str = os.getenv("GEMINI_FAST_MODEL", "gemini-2.5-flash")
    model_reason: str = os.getenv("GEMINI_REASON_MODEL", "gemini-2.5-pro")
    temperature: float = 0.2
    max_output_tokens: int = 2048

@dataclass
class LlamaConfig:
    # Optional local fallback (set LLAMA_GGUF_PATH if you have a file)
    gguf_path: str = os.getenv("LLAMA_GGUF_PATH", "")
    n_ctx: int = 8192
    temperature: float = 0.2
    max_tokens: int = 1024

class ModelRouter:
    """
    - Primary: Gemini 2.5 Flash (fast) or Pro (heavy) via LangChain's ChatGoogleGenerativeAI.
    - Fallback: local Llama via llama.cpp *if* configured; otherwise return a helpful message.
    """

    def __init__(self, gcfg: GeminiConfig = GeminiConfig(), lcfg: LlamaConfig = LlamaConfig()):
        self.gcfg = gcfg
        self.lcfg = lcfg

        # --- Set up Gemini (LangChain wrapper) ---
        self._gem_fast = None
        self._gem_heavy = None
        if self.gcfg.api_key:
            # Uses the google-generativeai client under the hood
            from langchain_google_genai import ChatGoogleGenerativeAI
            self._gem_fast = ChatGoogleGenerativeAI(
                model=self.gcfg.model_fast,
                google_api_key=self.gcfg.api_key,
                temperature=self.gcfg.temperature,
                max_output_tokens=self.gcfg.max_output_tokens,
            )
            self._gem_heavy = ChatGoogleGenerativeAI(
                model=self.gcfg.model_reason,
                google_api_key=self.gcfg.api_key,
                temperature=self.gcfg.temperature,
                max_output_tokens=self.gcfg.max_output_tokens,
            )

        # --- Optional local fallback (only if you have a GGUF path set up) ---
        self._llama = None
        try:
            if self.lcfg.gguf_path:
                from llama_cpp import Llama
                self._llama = Llama(model_path=self.lcfg.gguf_path, n_ctx=self.lcfg.n_ctx)
        except Exception:
            # On Windows without build tools, this may fail — that's OK; we keep Gemini-only
            self._llama = None

    # --------------------------- Internal helpers ----------------------------

    def _llama_chat(self, prompt: str) -> str:
        """
        Try local Llama if available; otherwise explain that fallback is disabled.
        """
        if self._llama is None:
            return (
                "[Fallback disabled] Local Llama is not configured. "
                "Gemini should handle this request. If you want a local fallback on Windows, "
                "use Ollama (recommended) or install llama-cpp-python from a prebuilt wheel."
            )
        out = self._llama(
            prompt=prompt,
            temperature=self.lcfg.temperature,
            max_tokens=self.lcfg.max_tokens,
        )
        return out["choices"][0]["text"]

    # ---------------------------- Public method ------------------------------

    def generate(self, prompt: str, heavy: bool = False) -> str:
        """
        Main generation entry point for the app.
        - Use Gemini (fast/pro) first.
        - If Gemini raises (quota/network/config), try local Llama if present.
        - Otherwise, return a clear error string so you can see what's wrong.
        """
        try:
            llm = self._gem_heavy if heavy else self._gem_fast
            if llm is None:
                raise RuntimeError("Gemini key missing (GOOGLE_API_KEY / GEMINI_API_KEY not set?)")
            # ChatGoogleGenerativeAI returns a ChatMessage object; use .content
            resp = llm.invoke(prompt)
            return getattr(resp, "content", str(resp))
        except Exception as e:
            # Last resort: local llama, or a readable error
            try:
                return self._llama_chat(prompt)
            except Exception:
                return f"[Gemini error] {e.__class__.__name__}: {e}"

# Export singleton
llm_model = ModelRouter()

