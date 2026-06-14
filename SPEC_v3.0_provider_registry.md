# Spec v3.0 — Provider/Model Selection Refactor in `PDFAnalyzer/llm_query.py`

> **Status:** Draft awaiting user approval.
> **Date:** 2026-06-14
> **Supersedes:** MULTIPROVIDER_SPEC v1.2 (the inline ``ProviderConfig`` registry in ``LLMAnalyzer.__init__``).
> **Scope:** Provider/model selection in ``PDFAnalyzer/llm_query.py``. **The user explicitly asked for new functions and classes; backward compat for callers is preserved but the internal architecture is fully reworked.**

## 1. Goal

Replace the inline, hardcoded two-provider ("openrouter", "local") ``ProviderConfig`` registry inside ``LLMAnalyzer.__init__`` with a **data-driven, registry-based** provider/model system that:

1. Supports an arbitrary number of providers (OpenRouter, Google AI Studio, local llama.cpp, future additions) declared in a single config file.
2. Maps each model name to exactly one provider **without** the caller having to specify a `provider` flag — the registry resolves it.
3. Preserves the existing text-file format of `remote_models.txt` and `local_models.txt` (per user request: "manter os arquivos de modelo") — these files are the per-provider model registries.
4. Adds `google_models.txt` as a new per-provider model registry for Google AI Studio.
5. Keeps every existing call site (main.py, full_pdf_analyzer.py, parallel.py) working **without code changes to those files** — the only required change at the call site is removing the now-unused `provider` arg (deprecation path, not a hard break).

## 2. Experimental Design (unchanged from v1.3.1)

The PDFAnalyzer's role is unchanged: it acts as a black-box subprocess that takes a PDF and produces analysis outputs. What changes is *which* provider it talks to for the LLM call.

After the refactor, a single subprocess can serve models from any registered provider — the new `gemma-4-26b-a4b-it:free` (Google AI Studio) will be reachable from the same subprocess, just with a different model name string.

## 3. INPUT / OUTPUT / MINIMAL TOUCH

### INPUT

- The refactor accepts the following new artifacts:
  - `PDFAnalyzer/google_models.txt` (new) — same format as `remote_models.txt` (one model per line, `#` for whole-line comments, inline comments stripped).
  - `PDFAnalyzer/providers.json` (new) — JSON config that declares all known providers (base URL, env var for API key, models file, cost strategy, rate-limit notes).
  - `PDFAnalyzer/remote_models.txt` (unchanged format) — still the OpenRouter model list.
  - `PDFAnalyzer/local_models.txt` (unchanged format, already deprecated v1.3) — still the local model list.
  - Environment variables: `ROUTER_API_KEY` (unchanged), `GOOGLE_API_KEY` (new), `LOCAL_LLM_BASE_URL` (unchanged).

- The refactor does NOT change:
  - `main.py` and `full_pdf_analyzer.py` flag surface (the `--provider`, `--local-url` flags stay, but become optional; if omitted, the LLMAnalyzer auto-detects from the model name).
  - The output JSON schema of `summary.json` / `2_full_text_analysis_summary.json`.
  - The call signature of `analyze()` / `analyze_single_occurrence()` / `fetch_article_summary()`.

### OUTPUT

- A model name passed to ``LLMAnalyzer`` is resolved to the right provider via a lookup in the registry. The caller does not need to know which provider the model belongs to.
- Cost tracking is per-provider: OpenRouter and Google AI Studio return cost in the response (via ``response.usage.model_extra['cost']`` or equivalent); local models report $0.
- All existing call sites (``main.py``, ``full_pdf_analyzer.py``, ``parallel.py``) continue to work with **zero changes** because the ``--provider`` flag is still accepted (deprecated; if absent, auto-detect).

### MINIMAL TOUCH

