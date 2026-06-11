# PDFAnalyzer — Multi-Provider LLM Integration Spec v1.2

> **Status:** Draft v1.2 — pending user approval.
> **Date:** 2026-06-19
> **Scope:** All analysis methods (Method 1 `main.py`, Method 2 `full_pdf_analyzer.py`, parallel path `parallel.py`). Core change in `llm_query.py`.
> **Codebase:** PDFAnalyzer repo (public), main branch
> **Python:** 3.12.3 | **OS:** Linux (VM 100, 192.168.0.178)
>
> **Revision history:**
> - v1.0 (2026-06-19) — initial draft. Comparison mode, dual sequential runs.
> - v1.1 (2026-06-19) — simplified: single provider per run, no comparison mode (future external tool). Renamed `models.txt` → `remote_models.txt`. All statistics collected identically for both providers. Web search skipped for local (non-blocking).
> - v1.2 (2026-06-19) — removed `fetch_article_summary` from pipeline (main.py + parallel.py). Method kept in `llm_query.py` but not called. Eliminates provider asymmetry and ensures fair comparison across runs. Reduces cost (1-6 fewer API calls per PDF).

---

## 1. Goal

Enable PDFAnalyzer to route LLM calls to **either a local llama.cpp server** (Qwen3-4B on ProxMox host) **or OpenRouter** (online models), selected at invocation time. One provider per run.

Specific objectives:

1. **Provider selection** — `LLMAnalyzer` accepts a `provider` parameter (`"openrouter"` or `"local"`). One `OpenAI` client is created for the selected provider.
2. **Local LLM integration** — route calls to the existing llama.cpp server at `http://192.168.0.200:8080/v1` (Qwen3-4B-Instruct-IQ3_XS.gguf). Zero cost per call, data privacy, LAN latency.
3. **OpenRouter remains default** — without `--provider`, behavior is identical to current code (minus the removed article summary feature).
4. **Uniform statistics** — `CallRecord` captures the same metrics regardless of provider: latency, tokens, temperature, top_p, model_version. Cost is `0.0` for local, real for OpenRouter. All reporting (`*_cost.txt`, `*_summary.json`) is identical in structure.
5. **Fair comparison** — both providers receive the same prompt inputs (no article summary enrichment for either). A future external tool can compare output directories across runs.

---

## 2. Current State (Baseline)

| Aspect | Current |
|---|---|
| **Provider** | OpenRouter only (`https://openrouter.ai/api/v1`) |
| **Client** | `OpenAI(api_key=..., base_url="https://openrouter.ai/api/v1")` |
| **API key** | `ROUTER_API_KEY` from `.env` |
| **Model selection** | `models.txt` → `get_random_model()` or `--model` CLI flag |
| **Cost tracking** | 3-tier: response.usage → generation endpoint → pricing table |
| **Article summary** | `fetch_article_summary` called in `main.py:463-476` and `parallel.py:567-595`, prepended to final prompt |
| **Local LLM** | None. |

---

## 3. Architecture

### 3.1 Provider Configuration

A `ProviderConfig` dataclass defines each provider. Built at `__init__` time from env vars + constructor args.

```python
@dataclass
class ProviderConfig:
    name: str                    # "openrouter" | "local"
    base_url: str                # API endpoint
    api_key: str                 # real key or "none"
    models_file: str             # "remote_models.txt" | "local_models.txt"
    cost_per_call: bool          # False for local → cost_usd=0.0
```

Note: `supports_web_search` is removed — `fetch_article_summary` is no longer called from the pipeline (see §3.6).

### 3.2 Provider Selection in `LLMAnalyzer.__init__`

```python
def __init__(
    self,
    api_key: str | None = None,
    models_file: str = "remote_models.txt",  # CHANGED from "models.txt"
    temperature: float = 1.0,
    top_p: float = 1.0,
    provider: str = "openrouter",              # NEW
    local_base_url: str | None = None,         # NEW
):
```

**Provider resolution:**