- The new code lives in **two new modules** (`providers.py`, `model_registry.py`) and **one rewritten module** (`llm_query.py`). The rest of `PDFAnalyzer/` is untouched.
- No new runtime dependencies (stdlib only: `json`, `pathlib`, `dataclasses`).
- No new environment variables are required (the existing `ROUTER_API_KEY` keeps working; `GOOGLE_API_KEY` is only needed if you actually invoke a Google model).
- The text files keep their current format — existing line-by-line edits, comments, and `:free` annotations all work without modification.

## 4. Affected files

| File | Change | Risk |
|---|---|---|
| `PDFAnalyzer/providers.json` (NEW) | Declarative list of all providers (base URL, env var, cost strategy) | None — pure config |
| `PDFAnalyzer/google_models.txt` (NEW) | List of Google AI Studio models (e.g., `gemini-2.5-flash`, `gemma-4-26b-a4b-it:free`) | None — read-only registry |
| `PDFAnalyzer/llm_query.py` (REWRITE) | New `ModelRegistry` class, provider lookup, deprecated `provider` arg in `LLMAnalyzer.__init__` | Medium — biggest change, but the public surface is preserved |
| `PDFAnalyzer/providers.py` (NEW) | New `ProviderSpec` dataclass + `ProviderRegistry` class with build-in `default_providers()` factory | None — new module |
| `PDFAnalyzer/model_registry.py` (NEW) | New `ModelRegistry` class: loads all model files, builds (model_name → provider) mapping, exposes `resolve(model_name) -> provider_id` | None — new module |
| `PDFAnalyzer/main.py` (NO change) | The `--provider` and `--local-url` flags stay; if absent, `LLMAnalyzer` auto-resolves. Tested by re-running the v1.3.1 dry-run. | Low |
| `PDFAnalyzer/full_pdf_analyzer.py` (NO change) | Same. | Low |
| `PDFAnalyzer/parallel.py` (NO change) | Same. | Low |
| `PDFAnalyzer/remote_models.txt` (NO change) | Already lists Google Gemma 4 free tier (per v1.3.1 spec). | None |
| `PDFAnalyzer/local_models.txt` (NO change) | Already deprecated. | None |

## 5. New module APIs

### 5.1 `PDFAnalyzer/providers.py` (new)

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ProviderSpec:
    """Static description of an LLM provider — base URL, credentials, cost strategy."""
    id: str                           # e.g. "openrouter", "google", "local"
    base_url: str                     # OpenAI-compatible base URL
    api_key_env: str                  # env-var name that holds the API key
    models_file: str                  # filename (relative to PDFAnalyzer dir)
    cost_per_call: bool               # True if the API returns cost in the response
    default_api_key: str = "none"     # literal value when no real key is needed (e.g. local)

    def resolve_api_key(self) -> str:
        """Return the API key from the environment, or default_api_key if unset."""
        return os.getenv(self.api_key_env) or self.default_api_key


def default_providers() -> dict[str, ProviderSpec]:
    """Return the v3.0 default provider registry. Pure data; no side effects."""
    return {
        "openrouter": ProviderSpec(
            id="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="ROUTER_API_KEY",
            models_file="remote_models.txt",
            cost_per_call=True,
        ),
        "google": ProviderSpec(
            id="google",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key_env="GOOGLE_API_KEY",
            models_file="google_models.txt",
            cost_per_call=True,
        ),
        "local": ProviderSpec(
            id="local",
            base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://192.168.0.200:8080/v1"),
            api_key_env="LOCAL_LLM_API_KEY",  # or empty
            models_file="local_models.txt",
            cost_per_call=False,
            default_api_key="none",
        ),
    }
```

### 5.2 `PDFAnalyzer/model_registry.py` (new)

```python
from pathlib import Path
from providers import ProviderSpec, default_providers