```python
providers: dict[str, ProviderConfig] = {}

# OpenRouter (always registered if ROUTER_API_KEY exists)
router_key = api_key or os.getenv("ROUTER_API_KEY")
if router_key:
    providers["openrouter"] = ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key=router_key,
        models_file="remote_models.txt",
        cost_per_call=True,
    )

# Local LLM (from env or constructor or default)
local_url = local_base_url or os.getenv("LOCAL_LLM_BASE_URL", "http://192.168.0.200:8080/v1")
providers["local"] = ProviderConfig(
    name="local",
    base_url=local_url,
    api_key="none",
    models_file="local_models.txt",
    cost_per_call=False,
)

# Validate selection
if provider not in providers:
    raise ValueError(
        f"Unknown provider '{provider}'. Available: {list(providers.keys())}"
    )

# Create client for active provider only
active = providers[provider]
self.client = OpenAI(api_key=active.api_key, base_url=active.base_url)
self.active_provider = active
self.provider_name = provider
self.models = self._load_models(active.models_file)
```

### 3.3 Model Files

| Provider | File | Content |
|---|---|---|
| openrouter | `remote_models.txt` | Renamed from `models.txt`. Same content. |
| local | `local_models.txt` | `Qwen3-4B-Instruct-IQ3_XS.gguf` |

**`local_models.txt`** (new):
```
# Local LLM models served by llama.cpp on ProxMox host
Qwen3-4B-Instruct-IQ3_XS.gguf
```

**`remote_models.txt`** — current content of `models.txt` moved verbatim. `models.txt` is deleted after the rename to avoid confusion.

### 3.4 CallRecord Extension

One new field with default — backwards compatible:

```python
@dataclass
class CallRecord:
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    source: str                      # "openrouter" | "generation_endpoint" | "estimate" | "local"
    latency_s: float | None = None
    temperature: float | None = None
    top_p: float | None = None
    model_version: str | None = None
    provider: str | None = None      # NEW — "openrouter" | "local"
```

### 3.5 Cost Tracking per Provider

| Provider | cost_usd | source | Cost resolution path |
|---|---|---|---|
| openrouter | From response / generation endpoint / pricing table | `"openrouter"` / `"generation_endpoint"` / `"estimate"` | Existing 3-tier (unchanged) |
| local | `0.0` | `"local"` | Skip cost resolution; use `response.usage` for token counts |

**In `_record_call`:**

When `self.active_provider.cost_per_call` is `False`:

```python
if not self.active_provider.cost_per_call:
    cost_usd = 0.0
    source = "local"
```

The OpenRouter cost extraction methods (`_extract_usage`, `_fetch_generation_stats`, `_estimate_cost`) are **not called** for the local provider. Token counts (`prompt_tokens`, `completion_tokens`) are still extracted from `response.usage` (llama.cpp returns standard OpenAI-compatible `usage`).

### 3.6 Article Summary Removal