class ModelRegistry:
    """Maps ``model_name`` → ``provider_id`` for a given set of providers.

    Built by:
    1. Loading each provider's models file (per ``ProviderSpec.models_file``).
    2. Building a dict ``{model_name: provider_id}``.
    3. Caching the lookup for fast ``resolve()`` calls.

    A model that appears in more than one providers' files is flagged as
    a *conflict* at construction time (the constructor logs a warning and
    keeps the first occurrence). A model that doesn't appear in any file
    is *unregistered*: ``resolve()`` returns ``None`` and the LLMAnalyzer
    raises a clear ``UnknownModelError`` with the list of known models.
    """

    def __init__(self, providers: dict[str, ProviderSpec],
                 pdfanalyzer_dir: Path | None = None,
                 log=print):
        ...

    def resolve(self, model_name: str) -> str | None:
        """Return the provider id for ``model_name``, or ``None`` if unregistered."""

    def known_models(self) -> list[str]:
        """Return all registered model names, sorted."""

    def provider_of(self, model_name: str) -> ProviderSpec | None:
        """Return the full ProviderSpec for ``model_name``'s provider."""
```

### 5.3 `llm_query.py` changes

The ``LLMAnalyzer`` class keeps the same public surface (constructor, `analyze()`, `analyze_single_occurrence()`, `fetch_article_summary()`, `get_random_model()`, `_load_models`, `call_records`, etc.) but the **internals** are rewritten:

- **NEW constructor signature** (additive — old positional args keep working but emit a ``DeprecationWarning``):
  ```python
  def __init__(self,
               api_key: str | None = None,             # DEPRECATED, see below
               models_file: str = "remote_models.txt", # DEPRECATED — derived from registry
               temperature: float = 1.0,
               top_p: float = 1.0,
               provider: str | None = None,           # DEPRECATED, see below
               local_base_url: str | None = None,     # DEPRECATED, see below
               pdfanalyzer_dir: Path | None = None,  # NEW — root for providers.json
               model_registry: ModelRegistry | None = None):  # NEW — inject for tests
  ```

- **NEW behaviour** when `provider` is not given:
  1. Load `providers.json` from `pdfanalyzer_dir` (or use `default_providers()`).
  2. Build a `ModelRegistry` from the providers.
  3. The first model in the merged registry (or the first model passed via `--model` CLI flag) determines the active provider. The LLMAnalyzer sets `self.active_provider` to that provider's `ProviderSpec`, builds an `OpenAI` client with the provider's `base_url` + `api_key`, and loads the provider's `models_file` into `self.models`.

- **DEPRECATION policy**:
  - Passing `provider="openrouter"` (or `"local"`, `"google"`) still works but logs a `DeprecationWarning` and uses that provider.
  - Passing `local_base_url=...` only takes effect when the resolved provider is `"local"`.
  - All deprecated args are removed in a future v4.0.

- **Cost tracking changes**:
  - The `cost_per_call` flag moves from `ProviderConfig` to `ProviderSpec.cost_per_call`.
  - The OpenRouter-specific `_fetch_generation_stats` path is generalised: a new helper `_fetch_generation_stats_for(provider, generation_id)` is called only for `provider.cost_per_call=True`. Local providers skip it.
  - A new helper `_extract_google_cost(response)` handles the Google AI Studio response shape (which differs slightly from OpenRouter's `model_extra['cost']`).

## 6. Configuration files (new)

### 6.1 `PDFAnalyzer/providers.json` (new)

```json
{
  "_comment": "v3.0: declarative provider registry. Edit this file to add a new provider; llm_query.py will pick it up automatically.",
  "providers": {
    "openrouter": {
      "base_url": "https://openrouter.ai/api/v1",
      "api_key_env": "ROUTER_API_KEY",
      "models_file": "remote_models.txt",
      "cost_per_call": true,
      "rate_limit_note": "Paid tier ~100+ req/min; free tier 16-20 req/min per account"
    },
    "google": {
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
      "api_key_env": "GOOGLE_API_KEY",
      "models_file": "google_models.txt",
      "cost_per_call": true,
      "rate_limit_note": "Free tier ~60 req/min for gemini-2.5-flash, ~30 req/min for gemma-4-26b-a4b-it:free"
    },
    "local": {
      "base_url": "http://192.168.0.200:8080/v1",
      "api_key_env": "LOCAL_LLM_API_KEY",
      "models_file": "local_models.txt",
      "cost_per_call": false,
      "default_api_key": "none",
      "rate_limit_note": "Local GPU; throughput depends on hardware"
    }
  }
}
```

### 6.2 `PDFAnalyzer/google_models.txt` (new)

```
# Google AI Studio models (Gemini + Gemma).
# Same format as remote_models.txt: one model per line, '#' for comments.
# Validated against `providers.json`'s google.models_file at startup.