**Rationale:** `fetch_article_summary` uses web search — a capability only available via OpenRouter. Calling it for openrouter but not local creates an asymmetric prompt (one provider gets enriched context, the other doesn't). This invalidates any cross-provider comparison. Additionally, even between openrouter-only runs, the article summary is stochastic (depends on model availability, whether the article is found), introducing noise. Removing it ensures both providers always receive the same prompt structure.

**What is removed from the pipeline (not from the class):**

1. **`main.py`** — remove lines 463-476 (fetch call + save) and lines 491-496 + 514-516 (article summary section in prompt construction):
   ```python
   # REMOVED (lines 463-476):
   # article_title = extract_article_title_from_filename(pdf_path)
   # article_summary = llm_analyzer.fetch_article_summary(article_title, effective_model)
   # if article_summary: ... save to file ... else: ... warning ...

   # REMOVED (lines 491-496):
   # article_summary_section = ""
   # if article_summary:
   #     article_summary_section = f"ARTICLE SUMMARY (from internet search):\n{article_summary}\n\n"

   # REMOVED (line 514-516):
   # if article_summary_section:
   #     final_prompt_with_paragraphs = article_summary_section + final_prompt_with_paragraphs
   ```

2. **`parallel.py`** — remove lines 567-595 (fetch call + save) and lines 616-620 (article summary section in prompt construction), plus the prepend line.

3. **`*_article_summary.txt`** output file is no longer produced.

**What is kept:**

- `fetch_article_summary` method in `llm_query.py` — not deleted, just not called from the pipeline. Available for ad-hoc use or future re-introduction.
- `WEB_SEARCH_MODELS` list — kept in `llm_query.py`.
- `summary_prompt.txt` — kept as a file.

**Impact on pipeline:** The final category analysis prompt no longer has the `ARTICLE SUMMARY (from internet search):` section prepended. The prompt consists only of:
- Enablers and keywords
- Keyword counts
- Significant paragraphs

This is the same prompt both providers receive — fair comparison.

**Side benefit:** Reduces cost by 1-6 API calls per PDF (web search models are billed even when they return `SUMMARY_NOT_FOUND`). Eliminates the C2 cost leak from STATISTICS_SPEC v1.3 at the source.

### 3.7 Reporting — Identical Structure for Both Providers

All statistics are collected and displayed identically regardless of provider:

**`print_usage_summary`** — adds a `Provider:` line at the top:

```
======================================================================
TOKEN USAGE AND COST SUMMARY
======================================================================
Provider:                  local
Total API calls:           1,644
  - Local:                 1,644  (cost $0.00 — local inference)
  - OpenRouter response:   0
  - Generation endpoint:   0
  - Estimated:             0
----------------------------------------------------------------------
Prompt tokens:             655,645
Completion tokens:         3,477
Total tokens:              659,122
----------------------------------------------------------------------
Total cost:               $0.00000000 USD
======================================================================
LATENCY (per LLM call, seconds)
----------------------------------------------------------------------
calls:    1,644
min:      0.350
max:      5.213
mean:     1.520
p50:      1.402
p95:      3.100
======================================================================
```

When `provider="openrouter"`, the existing section layout is unchanged (backward compat) — only the `Provider:` line is added.

**`write_summary_json`** — adds `provider` and `cost_source` fields:

```json
{
  "run_id": "2026-06-19_10-30-00",
  "provider": "local",
  "pdf_file": "NIST.SP.800-207.pdf",
  "model_requested": "Qwen3-4B-Instruct-IQ3_XS.gguf",
  "temperature": 1.0,
  "top_p": 1.0,
  "total_api_calls": 1644,
  "total_prompt_tokens": 655645,
  "total_completion_tokens": 3477,
  "total_cost_usd": 0.0,
  "cost_source": "local",
  "latency": { ... },
  "significant_paragraphs_count": 42,
  "categories_found": 5,
  "category_results": { ... },
  "model_versions": { "Qwen3-4B-Instruct-IQ3_XS.gguf": 1644 }
}
```

Same JSON schema as STATISTICS_SPEC v1.3 R8, plus `"provider"` and `"cost_source"`. A future external tool can compare this JSON across runs from different providers.

### 3.8 Reasoning Model Validation — Local Provider

Local models (4B instruct) are NOT reasoning models. `validate_sampling_for_model` should not match them. Verify: `is_reasoning_model("Qwen3-4B-Instruct-IQ3_XS.gguf")` returns `False` (none of the `REASONING_MODEL_PATTERNS` match). No changes needed to the validation logic.

---

## 4. Configuration

### 4.1 Environment Variables (`.env`)

Existing:
```
ROUTER_API_KEY="sk-o...nNew (optional — has hardcoded default):
```
LOCAL_LLM_BASE_URL=http://192.168.0.200:8080/v1
```

### 4.2 New / Renamed Files

| File | Action | Content |
|---|---|---|
| `remote_models.txt` | **Rename** from `models.txt` | Same content (OpenRouter model names) |
| `models.txt` | **Delete** after rename | — |
| `local_models.txt` | **Create** | `Qwen3-4B-Instruct-IQ3_XS.gguf` |

### 4.3 CLI Flags

**`main.py` additions:**

```
--provider {openrouter,local}   LLM provider (default: openrouter)
--local-url URL                 Override local LLM base URL (default: LOCAL_LLM_BASE_URL env or http://192.168.0.200:8080/v1)
```

**`full_pdf_analyzer.py` additions:**

```
--provider {openrouter,local}   LLM provider (default: openrouter)
--local-url URL                 Override local LLM base URL
```

**`parallel.py`** — thread `provider` and `local_base_url` through the 3 function signatures.

### 4.4 Provider-Model Validation

The `--model` flag must reference a model valid for the active provider's models file:

```python
if args.model != "random":
    analyzer = LLMAnalyzer(provider=args.provider, local_base_url=local_url)
    if args.model not in analyzer.models:
        print(Fore.RED + f"Error: Model '{args.model}' not found in {analyzer.active_provider.models_file}" + Style.RESET_ALL)
        sys.exit(2)
```

When `--model random`, `get_random_model()` picks from the active provider's list.

---

## 5. Scope

### IN

- `llm_query.py`:
  - Add `ProviderConfig` dataclass.
  - Extend `LLMAnalyzer.__init__` with `provider`, `local_base_url`.
  - Build provider registry; create client for active provider.
  - Load models from `active.models_file`.
  - Add `provider` field to `CallRecord`.
  - In `_record_call`: set `cost_usd=0.0, source="local"` when `cost_per_call=False`; set `provider=self.provider_name`.
  - Extend `print_usage_summary` with `Provider:` line.
  - Extend `write_summary_json` with `provider` and `cost_source` fields.
  - Default `models_file` parameter changes from `"models.txt"` to `"remote_models.txt"`.
- `main.py`:
  - Add `--provider`, `--local-url` CLI flags.
  - Thread `provider` and `local_base_url` to `LLMAnalyzer()`.
  - Add provider-model validation.
  - **Remove `fetch_article_summary` call** (lines 463-476) and **article summary section in prompt** (lines 491-496, 514-516).
- `full_pdf_analyzer.py`:
  - Add `--provider`, `--local-url` CLI flags.
  - Thread to `LLMAnalyzer()`.
- `parallel.py`:
  - Thread `provider`, `local_base_url` through `run_pipeline_parallel`, `_worker_process_entry`, `process_single_pdf_v2`.
  - **Remove `fetch_article_summary` call** (lines 567-595) and **article summary section in prompt** (lines 616-620 + prepend).
- `remote_models.txt` — rename from `models.txt`.
- `local_models.txt` — new file.
- `.env` — add `LOCAL_LLM_BASE_URL` (optional).

### OUT (DO NOT TOUCH)

- `keyword_search.py` — no LLM involvement.
- `*_prompt.txt` files — no change.
- `_extract_usage`, `_fetch_generation_stats`, `_estimate_cost` — not called for local, unchanged.
- `preferred_models.txt` — unchanged.
- `fetch_article_summary` method in `llm_query.py` — kept but not called.
- `WEB_SEARCH_MODELS` list in `llm_query.py` — kept.
- `summary_prompt.txt` — kept.

### MINIMAL TOUCH (estimate)

- `llm_query.py`: ~50 LOC added (`ProviderConfig`, provider registry, conditional cost, `provider` in CallRecord + reporting)
- `main.py`: ~15 LOC added (2 argparse, provider threading, validation) — ~20 LOC removed (article summary)
- `full_pdf_analyzer.py`: ~10 LOC added (2 argparse, provider threading)
- `parallel.py`: ~10 LOC added (2 params × 3 signatures, threading) — ~25 LOC removed (article summary)
- Config files: 1 rename + 1 new + 1 `.env` line
- Total: ~85 LOC added, ~45 LOC removed across 4 files. No new dependencies.

---

## 6. Implementation Order (incremental, "test 1 by 1")

- [ ] **E1 — `ProviderConfig` dataclass + `CallRecord.provider` field**: Add the dataclass and the new field (default `None`). No other code changes. **Test:** `import llm_query; p = ProviderConfig(name="test", base_url="http://localhost/v1", api_key="none", models_file="local_models.txt", cost_per_call=False); cr = CallRecord(model="x", prompt_tokens=1, completion_tokens=1, cost_usd=0.0, source="test")` — old-style construction still works.

- [ ] **E2 — Provider registry in `LLMAnalyzer.__init__`**: Extend constructor with `provider` and `local_base_url`. Build provider registry. Create `OpenAI` client for active provider. Store `self.active_provider`, `self.provider_name`. Change default `models_file` from `"models.txt"` to `"remote_models.txt"`. **Test:** `LLMAnalyzer(provider="openrouter")` works as before; `LLMAnalyzer(provider="local")` creates client at `http://192.168.0.200:8080/v1`; `LLMAnalyzer(provider="invalid")` raises `ValueError`.

- [ ] **E3 — Rename `models.txt` → `remote_models.txt` + create `local_models.txt`**: `git mv models.txt remote_models.txt`. Create `local_models.txt` with `Qwen3-4B-Instruct-IQ3_XS.gguf`. **Test:** `LLMAnalyzer(provider="openrouter")` loads from `remote_models.txt` (same models as before); `LLMAnalyzer(provider="local")` loads from `local_models.txt` (1 model).

- [ ] **E4 — Conditional cost tracking + provider in CallRecord**: In `_record_call`, when `self.active_provider.cost_per_call` is `False`, set `cost_usd=0.0, source="local"`, skip `_fetch_generation_stats` and `_estimate_cost`. Extract token counts from `response.usage` (llama.cpp returns standard `usage`). Set `provider=self.provider_name` on every `CallRecord`. **Test (integration):** Make a single local call: `a = LLMAnalyzer(provider="local"); a.analyze_single_occurrence("Is this significant?", "Qwen3-4B-Instruct-IQ3_XS.gguf")` — assert `call_records[-1].cost_usd == 0.0`, `.source == "local"`, `.provider == "local"`, `.prompt_tokens > 0`, `.latency_s > 0`.

- [ ] **E5 — Remove `fetch_article_summary` from `main.py` pipeline**: Remove lines 463-476 (fetch call + save) and lines 491-496 + 514-516 (article summary section construction + prepend). **Test:** Run `main.py` with a single PDF (openrouter, sequential) — verify no `Fetching article summary` message appears, no `*_article_summary.txt` file is created, analysis completes normally, `*_cost.txt` has fewer API calls than baseline (1-6 fewer — the web search calls are gone).

- [ ] **E6 — Remove `fetch_article_summary` from `parallel.py` pipeline**: Remove lines 567-595 (fetch call + save) and lines 616-620 + prepend line (article summary section in prompt). **Test:** Run with `--parallel` — verify same behavior as E5 (no article summary, analysis completes).

- [ ] **E7 — Reporting extensions**: Add `Provider:` line to `print_usage_summary`. Add `provider` and `cost_source` fields to `write_summary_json`. **Test:** Run a single local call, call `print_usage_summary()` — assert output shows `Provider: local`, `$0.00000000 USD (local)`. Call `write_summary_json()` — assert JSON has `"provider": "local"`, `"cost_source": "local"`.

- [ ] **E8 — CLI flags in `main.py`**: Add `--provider`, `--local-url`. Thread to `LLMAnalyzer()`. Add provider-model validation. **Test:** `python main.py --help` shows new flags. `python main.py ... --provider local` uses local. `--provider local --model google/gemini-3-flash-preview` exits code 2.

- [ ] **E9 — CLI flags in `full_pdf_analyzer.py`**: Add `--provider`, `--local-url`. Thread to `LLMAnalyzer()`. **Test:** `python full_pdf_analyzer.py --help` shows new flags.

- [ ] **E10 — Parallel path integration**: Thread `provider` and `local_base_url` through `parallel.py` (`run_pipeline_parallel`, `_worker_process_entry`, `process_single_pdf_v2`). **Test:** `python main.py ... --parallel --provider local` — verify `*_cost.txt` shows `Provider: local`.

- [ ] **E11 — `.env` update**: Add `LOCAL_LLM_BASE_URL=http://192.168.0.200:8080/v1` to `.env`. **Test:** Remove `--local-url` flag, set env var to a different URL, verify `LLMAnalyzer(provider="local")` connects to the env var URL.

- [ ] **E12 — Smoke test (sequential, local provider)**: Run a single PDF with `--provider local`. Acceptance:
  - Analysis completes without errors.
  - Significant occurrences are produced.
  - `*_cost.txt` shows `Provider: local`, `$0.00000000 USD`.
  - `*_summary.json` has `"provider": "local"`, `"cost_source": "local"`.
  - All `call_records` have `source="local"`, `cost_usd=0.0`, `provider="local"`.
  - No `*_article_summary.txt` file produced.
  - LATENCY section has real values.

- [ ] **E13 — Smoke test (sequential, openrouter, backward compat)**: Run a single PDF WITHOUT `--provider` (default openrouter). Acceptance:
  - Results match current code minus article summary (same significant paragraphs, same call count minus web search calls).
  - `*_cost.txt` shows `Provider: openrouter`.
  - `*_summary.json` has `"provider": "openrouter"`.
  - No `*_article_summary.txt` file produced.

- [ ] **E14 — Commit + readme**: Update `readme.md` with a "Multi-provider LLM support" section and note the article summary removal. Conventional commit: `feat(providers): add local LLM provider, remove article summary from pipeline (v1.2)`.

---

## 7. Acceptance Criteria

| # | Criterion | How Verified |
|---|-----------|--------------|
| A1 | `python main.py --help` shows `--provider` and `--local-url` | Manual `--help` |
| A2 | `--provider openrouter` (default) produces results identical to current code minus article summary | Diff against baseline run (paragraph counts match, cost reduced by web search calls) |
| A3 | `--provider local` completes a full PDF analysis using Qwen3-4B | Smoke test E12 |
| A4 | Local calls record `cost_usd=0.0, source="local"` in `CallRecord` | Check `call_records` |
| A5 | Local calls record `provider="local"` in `CallRecord` | Check `call_records` |
| A6 | Local calls have non-None `latency_s` and `prompt_tokens > 0` in `CallRecord` | Check `call_records` |
| A7 | No `*_article_summary.txt` file is produced in any run (openrouter or local) | `ls` after run |
| A8 | `*_cost.txt` shows `Provider: <name>` for both providers | Inspect output |
| A9 | `*_summary.json` contains `"provider"` and `"cost_source"` fields | `python -c "import json; ..."` |
| A10 | `--provider invalid` raises `ValueError` | Inline Python check |
| A11 | `--provider local --model google/gemini-3-flash-preview` exits code 2 | CLI test |
| A12 | Running without `--provider` defaults to `openrouter` (backward compat) | Run + check output |
| A13 | No new dependencies in `requirements.txt` | `git diff requirements.txt` empty |
| A14 | `--parallel --provider local` works | Run + verify output |
| A15 | `LOCAL_LLM_BASE_URL` env var overrides default local URL | Set env, run, verify |
| A16 | `local_models.txt` exists with at least one model | File exists |
| A17 | `remote_models.txt` exists (renamed from `models.txt`) | File exists |
| A18 | `models.txt` no longer exists (renamed, not copied) | `ls models.txt` fails |
| A19 | Statistics structure (latency, tokens, model version) is identical for both providers | Compare `*_cost.txt` sections from openrouter vs local runs |
| A20 | `fetch_article_summary` method still exists in `llm_query.py` (not deleted, just not called) | `grep -c fetch_article_summary llm_query.py` > 0 |

---

## 8. Local LLM Infrastructure Facts

| Fact | Detail |
|---|---|
| **Server** | llama.cpp `llama-server` on ProxMox host (192.168.0.200:8080) |
| **Model** | `Qwen3-4B-Instruct-IQ3_XS.gguf` (4B params, IQ3_XS quant, ~1.73 GB) |
| **API** | OpenAI-compatible: `/v1/chat/completions`, `/v1/models`, `/health` |
| **Context** | 65536 tokens (`--ctx-size 65536`) |
| **Auth** | None (`api_key="none"`) |
| **Performance** | ~50-150 tok/s prompt, ~19-21 tok/s generation (Vulkan GPU, Radeon 780M) |
| **Cost** | $0.00 per call |
| **Limitations** | No web search; 4B model less capable than GPT-5/Gemini for complex analysis; single model served at a time |
| **Firewall** | iptables rule on ProxMox allows VM 100 → host port 8080 |
| **Systemd** | `llama-server.service`, `Restart=always` |
| **Health check** | `curl -s http://192.168.0.200:8080/health` → `{"status":"ok"}` |

---

## 9. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Local model quality worse than OpenRouter for PDF analysis | Medium | Acceptable tradeoff — local is for privacy/cost savings. User decides per run. |
| llama.cpp server unavailable (host down / service stopped) | Medium | Connection timeout + clear error. Suggest `--provider openrouter`. |
| Local model cannot handle full prompt context for very long PDFs | Medium | `--ctx-size 65536` covers most papers. Very long PDFs may truncate. Future: context length check. |
| Removing article summary reduces analysis quality | Low | Article summary was stochastic enrichment, not core input. Both providers lose it equally — fair comparison. Users who need it can call `fetch_article_summary` ad-hoc. |
| `models.txt` rename breaks external scripts | Low | `models.txt` only referenced by `LLMAnalyzer._load_models()`. Rename is safe. |
| `_estimate_cost` not called for local but still exists | Low | Dead code for local path, harmless. No removal needed. |
| `LOCAL_LLM_BASE_URL` default wrong on different networks | Low | `--local-url` flag + `.env` override. Default matches ProxMox setup. |
| `CallRecord.provider` field breaks external positional construction | Low | No external constructors found (same argument as STATISTICS_SPEC). |

---

## 10. Open Questions

None.

---

## 11. Future Work (out of scope)

- **External comparison tool**: Reads `*_summary.json` from multiple runs (different providers, models, temperatures) and produces cross-run statistics + text diffs.
- **Additional local models**: Swap Qwen3-4B via `local_models.txt` + systemd restart on ProxMox.
- **Context length guard**: Check estimated token count against server `--ctx-size` before sending.
- **Ollama on VM**: More model flexibility, but requires RAM (~8 GB for 4B model).
- **Article summary re-introduction**: If web search becomes available locally (e.g., via a RAG pipeline or a web-search proxy), the feature can be re-enabled in the pipeline. The method is preserved in `llm_query.py`.