# Gemini family (free tier, 60 req/min)
gemini-2.5-flash
gemini-2.5-flash-lite
gemini-2.5-pro
gemini-3.0-flash-preview
gemini-3.1-flash-lite-preview

# Gemma 4 family (free tier, ~30 req/min for gemma-4-26b-a4b-it:free)
google/gemma-4-26b-a4b-it
google/gemma-4-26b-a4b-it:free
google/gemma-4-31b-it
google/gemma-4-31b-it:free
```

## 7. Behaviour matrix (E0–E5)

- **E0 — no flag passed**: `LLMAnalyzer()` builds a `ModelRegistry` from `providers.json` + all 3 model files, picks the first registered model as the "active" one, builds an `OpenAI` client for that provider.
- **E1 — `--model "X"` only (no `--provider`)**: registry resolves `X` → provider; client built for that provider; `self.models` loaded from that provider's models file.
- **E2 — `--model "X" --provider "Y"` (legacy)**: if `X` is in `Y`'s models, use it; if not, log a `UserWarning` and fall back to the registry resolution.
- **E3 — `--model "X"` where `X` is unregistered**: `LLMAnalyzer.__init__` raises `UnknownModelError("'X' is not in any provider's models file. Known models: [...]")`.
- **E4 — `--provider "Y"` only (no model)**: deprecated; falls back to first model in `Y`'s models file.
- **E5 — provider requested but its API key env var is unset**: raises `MissingAPIKeyError("Provider 'Y' requires env var 'Z' to be set. Either set it or remove the provider from providers.json.")`. Providers with `cost_per_call=False` (i.e. local) are exempt — they fall back to `default_api_key`.

## 8. Cost accuracy per provider

- **OpenRouter**: unchanged. Cost comes from `response.usage.model_extra['cost']` (zero-latency, accurate). Fallback to `/api/v1/generation?id=<id>` if the response doesn't carry cost metadata.
- **Google AI Studio**: cost comes from `response.usage.prompt_tokens` × per-1M-token rate (the Google API doesn't return cost in the response for the OpenAI-compat endpoint; we estimate from token counts and a per-model rate table). The estimation is best-effort: ±10% accuracy vs. the actual billing.
- **Local**: cost is always 0.0; `source` is `"local"`.

The new helper `_extract_google_cost(response, model_name)` is added to ``llm_query.py`` and is called when the active provider is `google`. The per-model rate table is a module-level constant in ``llm_query.py`` (initial values: $0.30/M input for gemini-2.5-flash, $0.06/M for gemma-4-26b-a4b-it, etc. — sourced from Google AI Studio's published pricing as of 2026-06-14).

## 9. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Existing call sites (`main.py`, `full_pdf_analyzer.py`, `parallel.py`) break because they pass a `provider` arg | Very low | Critical | The `provider` arg is kept in the constructor with a `DeprecationWarning`. All three call sites tested via the v1.3.1 dry-run before commit. |
| A model is registered in two providers' files → ambiguous routing | Low | Critical | `ModelRegistry.__init__` logs a warning at construction and picks the first occurrence deterministically. The spec recommends **never** duplicate a model name across files. |
| `providers.json` is missing or malformed | Medium | Fatal at startup | `LLMAnalyzer` falls back to `default_providers()` (the hardcoded spec) if the file is missing, but raises `InvalidProviderConfigError` if it's malformed (parse error, missing required field). |
| Cost accuracy for Google AI Studio drifts from real billing | Medium | Low | Cost is reported with a `source: "google_estimate"` flag; downstream analysis can opt to filter or use a different aggregation. |
| Backward-compat with the v1.2 ``MULTIPROVIDER_SPEC`` flag surface | Low | Low | The `--provider` and `--local-url` CLI flags are preserved; the internal ``provider`` constructor arg accepts the old values with a warning. |

## 10. Rollback

- The rewrite lives in two new modules (`providers.py`, `model_registry.py`) and one rewritten module (`llm_query.py`). To roll back:
  ```bash
  git checkout llm_query.py    # restores the v1.2 hardcoded 2-provider registry
  rm providers.py model_registry.py providers.json
  ```
- The text files (`remote_models.txt`, `local_models.txt`) are untouched, so no data loss.
- The Google model support is a net add: even after rollback, `google_models.txt` and the `GOOGLE_API_KEY` env var remain in place for future use.

## 11. Verification (E6–E9)

- **E6 — unit test**: instantiate ``ModelRegistry`` with all 3 providers, assert ``resolve("google/gemma-4-26b-a4b-it:free") == "google"`` and ``resolve("qwen/qwen-turbo") == "openrouter"``.
- **E7 — backward compat**: run the v1.3.1 dry-run (60 commands, 5 trials, cells C, D) and assert the dispatched ``--model`` and ``--provider`` flags are correct.
- **E8 — Google AI Studio smoke test**: 1-PDF, 1-trial run with ``--model google/gemma-4-26b-a4b-it:free``; verify a ``<pdf>_summary.json`` is produced.
- **E9 — error path**: instantiate ``LLMAnalyzer`` with ``--model "totally/made-up-model"`` and assert a clear ``UnknownModelError`` is raised with the list of known models.

## 12. Acceptance criteria

- [ ] `providers.json` exists and validates as JSON.
- [ ] `google_models.txt` exists with the 7 models listed in §6.2.
- [ ] `model_registry.py` and `providers.py` exist and have docstrings.
- [ ] `llm_query.py` no longer contains the inline `ProviderConfig` registry.
- [ ] `LLMAnalyzer.__init__` accepts the new args (`pdfanalyzer_dir`, `model_registry`) and the deprecated args (`api_key`, `models_file`, `provider`, `local_base_url`).
- [ ] Deprecation warnings are issued on every call that uses the old args.
- [ ] The v1.3.1 dry-run still produces 60 commands with correct `--model` flags.
- [ ] Smoke test with `--model google/gemma-4-26b-a4b-it:free` returns a real ``<pdf>_summary.json`` (proves Google AI Studio integration works).
- [ ] Cost estimates for Google calls are within ±10% of the actual token-count-based cost.
- [ ] `main.py`, `full_pdf_analyzer.py`, `parallel.py` are **not modified** (the v3.0 contract is internal to `llm_query.py`).

---

**Implementation order** (after spec approval):
1. E0: create `providers.json` and `google_models.txt`.
2. E1: write `providers.py` (ProviderSpec + default_providers).
3. E2: write `model_registry.py` (ModelRegistry).
4. E3: rewrite `llm_query.py` to consume the new modules.
5. E4: run unit tests (E6), backward-compat dry-run (E7), and Google smoke test (E8).
6. E5: re-run the v1.3.1 cells C+D experiment with `--model google/gemma-4-26b-a4b-it:free` to confirm end-to-end.
7. E6: update `SPEC_v1.3.1_free_tier.md` to point to v3.0 and remove the v1.3.1-specific text.
