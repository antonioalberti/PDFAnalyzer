# PDFAnalyzer — Statistics Enhancement Spec v1.3

> **Status:** Draft v1.3 — pending user approval.
> **Date:** 2026-06-15
> **Scope:** Method 1 (`main.py`) + Method 2 (`full_pdf_analyzer.py`) + parallel path (`parallel.py`). All share `LLMAnalyzer` in `llm_query.py`.
> **Codebase:** PDFAnalyzer repo (public), main branch
> **Python:** 3.12.3 | **OS:** Linux
>
> **Revision history:**
> - v1.0 (2026-06-11) — initial draft. Scope closed to 4 items: latency, temperature, top-p, model version. Prompt versioning deferred (user decision 2026-06-11).
> - v1.1 (2026-06-11) — conservative sampling validation added (R6 mitigation, user decision option A). New helper `validate_sampling_for_model()` in `llm_query.py`; enforcement at CLI parse time and at runtime in `_complete`. Acceptance criteria A9–A11 added. Implementation order grew from 9 to 12 etapas (new E3 for helper, E7 for CLI validation, E11 for reasoning-model rejection check).
> - v1.2 (2026-06-14) — critical review: 17 issues found, 4 critical, 3 high, 7 medium, 3 low. All fixes integrated below. Key changes from v1.1: (a) `fetch_article_summary` calls now tracked via new `_timed_create` helper (P1); (b) `parallel.py` removed from OUT — must be touched to thread temperature/top_p (P2); (c) `latency_s` default changed from `0.0` to `None` to avoid false-minimum in percentile stats (P4); (d) `validate_sampling_for_model` in runtime path uses warn+override instead of raise (P6); (e) `generation_id` diff corrected to use `response.id` (P3); (f) `generate_cost_summary.py` reference removed (P8); (g) line numbers re-verified post-parallelization; (h) `model_version` per model can be multi-valued (P7); (i) percentile implementation specified (P11).
> - v1.3 (2026-06-15) — cost calculation audit: 4 pricing errors in `_fallback_pricing` (C1), `fetch_article_summary` cost leak (C2), `_estimate_cost` design issues (C3–C5), missing-model default too low (C6). New §10 added. Etapas E4 and E5 updated. Also added: Results directory with timestamped runs (R7), per-run summary JSON for variance analysis (R8), and batch runner design for repeated trials (R9) — addresses reviewer critique "without repeated trials and variance analysis, the reproducibility claim remains insufficiently demonstrated".

---

## 1. Goal

Enhance the per-PDF cost/execution statistics emitted by PDFAnalyzer so users can:

1. **Diagnose performance** — know the latency distribution of individual LLM calls (min/max/mean/p50/p95/p99) and identify outliers.
2. **Reproduce runs** — record the exact `temperature` and `top_p` used per call so a re-run with the same flags produces the same sampling behavior.
3. **Identify the actual model served** — OpenRouter may return a different model string than requested (snapshot versions, fallbacks). Capture the real `response.model` so cost reports show what was actually billed.
4. **Tune sampling on demand** — expose `--temperature` and `--top-p` as CLI flags (currently hardcoded to OpenRouter's implicit defaults of 1.0/1.0).
5. **Organize execution results** — each run writes its output to a timestamped subdirectory inside the input folder's `Results/` directory, enabling easy comparison across runs.

All changes must be **backwards compatible**: existing invocations without the new flags produce identical `*_cost.txt` for the pre-existing sections (`TOKEN USAGE AND COST SUMMARY` + original `PER-MODEL BREAKDOWN` structure minus the new `actual:` sub-line) and identical significant-occurrence counts. **Note (P12 clarification):** the `PER-MODEL BREAKDOWN` section gains a new `actual:` sub-line and latency stats per model, so it is NOT byte-identical to the old output — only the header/total sections above it are.

**Non-goals (deferred from TOOLS-002):** prompt versioning, retries, error type breakdown, per-phase timing, ETA projection, histogram of latencies, cache tracking, inter-call gaps, per-category cost. These remain in `TOOLS-002-estatisticas-pdfanalyzer.md` as future work.

---

## 2. Scope

### IN

- `llm_query.py`:
  - Add 4 new fields to `CallRecord` dataclass (with defaults — backwards compat).
  - Extend `LLMAnalyzer.__init__` signature to accept `temperature` and `top_p`.
  - Extend `_complete` to: time the call, pass `temperature`/`top_p` to the SDK, capture `response.model`.
  - **NEW (v1.2, P1):** Extend `fetch_article_summary` to use a shared `_timed_create` helper so those calls also get latency, temperature, top_p, and model_version tracking.
  - Extend `_record_call` to receive and store the 4 new values as keyword-only parameters.
  - Extend `print_usage_summary` to emit 2 new sections (`LATENCY` + `SAMPLING & MODEL`) and extend `PER-MODEL BREAKDOWN` to show `model_version` and per-model latency.
  - **NEW (v1.2, P4):** Change `latency_s` default from `0.0` to `None`; filter `None` in percentile calculations.
  - **NEW (v1.2, P6):** Change `validate_sampling_for_model` runtime behavior from `raise ValueError` to `logging.warning` + auto-override to 1.0/1.0 (safe fallback, no crash in threads).
  - **NEW (v1.3, C1):** Fix 4 incorrect entries in `_fallback_pricing` table.
  - **NEW (v1.3, C6):** Fix missing-model fallback default from $0.10/$0.40 to $2.00/$8.00 with Fore.RED warning.
  - **NEW (v1.3, R8):** Emit `<pdf_stem>_summary.json` in output directory with machine-readable metrics for variance analysis.
- `main.py`:
  - Add 2 new CLI flags: `--temperature`, `--top-p`.
  - Pass them to `LLMAnalyzer()` constructor.
  - Add CLI validation after `parse_args()`.
  - **NEW (v1.3, R7):** Create `<source_folder>/Results/<timestamp>/` directory and redirect all output files there instead of `pdf_path.parent`.
  - **NEW (v1.3, R8):** Emit `<pdf_stem>_summary.json` in the Results directory with structured metrics for variance analysis.
- `full_pdf_analyzer.py`:
  - Add the same 2 CLI flags.
  - Pass them to `FullPDFAnalyzer.__init__` which threads to `LLMAnalyzer()`.
  - **NEW (v1.3, R7):** Use `<source_folder>/Results/<timestamp>/` for output instead of `output_folder`.
  - **NEW (v1.3, R8):** Emit `<pdf_stem>_summary.json` with structured metrics.
- **CHANGED (v1.2, P2):** `parallel.py`:
  - Thread `temperature` and `top_p` through `run_pipeline_parallel`, `_worker_process_entry`, and `process_single_pdf_v2`.
  - Pass them to `LLMAnalyzer()` constructor inside `process_single_pdf_v2`.
  - **NEW (v1.3, R7):** Write output files to the Results subdirectory instead of `pdf_path.parent`.
  - **NEW (v1.3, R8):** Emit `<pdf_stem>_summary.json` with structured metrics.

### OUT (DO NOT TOUCH)

- `analyze_occurrences` (main.py) — internal loop, not affected.
- `analyze_single_occurrence` (llm_query.py) — caller of `_complete`, no change needed (it just receives the result string).
- `process_category` (main.py) — dead code, untouched.
- `load_prompt`, `load_enabler_keywords`, `_load_models` — no change.
- Prompt files (`*.txt`) — no change. No versioning system introduced.
- `readme.md` — updated in E9 with a one-paragraph mention, not a full new section.

### MINIMAL TOUCH (rough estimate, updated v1.2)

- `llm_query.py`: ~70 LOC added (4 dataclass fields, 2 instance attrs, `_timed_create` helper ~10 LOC, 5-line wrap in `_complete`, 5-line wrap in `fetch_article_summary`, ~15 LOC print sections, 5-LOC PER-MODEL extension, 3-LOC LATENCY filter for None).
- `main.py`: ~12 LOC added (2 argparse entries + 1-line pass to constructor + 2-line CLI validation).
- `full_pdf_analyzer.py`: ~8 LOC added (2 argparse entries + 2-line thread to constructor + 2-line CLI validation).
- `parallel.py`: ~10 LOC added (2 params in function signatures + 1-line pass to LLMAnalyzer constructor + 2-line thread in run_pipeline_parallel).
- Total: ~100 LOC across 4 files. No new dependencies.

---

## 3. Codebase Facts (verified against real code, 2026-06-14, post-parallelization)

| Fact | Detail |
|---|---|
| **`CallRecord` is a `@dataclass` at llm_query.py:22** | Adding fields with defaults is safe — existing constructors with positional args (none external) keep working. |
| **`_complete` at llm_query.py:462** | Calls `self.client.chat.completions.create(model=model_name, messages=[...])`. **No `temperature` or `top_p` is passed today** — OpenRouter's implicit defaults (1.0/1.0) are used. |
| **`_record_call` at llm_query.py:248** | Receives `model_name, generation_id, ...` and appends to `self.call_records`. Has access to the parsed usage data; does **NOT** currently receive the response object. **Decision**: pass the 4 new values as keyword-only args from callers — preserves positional signature for existing callers. |
| **`response.model` exists in OpenAI Python SDK** | `ChatCompletion.model` is the actual model used by the server. With OpenRouter, this may differ from the requested string (e.g. request `"google/gemini-2.5-flash"`, response may be `"google/gemini-2.5-flash-preview-05-20"`). |
| **OpenRouter's `temperature` default is 1.0** | Confirmed via OpenRouter API docs. Explicitly passing `temperature=1.0` is **bit-identical** to omitting it. Same for `top_p`. |
| **OpenRouter supports `temperature` and `top_p`** | Both are passed via the OpenAI-compatible API in the standard `chat.completions.create(...)` kwargs. |
| **`print_usage_summary` at llm_query.py:332** | Writes a human-readable text file. The `full_pdf_analyzer.py`'s `generate_cost_table` and `generate_token_table` methods parse `*_cost.txt` with regex on `Total cost:` and `Total API calls:` only — new appended sections don't break these parsers. **REMOVED (v1.2, P8):** the reference to `generate_cost_summary.py` which does not exist in the codebase. |
| **CLI flags of `main.py`** (verified) | Positional: `source_folder, start_index, end_index, keywords_path`. Optional: `--model`, `--min-representative-matches`, `--debug`, `--parallel`, `--max-workers`, `--num-processes`, `--log-level`, `--profile`. New `--temperature` and `--top-p` slot in cleanly. |
| **`fetch_article_summary` at llm_query.py:545** | Calls `self.client.chat.completions.create()` directly (NOT via `_complete`) and then `self._record_call()`. **v1.2 fix (P1):** this path now uses `_timed_create` so latency/temperature/top_p/model_version are captured. |
| **Cost file path** | `<pdf_path.stem>_cost.txt` written by `llm_analyzer.print_usage_summary(str(cost_file))` at main.py:556. New sections append inside the same file. |
| **Thread-safety** | TOOLS-001's lock around `self.call_records.append(...)` is preserved. The new fields are read/written only inside the lock (the entire `_record_call` body is locked per the v2.0 design). |
| **`parallel.py` now uses `LLMAnalyzer()` at line 465** | Creates a fresh instance per PDF in `process_single_pdf_v2`. **v1.2 (P2):** must pass `temperature`/`top_p` here. |
| **`_worker_process_entry` at parallel.py:757** | Currently takes `model_name` but not `temperature`/`top_p`. **v1.2 (P2):** signature extended. |
| **`run_pipeline_parallel` at parallel.py:792** | Currently does not receive `temperature`/`top_p`. **v1.2 (P2):** signature extended. |

---

## 4. Architecture

### Data flow

```
CLI (--temperature X --top-p Y)
        │
        ▼
LLMAnalyzer.__init__(temperature=X, top_p=Y)
        │  stores self.temperature, self.top_p
        ▼
analyze_single_occurrence(prompt)
        │
        ▼
_complete(model_name, system_message, user_message)
        │
        │  ┌─ validate_sampling_for_model(model_name, ...) ──┐
        │  │  (warn + override if reasoning model, not raise) │
        │  └─────────────────────────────────────┬───────────┘
        │                                        │
        │  ┌─ t0 = time.perf_counter() ─────────┐
        │  │   response = _timed_create(...)      │
        │  │   latency_s = perf_counter() - t0   │
        │  └─────────────────────────────────────┘
        │
        ▼
_record_call(..., latency_s=latency_s, temperature=self.temperature,
             top_p=self.top_p, model_version=response.model)
        │  appends to self.call_records (under lock)
        ▼
... (N occurrences) ...

print_usage_summary(output_file)
        │  reads self.call_records
        │  aggregates:
        │    - latency_s (!= None): min/max/mean/p50/p95/p99
        │    - temperature/top_p: distribution
        │    - model_version: per-model breakdown (may be multi-valued)
        ▼
<stem>_cost.txt  (existing file, with new sections appended)
```

### CallRecord schema

```python
@dataclass
class CallRecord:
    model: str                       # requested model (existing)
    prompt_tokens: int               # (existing)
    completion_tokens: int           # (existing)
    cost_usd: float                  # (existing)
    source: str                      # (existing: openrouter/generation_endpoint/estimate)

    # NEW (all with defaults → backwards compatible):
    latency_s: float | None = None   # wall-clock seconds of the SDK call (None = not tracked)
    temperature: float | None = None # value passed to the API (None = not set)
    top_p: float | None = None       # value passed to the API (None = not set)
    model_version: str | None = None # response.model from the server
```

**v1.2 change (P4):** `latency_s` changed from `float = 0.0` to `float | None = None`. Reason: `0.0` is a valid latency value that would falsely lower min/mean. `None` cleanly represents "not tracked" and is filtered out of percentile calculations.

### LLMAnalyzer constructor

```python
def __init__(
    self,
    api_key: str | None = None,
    models_file: str = "models.txt",
    temperature: float = 1.0,        # NEW — OpenRouter's default
    top_p: float = 1.0,              # NEW — OpenRouter's default
):
    ...
    self.temperature = temperature
    self.top_p = top_p
```

### `_timed_create` helper (NEW in v1.2, fixes P1)

Both `_complete` and `fetch_article_summary` need timing + sampling params + model_version capture. A shared helper avoids code duplication:

```python
def _timed_create(
    self,
    model_name: str,
    system_message: str,
    user_message: str,
) -> tuple:
    """Send a chat completion with timing and sampling params.

    Returns (response, latency_s, model_version).
    Raises ValueError if the model is a reasoning model and
    temperature/top_p are not 1.0 (see validate_sampling_for_model).
    """
    # Runtime safety net (warn + override, NOT raise — P6)
    temp, top_p = validate_sampling_for_model(
        model_name, self.temperature, self.top_p
    )
    t0 = time.perf_counter()
    response = self.client.chat.completions.create(
        model=model_name,
        temperature=temp,
        top_p=top_p,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user",   "content": user_message},
        ],
    )
    latency_s = time.perf_counter() - t0
    model_version = getattr(response, "model", None)
    return response, latency_s, model_version
```

### `_complete` diff (illustrative, corrected P3)

```python
def _complete(self, model_name, system_message, user_message) -> str:
    """Send a chat completion, record accurate billing, and return the reply."""
    response, latency_s, model_version = self._timed_create(
        model_name, system_message, user_message
    )

    if not response.choices:
        raise RuntimeError("No response choices returned by the API.")

    prompt_tokens, completion_tokens, cost_from_response = self._extract_usage(response)

    self._record_call(
        model_name=model_name,
        generation_id=response.id,           # CORRECTED (P3): was response.usage.model_extra.get("id","")
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_from_response=cost_from_response,
        latency_s=latency_s,                # NEW
        temperature=self.temperature,        # NEW
        top_p=self.top_p,                    # NEW
        model_version=model_version,         # NEW
    )

    return response.choices[0].message.content.strip()
```

### `fetch_article_summary` diff (NEW in v1.2, fixes P1)

Only the `self.client.chat.completions.create(...)` call changes; the rest of the method stays the same:

```python
# OLD:
response = self.client.chat.completions.create(
    model=search_model,
    messages=[...],
)

# NEW (inside the for-loop):
response, latency_s, model_version = self._timed_create(
    search_model, system_message, prompt
)

# Then after cost extraction:
self._record_call(
    model_name=search_model,
    generation_id=response.id,
    prompt_tokens=prompt_tokens,
    completion_tokens=completion_tokens,
    cost_from_response=cost_from_response,
    latency_s=latency_s,
    temperature=self.temperature,
    top_p=self.top_p,
    model_version=model_version,
)
```

This ensures `fetch_article_summary` calls (1–6 per PDF) are fully tracked in latency and model version stats.

### `_record_call` signature extension

```python
def _record_call(
    self,
    model_name: str,
    generation_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_from_response: float | None,
    *,                                  # keyword-only separator (new params below)
    latency_s: float | None = None,     # NEW
    temperature: float | None = None,    # NEW
    top_p: float | None = None,          # NEW
    model_version: str | None = None,    # NEW
) -> None:
```

Using `*` ensures all existing positional callers are unaffected. The new fields are keyword-only with defaults.

### `print_usage_summary` output (new sections appended)

```
======================================================================
LATENCY (per LLM call, seconds)
----------------------------------------------------------------------
calls:    1,650
min:      0.182
max:      4.713
mean:     0.781
p50:      0.612
p95:      1.943
p99:      3.221
======================================================================
SAMPLING & MODEL
----------------------------------------------------------------------
temperature: 1.0   (used in 1,644/1,650 calls; n/a in 6 calls)
top_p:       1.0   (used in 1,644/1,650 calls; n/a in 6 calls)
======================================================================
PER-MODEL BREAKDOWN
----------------------------------------------------------------------
  google/gemini-2.5-flash
    actual: google/gemini-2.5-flash-preview-05-20 (1,640 calls)
             google/gemini-2.5-flash-preview-06-20 (4 calls)
    calls=1,644  prompt=655,645  completion=3,477  cost=$0.33825350  [openrouter]
    latency: min=0.182  max=4.713  mean=0.781  p50=0.612  p95=1.943
  openai/gpt-4.1-nano
    actual: openai/gpt-4.1-nano (6 calls)
    calls=6  prompt=12,540  completion=890  cost=$0.00152750  [openrouter]
    latency: min=0.310  max=1.022  mean=0.501  p50=0.488
======================================================================
```

**Notes:**
- The `n/a` count in SAMPLING & MODEL refers to calls where `temperature`/`top_p` is `None` (e.g., from old-style records if any exist, or from calls made before the feature was enabled). In practice, after this spec is implemented, all calls should have values — but the display handles the edge case.
- **v1.2 (P7):** `actual:` now shows all distinct `model_version` values with their call counts, not just one. If the requested model always maps to a single actual model, the output collapses to one line as before.
- Latency stats per model show only percentiles available for the data size (e.g., a model with <20 calls omits p95/p99).
- Percentiles are computed using `statistics.quantiles(data, n=100, method='inclusive')` and indexing: p50 = result[49], p95 = result[94], p99 = result[98]. For fewer than 2 data points, only min/max/mean are shown. **(v1.2, P11)**

### Sampling validation (conservative — R6 mitigation)

OpenRouter's reasoning models (OpenAI o1/o1-mini/o1-preview/o3/o3-mini, GPT-5 family, DeepSeek r1, Claude `*-thinking`) reject `temperature != 1.0` or `top_p != 1.0` with HTTP 400. A user invoking the tool with `--temperature 0.0 --model openai/o1` would burn the API key on 1644 failed calls.

**v1.2 change (P5 + P6):** Two enforcement points with different behavior:

1. **CLI parse time** (in `main.py` and `full_pdf_analyzer.py`): if `args.model != "random"` and the model matches a reasoning pattern, call `validate_sampling_for_model(args.model, args.temperature, args.top_p)`. On `ValueError`, print the message in red and exit with code 2. **This is a hard rejection — no API call is made.**

2. **Runtime safety net** (in `_timed_create`): after `model_name` is selected (whether via `--model` or `get_random_model()`), call `validate_sampling_for_model(model_name, self.temperature, self.top_p)`. **Changed (P6):** instead of `raise ValueError`, this now:
   - Logs a `warning` with the model name and the conflicting values.
   - Returns `(1.0, 1.0)` as the effective values for this call (safe fallback).
   - This prevents crashes in thread pools (`--parallel`) and in `--model random` where a reasoning model might be selected mid-run.

The helper in `llm_query.py`:

```python
REASONING_MODEL_PATTERNS: tuple[str, ...] = (
    "openai/o1", "openai/o3", "openai/gpt-5", "deepseek/r1", ":thinking",
)

def is_reasoning_model(model: str) -> bool:
    """Check if a model string is a reasoning model.

    v1.2 (P5): uses prefix-based matching instead of substring to reduce
    false positives.  Patterns match at the provider/model boundary
    (e.g., "openai/o1" matches "openai/o1-mini" but NOT "llama-o1").
    The ":thinking" suffix catches Anthropic thinking variants.
    """
    m = model.lower()
    return any(m.startswith(p) or p in m for p in REASONING_MODEL_PATTERNS)

def validate_sampling_for_model(
    model: str, temperature: float, top_p: float,
    *,
    strict: bool = True,
) -> tuple[float, float]:
    """Validate sampling params for reasoning models.

    Args:
        strict: If True (default, CLI path), raises ValueError on mismatch.
                If False (runtime path), logs warning and returns (1.0, 1.0).

    Returns the (validated/effective) sampling params.
    """
    if is_reasoning_model(model) and (temperature != 1.0 or top_p != 1.0):
        msg = (
            f"Model '{model}' is a reasoning model and only supports "
            f"temperature=1.0 and top_p=1.0. "
            f"Got temperature={temperature}, top_p={top_p}."
        )
        if strict:
            raise ValueError(msg)
        else:
            logging.warning(msg + " Overriding to 1.0/1.0 for this call.")
            return 1.0, 1.0
    return temperature, top_p
```

**v1.2 note (P5):** `REASONING_MODEL_PATTERNS` changed from generic substrings (`"o1"`, `"thinking"`) to provider-qualified prefixes (`"openai/o1"`, `"openai/o3"`, `"openai/gpt-5"`, `"deepseek/r1"`, `":thinking"`). This reduces false positives (e.g., a hypothetical `"llama-o1"` would not match). The `":thinking"` pattern catches Anthropic models like `"anthropic/claude-3.7-sonnet:thinking"`. **Residual risk:** a new reasoning model not in the list will not be caught. Document as known limitation.

### CLI flags

`main.py` argparse additions (full_pdf_analyzer.py mirrors):

```python
parser.add_argument(
    "--temperature",
    type=float,
    default=1.0,
    help="LLM sampling temperature. Default 1.0 (OpenRouter default). "
         "Lower values (e.g. 0.0) make output more deterministic.",
)
parser.add_argument(
    "--top-p",
    type=float,
    default=1.0,
    help="LLM nucleus sampling top-p. Default 1.0 (OpenRouter default). "
         "Lower values restrict the token pool.",
)
```

Then in `process_single_pdf`:

```python
llm_analyzer = LLMAnalyzer(
    temperature=args.temperature,
    top_p=args.top_p,
)
```

### `parallel.py` integration (NEW in v1.2, fixes P2)

Three functions need signature changes:

```python
# run_pipeline_parallel — add 2 params:
def run_pipeline_parallel(
    files, keywords_path, max_workers=5, num_processes=2,
    min_representative_matches=1, model_name="random",
    log_level="normal", profile=False,
    temperature=1.0,    # NEW
    top_p=1.0,          # NEW
) -> None:

# _worker_process_entry — add 2 params:
def _worker_process_entry(
    pdf_path, keywords_path, max_workers,
    min_representative_matches, model_name, log_level,
    temperature=1.0,    # NEW
    top_p=1.0,          # NEW
) -> str:

# process_single_pdf_v2 — add 2 params, thread to LLMAnalyzer:
def process_single_pdf_v2(
    file_path, keywords_path, max_workers=5,
    min_representative_matches=1, model_name="random",
    log_level="normal",
    temperature=1.0,    # NEW
    top_p=1.0,          # NEW
) -> None:
    ...
    llm_analyzer = LLMAnalyzer(temperature=temperature, top_p=top_p)
```

And in `main.py`'s routing block:

```python
if args.parallel:
    from parallel import run_pipeline_parallel
    run_pipeline_parallel(
        files=files_to_process,
        keywords_path=keywords_path,
        max_workers=args.max_workers,
        num_processes=args.num_processes,
        min_representative_matches=args.min_representative_matches,
        model_name=args.model,
        log_level=args.log_level,
        profile=args.profile,
        temperature=args.temperature,    # NEW
        top_p=args.top_p,                # NEW
    )
```

### `full_pdf_analyzer.py` integration (clarified v1.2, fixes P10)

```python
# FullPDFAnalyzer.__init__ — add 2 params:
class FullPDFAnalyzer:
    def __init__(self, source_folder, keywords_path, output_folder,
                 temperature=1.0, top_p=1.0):   # NEW
        ...
        self.llm_analyzer = LLMAnalyzer(temperature=temperature, top_p=top_p)

# CLI — add 2 flags:
parser.add_argument("--temperature", type=float, default=1.0, ...)
parser.add_argument("--top-p", type=float, default=1.0, ...)

# After parse_args:
analyzer = FullPDFAnalyzer(
    args.source, args.keywords, args.output,
    temperature=args.temperature, top_p=args.top_p,
)

# CLI validation (same as main.py):
if args.model != "random":  # Note: full_pdf_analyzer currently hardcodes model
    validate_sampling_for_model(args.model, args.temperature, args.top_p)
```

### Results directory with timestamped runs (NEW in v1.3, R7)

Currently, all output files are written to `pdf_path.parent` (the same folder as the input PDF). This clutters the input directory and overwrites previous runs. The new structure serves the reproducibility requirement: repeated trials on the same PDF set generate independent result directories, enabling variance analysis across runs.

```
<source_folder>/
  ├── NIST.SP.800-207.pdf
  ├── cloud.json
  └── Results/
      ├── 2026-06-15_14-32-01/
      │   ├── NIST.SP.800-207_significant_paragraphs_category_1.txt
      │   ├── NIST.SP.800-207_cost.txt
      │   ├── NIST.SP.800-207_all_category_results.txt
      │   ├── NIST.SP.800-207_all_category_notes.txt
      │   ├── NIST.SP.800-207_article_summary.txt
      │   ├── NIST.SP.800-207_occurrences.txt
      │   └── NIST.SP.800-207_summary.json    ← machine-readable metrics
      ├── 2026-06-15_16-05-33/
      │   ├── NIST.SP.800-207_summary.json
      │   └── ...
      └── _batch_2026-06-15_18-00/             ← batch runner output
          ├── run_001/
          │   └── NIST.SP.800-207_summary.json
          ├── run_002/
          │   └── NIST.SP.800-207_summary.json
          └── variance_report.json             ← cross-run statistics
```

**Implementation:**

```python
from datetime import datetime

# In main.py's main(), BEFORE the PDF processing loop:
results_base = Path(args.source_folder) / "Results"
run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
run_dir = results_base / run_timestamp
run_dir.mkdir(parents=True, exist_ok=True)
print(Fore.GREEN + f"Results will be saved to: {run_dir}" + Style.RESET_ALL)

# Then pass run_dir to process_single_pdf instead of using pdf_path.parent:
def process_single_pdf(pdf_path, keywords_file_path, ..., output_dir: Path):
    # Replace all `pdf_path.parent / f"{pdf_path.stem}_*.txt"` with:
    #   output_dir / f"{pdf_path.stem}_*.txt"
    cost_file = output_dir / f"{pdf_path.stem}_cost.txt"
    summary_file = output_dir / f"{pdf_path.stem}_article_summary.txt"
    # etc.
```

**For `parallel.py`:** `run_pipeline_parallel` receives `run_dir` (or creates it) and passes it through to `_worker_process_entry` and `process_single_pdf_v2`. All `pdf_path.parent /` references become `output_dir /`.

**For `full_pdf_analyzer.py`:** `FullPDFAnalyzer.__init__` creates the timestamped directory under `self.source_folder / "Results"`. All output goes there instead of `self.output_folder`.

**Key decisions:**
- Timestamp format: `YYYY-MM-DD_HH-MM-SS` (sortable, filesystem-safe, no colons).
- The `Results/` directory is created on the first run; it is never auto-cleaned.
- If two runs start in the same second, the second `mkdir` succeeds silently (no collision because `exist_ok=True`). If sub-second uniqueness is needed in the future, append `_{uuid4()[:8]}`.
- The input PDFs are NOT copied to the Results directory — only output files go there.
- `pdf_path.parent` is still available for reading the PDF; only the write location changes.

### Per-run summary JSON (NEW in v1.3, R8)

To enable automated variance analysis across repeated trials, each run also emits a machine-readable `<pdf_stem>_summary.json` alongside the human-readable text files. This avoids fragile regex parsing of `*_cost.txt` and gives the future batch runner a clean data format.

**Schema:**

```json
{
  "run_id": "2026-06-15_14-32-01",
  "pdf_file": "NIST.SP.800-207.pdf",
  "model_requested": "google/gemini-2.5-flash",
  "temperature": 1.0,
  "top_p": 1.0,
  "total_api_calls": 1644,
  "total_prompt_tokens": 655645,
  "total_completion_tokens": 3477,
  "total_cost_usd": 0.33825350,
  "cost_source": "openrouter",
  "latency": {
    "count": 1644,
    "min_s": 0.182,
    "max_s": 4.713,
    "mean_s": 0.781,
    "p50_s": 0.612,
    "p95_s": 1.943,
    "p99_s": 3.221
  },
  "significant_paragraphs_count": 42,
  "categories_found": 5,
  "category_results": {
    "Cloud Computing": {
      "occurrences_found": 12,
      "significant_paragraphs": 8,
      "model_versions_used": ["google/gemini-2.5-flash-preview-05-20"]
    }
  },
  "model_versions": {
    "google/gemini-2.5-flash-preview-05-20": 1640,
    "google/gemini-2.5-flash-preview-06-20": 4
  }
}
```

**Implementation:** In `process_single_pdf` (and `process_single_pdf_v2`), after `print_usage_summary`, collect the same data already computed for the text sections and dump it as JSON:

```python
import json

summary = {
    "run_id": run_dir.name,
    "pdf_file": pdf_path.name,
    "model_requested": effective_model,
    "temperature": llm_analyzer.temperature,
    "top_p": llm_analyzer.top_p,
    # ... aggregate from llm_analyzer.call_records ...
}
summary_file = output_dir / f"{pdf_path.stem}_summary.json"
summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
```

This is a **read-only addition** — no existing code path is changed. The JSON mirrors what the text sections already show, just in structured form.

### Batch runner for repeated trials (NEW in v1.3, R9 — future script)

A separate script `run_trials.py` (NOT part of this spec's etapas, but documented here so the design supports it) will:

1. Accept the same CLI arguments as `main.py`, plus `--trials N` (default 30).
2. Call `process_single_pdf` N times for each PDF, each time with a fresh timestamped `Results/_batch_<timestamp>/run_XXX/` directory.
3. After all trials, read every `*_summary.json` and compute:
   - Per-metric mean, std dev, CV (coefficient of variation)
   - Stability: count of unique `significant_paragraphs_count` values / N
   - Category-level Jaccard similarity of found paragraphs across trials
4. Write `variance_report.json` in the batch directory.

This script is **out of scope** for this spec's etapas, but the `_summary.json` output (R8) is designed specifically to make it trivial to implement. The spec's etapas include R8 so the data foundation is ready.

**Reproducibility argument structure (for the paper):**

```
1. Run N=30 trials on the same PDF corpus (temperature=1.0 → stochastic)
   → variance_report.json shows CV of cost, latency, paragraph counts

2. Run N=30 trials with temperature=0.0 (deterministic)
   → variance_report.json shows CV ≈ 0 for paragraph counts (content reproducible)
   → but CV > 0 for latency (server-side variance only)

3. Compare 1 vs 2 → quantifies how much variance is due to LLM sampling
   vs. infrastructure variance → addresses the reviewer's critique directly
```

---

## 5. Implementation order (incremental, "test 1 by 1")

Mirrors the TOOLS-001 pattern. Each step ends with a focused test the user can verify before approving the next.

- [ ] **E1 — CallRecord fields**: add 4 new fields with defaults to the dataclass (`latency_s: float | None = None`, `temperature: float | None = None`, `top_p: float | None = None`, `model_version: str | None = None`). No other code changes. **Test:** import the module and instantiate `CallRecord(model=..., prompt_tokens=1, ...)` — old call style still works.
- [ ] **E2 — LLMAnalyzer constructor**: add `temperature` and `top_p` params with defaults 1.0; store as instance attrs. **Test:** instantiate `LLMAnalyzer()` and `LLMAnalyzer(temperature=0.5, top_p=0.9)`; assert `self.temperature` / `self.top_p` correct.
- [ ] **E3 — Sampling validation helper**: add `REASONING_MODEL_PATTERNS`, `is_reasoning_model()`, `validate_sampling_for_model()` to `llm_query.py` (module-level, no class). **Test:** `validate_sampling_for_model("openai/o1", 1.0, 1.0)` returns (1.0, 1.0); `validate_sampling_for_model("openai/o1", 0.5, 1.0, strict=True)` raises ValueError; `validate_sampling_for_model("openai/o1", 0.5, 1.0, strict=False)` returns (1.0, 1.0) and logs warning; `validate_sampling_for_model("google/gemini-2.5-flash", 0.5, 0.9)` returns (0.5, 0.9); `is_reasoning_model("anthropic/claude-3.7-sonnet:thinking")` returns True; `is_reasoning_model("meta-llama/llama-o1")` returns False (P5 check).
- [ ] **E4 — `_timed_create` helper + `_complete` rewrite + pricing fixes (C1, C6)**: implement `_timed_create` in `llm_query.py`. Rewrite `_complete` to call it. Also fix `_fallback_pricing` table (C1): update 4 entries — `google/gemini-2.5-flash` → $0.30/$2.50, `google/gemini-3-flash-preview` → $0.50/$3.00, `openai/gpt-5-mini` → $0.25/$2.00, `anthropic/claude-3.5-sonnet` → $3.00/$15.00. Also fix missing-model default (C6): change from $0.10/$0.40 to $2.00/$8.00 with Fore.RED warning. **Test (integration):** run a single LLM call with default model — assert `call_records[-1].latency_s > 0`, `.temperature == 1.0`, `.top_p == 1.0`, `.model_version` is a non-empty string. Unit test: `_estimate_cost("google/gemini-2.5-flash", 1000, 500)` should return `(1000/1M)*0.30 + (500/1M)*2.50 = $0.00155` (not the old $0.00045).
- [ ] **E5 — `fetch_article_summary` update (fixes C2)**: replace the direct `self.client.chat.completions.create(...)` call with `self._timed_create(...)`, **and move `_record_call` BEFORE content-quality checks** so that failed-but-billed calls are still recorded (C2). Pass new values to `_record_call`. **Test (integration):** run a PDF that triggers article summary fetch — assert those `call_records` have `latency_s > 0` and `model_version is not None`. **Test (C2):** verify that when a summary model returns `SUMMARY_NOT_FOUND` or matches `_NOT_FOUND_PATTERNS`, a `CallRecord` is still appended with the correct token count and cost (tokens consumed, cost recorded even though content is discarded).
- [ ] **E6 — `print_usage_summary` extensions**: add the 2 new sections + extend PER-MODEL (with multi-valued `actual:` and per-model latency). Filter `None` latencies in percentile calculation. **Test:** run E4/E5 and inspect the `*_cost.txt` — all original lines present + new sections present + parseable.
- [ ] **E7 — CLI flags in main.py**: add `--temperature` and `--top-p`, thread to `LLMAnalyzer()`. **Test:** `python main.py --help` shows the new flags; running without them behaves identically to E6.
- [ ] **E8 — CLI validation in main.py**: after `parse_args()`, if `args.model != "random"`, call `validate_sampling_for_model(args.model, args.temperature, args.top_p, strict=True)`. On ValueError, print red and `sys.exit(2)`. **Test:** `python main.py /tmp/ 0 0 cloud.json --model openai/o1 --temperature 0.0` exits with code 2 and a clear message; same with `--model openai/o1` and default 1.0/1.0 passes validation.
- [ ] **E9 — CLI flags + validation in full_pdf_analyzer.py**: add `--temperature`/`--top-p`, thread to `FullPDFAnalyzer.__init__`, add CLI validation. **Test:** same as E8 for the full-text script.
- [ ] **E10 — Parallel path integration**: add `temperature`/`top_p` to `run_pipeline_parallel`, `_worker_process_entry`, `process_single_pdf_v2` in `parallel.py`. Thread from `main.py` routing block. **Test:** `python main.py /tmp/ 0 0 cloud.json --parallel --temperature 0.5` — verify `*_cost.txt` shows `temperature: 0.5`.
- [ ] **E11 — Smoke test 1 PDF (NIST.SP.800-207)**: run E7 + E8 + E9 + E10 in sequence (sequential mode, no `--parallel`). Acceptance:
  - Significant occurrences **identical** to the per-PDF baseline (call count and content match).
  - New `*_cost.txt` contains the 2 new sections + extended PER-MODEL.
  - `model_version` in PER-MODEL is non-empty and matches the expected OpenRouter snapshot string.
  - All `latency_s` values are `> 0` (no `None` in fresh runs).
- [ ] **E12 — Determinism check (optional)**: run the same PDF with `--temperature 0.0 --top-p 1.0` and confirm: same cost, same call count, but `latency_s` distribution may differ (deterministic models sometimes take longer or shorter — only checked as informational, not a pass/fail).
- [ ] **E13 — Reasoning-model rejection check**: run `python main.py /tmp/ 0 0 cloud.json --model openai/o1 --temperature 0.5` and confirm: exits with code 2 BEFORE any API call (no `*_cost.txt` produced). Then run with `--model openai/o1` and default 1.0/1.0 — should proceed (whether or not it succeeds depends on key/model availability, but no validation error). Also test the runtime path: `--model random` with a `models.txt` containing only reasoning models + `--temperature 0.5` — confirm the run proceeds with `temperature: 1.0` in the cost file (override, not crash).
- [ ] **E14 — Results directory (R7)**: redirect all output file writes from `pdf_path.parent` to `<source_folder>/Results/<timestamp>/`. Modify `main.py` (add `output_dir` param to `process_single_pdf`), `parallel.py` (add `output_dir` param to `process_single_pdf_v2`, `_worker_process_entry`, `run_pipeline_parallel`), and `full_pdf_analyzer.py` (use timestamped dir instead of `output_folder`). **Test:** run a single PDF in sequential mode — verify all output files (`*_cost.txt`, `*_significant_paragraphs_*.txt`, `*_all_category_results.txt`, `*_all_category_notes.txt`, `*_article_summary.txt`, `*_occurrences.txt`) are inside `<source_folder>/Results/<timestamp>/` and NOT in the PDF's parent directory. Run again — verify a NEW timestamped directory is created (no overwrite of previous run).
- [ ] **E15 — Per-run summary JSON (R8)**: after `print_usage_summary`, emit `<pdf_stem>_summary.json` in the same output directory with the schema defined in §4 (R8). This is a read-only addition — no existing code path changes. **Test:** run a single PDF — verify `*_summary.json` exists, is valid JSON, and contains `run_id`, `pdf_file`, `model_requested`, `temperature`, `total_api_calls`, `total_cost_usd`, `latency`, `significant_paragraphs_count`, `category_results`, `model_versions`. All numeric values must match the corresponding `*_cost.txt` sections.
- [ ] **E16 — Skill + readme + commit**: append a one-paragraph "Statistics enhancements" section to `readme.md` and update the `pdfanalyzer` skill. Conventional commit `feat(stats): track latency, sampling params, model version, cost fixes, results dir, summary JSON (v1.3)`.

---

## 6. Acceptance criteria

| # | Criterion | How verified |
|---|-----------|--------------|
| A1 | `python main.py --help` shows `--temperature` and `--top-p` | Manual `--help` |
| A2 | Running without the new flags produces a `*_cost.txt` where the header sections (`TOKEN USAGE AND COST SUMMARY` through `Total cost:`) are identical to baseline | `diff <baseline_header> <new_header>` |
| A3 | `*_cost.txt` ends with the new `LATENCY` and `SAMPLING & MODEL` sections | `tail` |
| A4 | `PER-MODEL BREAKDOWN` shows `actual: <response.model>` for each model, with call counts when multiple actual versions exist | grep `actual:` |
| A5 | Smoke test on `NIST.SP.800-207.pdf` (cloud.json, sequential, no `--parallel`): call count identical to baseline, cost within +/-5%, significant paragraphs identical to baseline. **Note:** baseline from article-private repo if available; otherwise compare against a fresh sequential run of the current code. | `diff` on significant paragraphs, numeric check on cost/calls |
| A6 | `--temperature 0.0 --top-p 1.0` produces the same number of calls and within +/-5% cost (content of significant paragraphs may differ — that's expected with T=0) | Smoke run with the flag, count + cost check |
| A7 | No new files (everything inside the existing `*_cost.txt`) | `ls` |
| A8 | No new dependencies in `requirements.txt` | `git diff requirements.txt` should be empty |
| A9 | `python main.py /tmp/ 0 0 cloud.json --model openai/o1 --temperature 0.5` exits with code 2, no `*_cost.txt` produced, error message mentions "reasoning model" | Run + check `$?` + `ls /tmp/*cost*` |
| A10 | `python main.py /tmp/ 0 0 cloud.json --model openai/o1` (defaults 1.0/1.0) passes validation and reaches the API call phase | Run + check no ValueError from `validate_sampling_for_model` |
| A11 | `validate_sampling_for_model("anthropic/claude-3.7-sonnet:thinking", 0.0, 1.0, strict=True)` raises ValueError (covers the `:thinking` pattern) | Inline Python check |
| A12 | **NEW (v1.2, P4):** All `latency_s` values in fresh runs are `> 0` (no `None` or `0.0` in a clean run) | Check call_records after E4 |
| A13 | **NEW (v1.2, P1):** `fetch_article_summary` calls have non-None `latency_s` and `model_version` in call_records | Check records after a run that fetches article summaries |
| A14 | **NEW (v1.2, P2):** `--parallel --temperature 0.5` produces `temperature: 0.5` in the cost file | Run with `--parallel` + check `*_cost.txt` |
|| A15 | **NEW (v1.2, P6):** Runtime reasoning-model conflict (`--model random` picks reasoning model + `--temperature 0.5`) logs warning and proceeds with `temperature: 1.0` — no crash, no exit(2) | Configure models.txt with reasoning model, run with `--temperature 0.5`, verify cost file shows 1.0 ||
|| A16 | **NEW (v1.3, C1):** `_estimate_cost("google/gemini-2.5-flash", 1_000_000, 1_000_000)` returns $2.80 (= $0.30 + $2.50), not the old $0.75 (= $0.15 + $0.60) | Inline Python check after E4 ||
|| A17 | **NEW (v1.3, C2):** When `fetch_article_summary` gets `SUMMARY_NOT_FOUND` from a model, a `CallRecord` is still appended (tokens and cost recorded) | Check `call_records` after a run that gets `SUMMARY_NOT_FOUND` ||
|| A18 | **NEW (v1.3, C6):** `_estimate_cost("unknown/model-xyz", 1_000_000, 1_000_000)` returns $10.00 (= $2.00 + $8.00), not the old $0.50 (= $0.10 + $0.40), and a Fore.RED warning is emitted | Inline Python check after E4 ||
|| A19 | **NEW (v1.3, R7):** After a run, all output files (`*_cost.txt`, `*_significant_paragraphs_*.txt`, `*_all_category_results.txt`, etc.) are inside `<source_folder>/Results/<timestamp>/` — none remain in the PDF's parent directory | `ls <source_folder>/Results/*/` + verify no `*cost*` files in PDF parent ||
|| A20 | **NEW (v1.3, R7):** Running twice creates two distinct timestamped directories — previous results are not overwritten | Run twice + `ls Results/` shows 2 dirs ||
|| A21 | **NEW (v1.3, R7):** `--parallel` mode also writes to the Results timestamped directory (not `pdf_path.parent`) | Run with `--parallel` + verify output location ||
|| A22 | **NEW (v1.3, R8):** `*_summary.json` is valid JSON with all required fields (`run_id`, `pdf_file`, `model_requested`, `temperature`, `total_api_calls`, `total_cost_usd`, `latency`, `significant_paragraphs_count`, `category_results`, `model_versions`) | `python -c "import json; d=json.load(open(f)); assert all(k in d for k in [...])"` after E15 ||
|| A23 | **NEW (v1.3, R8):** Numeric values in `*_summary.json` match the corresponding `*_cost.txt` sections (total_api_calls, total_cost_usd, latency stats) | Compare JSON values vs text file parsing after E15 ||
|| A24 | **NEW (v1.3, R9 future):** The `*_summary.json` schema is stable enough that a future `run_trials.py` script can read N such files and compute variance without modification | Verify schema has no ad-hoc formatting, only structured data types ||

---

## 7. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Changing `temperature` from "implicit default" to "explicit 1.0" might shift OpenRouter's behavior | Low | OpenRouter docs state the default is exactly 1.0 for both. Smoke test A5 will catch any drift. |
| `response.model` may be `None` for some error responses or for non-OpenAI-compatible providers | Low | `model_version` defaults to `None` and the print section handles it (shows "n/a"). |
| Adding 4 fields to `CallRecord` breaks any external code that constructs it positionally | Low | No external constructors found via grep. All CallRecord constructions are inside `_record_call` itself. |
| `time.perf_counter()` overhead per call is significant | Negligible | ~100ns; the SDK call takes >=180ms. |
| New print sections break `full_pdf_analyzer.py` regex parsers | Low | Those scripts only match `Total cost:`, `Total API calls:`, `Prompt tokens:`, `Completion tokens:` — all unchanged. **REMOVED (P8):** reference to nonexistent `generate_cost_summary.py`. |
| Different OpenRouter models may reject `temperature` or `top_p` (e.g. o1 reasoning models only accept `temperature=1.0`) | Medium (mitigated) | **Mitigation (v1.2, P5+P6):** CLI: hard reject with `sys.exit(2)`. Runtime: warn + override to 1.0/1.0 (no crash in threads). `REASONING_MODEL_PATTERNS` uses provider-qualified prefixes to reduce false positives. **Residual risk:** new reasoning models not in the list will not be caught — document as known limitation. |
|| `fetch_article_summary` bypasses `_complete` and misses stats (P1) | High → FIXED in v1.2 | New `_timed_create` helper used by both `_complete` and `fetch_article_summary`. |
|| `fetch_article_summary` skips cost recording for non-exception failures (C2) | Medium → FIXED in v1.3 | `_record_call` moved BEFORE content-quality checks in E5. |
|| `parallel.py` in OUT but must be touched for temperature/top_p (P2) | High → FIXED in v1.2 | `parallel.py` moved to IN; 3 function signatures extended. |
|| `_fallback_pricing` has 4 incorrect entries (C1) | High → FIXED in v1.3 | Pricing table corrected in E4. Worst case: `gemini-2.5-flash` completion was 4.2x underpriced. |
|| Missing-model fallback default too low (C6) | Medium → FIXED in v1.3 | Default changed from $0.10/$0.40 to $2.00/$8.00 in E4; Fore.RED warning added. |
|| Output files overwritten on repeated runs (R7) | High → FIXED in v1.3 | Timestamped `Results/YYYY-MM-DD_HH-MM-SS/` directory per run; previous runs preserved. |
|| No machine-readable metrics for automated variance analysis (R8) | Medium → FIXED in v1.3 | Per-run `_summary.json` emitted alongside text files; enables future `run_trials.py` without parsing. |
|| Reviewer critique: "no repeated trials, no variance analysis" (R9) | High → ADDRESSED in v1.3 | R7 + R8 provide the data foundation; `run_trials.py` script (future) will automate N runs and compute CV. The spec documents the reproducibility argument structure for the paper. |
| `latency_s=0.0` conflates "not tracked" with "zero latency" (P4) | Medium → FIXED in v1.2 | Default changed to `None`; filtered in percentile calculations. |
| `is_reasoning_model` false positives from substring match (P5) | Medium → FIXED in v1.2 | Uses provider-qualified prefix matching (`"openai/o1"`, not `"o1"`). |
| `validate_sampling_for_model` raises ValueError in thread (P6) | Medium → FIXED in v1.2 | Runtime path uses `strict=False` → warn + override instead of raise. |
| `model_version` per model can be multi-valued (P7) | Low → HANDLED in v1.2 | `actual:` shows all distinct values with call counts. |
| `generation_id` diff showed wrong source (P3) | Low → FIXED in v1.2 | Corrected to `response.id`. |
| Line numbers in §9 became stale after parallelization (P9) | Low → FIXED in v1.2 | Re-verified. |

---

## 8. Open questions

None. The user's decisions on 2026-06-11 closed the open items:

- ~~Temperature/top_p default value~~ → **1.0/1.0** (= current OpenRouter default; explicit, not implicit).
- ~~Prompt versioning~~ → **deferred**. Prompts are stable; no version system needed.
- ~~Separate `*_stats.json` file vs extend `*_cost.txt`~~ → **extend `*_cost.txt`**. JSON would be additive work; not asked.
- ~~Spec-first vs code-first~~ → **spec-first**. This document is the spec.
- ~~(v1.2) `is_reasoning_model` pattern matching~~ → **provider-qualified prefixes** (P5 fix). Accept residual risk of new models not in the list.
- ~~(v1.2) Runtime validation behavior~~ → **warn + override** instead of raise (P6 fix). Prevents thread crashes.

---

## 9. Reference: code line numbers (re-verified 2026-06-14, post-parallelization)

|| Item | Location |
||---|---|
|| `CallRecord` | `llm_query.py:22-29` |
|| `LLMAnalyzer.__init__` | `llm_query.py:54-122` |
|| `_fallback_pricing` table | `llm_query.py:94-122` |
|| `_record_call` | `llm_query.py:248-311` |
|| `print_usage_summary` | `llm_query.py:332-396` |
|| `load_prompt` | `llm_query.py:453-456` |
|| `_complete` | `llm_query.py:462-490` |
|| `analyze_single_occurrence` | `llm_query.py:517-529` |
|| `analyze` | `llm_query.py:496-515` |
|| `fetch_article_summary` | `llm_query.py:545-631` |
|| `LLMAnalyzer()` in main.py (sequential) | `main.py:393` |
|| `LLMAnalyzer()` in parallel.py | `parallel.py:465` |
|| `cost_file` write | `main.py:556-557` |
|| main.py argparse | `main.py:571-636` |
|| main.py parallel routing | `main.py:720-732` |
|| `process_single_pdf_v2` | `parallel.py:374-723` |
|| `_worker_process_entry` | `parallel.py:757-789` |
|| `run_pipeline_parallel` | `parallel.py:792-925` |
|| `FullPDFAnalyzer.__init__` | `full_pdf_analyzer.py:17-23` |
|| `FullPDFAnalyzer.analyze_category` | `full_pdf_analyzer.py:39-68` |
|| `FullPDFAnalyzer.run` | `full_pdf_analyzer.py:235-267` |
|| full_pdf_analyzer.py argparse | `full_pdf_analyzer.py:270-278` |

---

## 10. Cost Calculation Correctness Audit (NEW in v1.3, 2026-06-15)

This section documents issues found in the cost calculation logic during a systematic audit. Issues are labeled C1–C6. Fixes for C1 and C2 are integrated into etapas E4 and E5 below.

### Cost priority path (current)

```
1. cost_from_response  (response.usage.model_extra['cost'] — primary, always present on OpenRouter)
2. _fetch_generation_stats  (HTTP GET to OpenRouter generation endpoint — secondary)
3. _estimate_cost  (local pricing table — last resort)
```

### C1 — Fallback pricing table has 4 incorrect entries [HIGH]

**Impact:** The fallback table is only used when both the primary path and generation endpoint fail. In practice, OpenRouter almost always returns cost in the response (path 1), so these errors only affect the rare fallback scenario. However, when they DO fire, the errors are large and the default model is the worst-affected one.

| Model | Field | Code value | Actual (OpenRouter, Jun 2026) | Error |
|---|---|---|---|---|
| `google/gemini-2.5-flash` | prompt | $0.15 | **$0.30** | 2x underpriced |
| `google/gemini-2.5-flash` | completion | $0.60 | **$2.50** | 4.2x underpriced |
| `google/gemini-3-flash-preview` | prompt | $0.10 | **$0.50** | 5x underpriced |
| `google/gemini-3-flash-preview` | completion | $0.50 | **$3.00** | 6x underpriced |
| `openai/gpt-5-mini` | prompt | $0.05 | **$0.25** | 5x underpriced |
| `openai/gpt-5-mini` | completion | $0.40 | **$2.00** | 5x underpriced |
| `anthropic/claude-3.5-sonnet` | prompt | $6.00 | **$3.00** | 2x overpriced |
| `anthropic/claude-3.5-sonnet` | completion | $30.00 | **$15.00** | 2x overpriced |

**Note on `openai/gpt-5-mini`:** The current code has the same pricing as `gpt-5-nano` ($0.05/$0.40). This is clearly a copy-paste error — `gpt-5-mini` is a different tier at $0.25/$2.00.

**Sources:** OpenRouter model pages, llmreference.com, bifrost (getmaxim.ai), tldl.io — all cross-verified June 2026.

**Fix:** Update `_fallback_pricing` in `llm_query.py` (llm_query.py:101, 103, 113, 121). Integrated into E4.

### C2 — `fetch_article_summary` skips cost recording for non-exception failures [MEDIUM]

**Location:** `llm_query.py:584-600`

When `fetch_article_summary` gets a response but the content is unusable, it `continue`s without calling `_record_call`. This means tokens consumed by the API are paid for but not recorded in the cost report.

```python
# Lines 584-600: these paths skip _record_call even though tokens were consumed:
if not response.choices:            # Empty choices → tokens consumed, cost NOT recorded
    continue
if llm_response == "SUMMARY_NOT_FOUND":  # API consumed tokens, cost NOT recorded
    continue
if any(p in llm_response.lower() for p in _NOT_FOUND_PATTERNS):  # same
    continue
if not llm_response:               # Empty string, tokens consumed, cost NOT recorded
    continue
# Only reached if response is usable:
self._record_call(...)              # ← cost recorded here
```

**Impact:** For 1–6 article summary calls per PDF, failed-but-billed calls are invisible in the cost report. The actual spend is higher than reported.

**Fix:** Extract usage and call `_record_call` BEFORE the content-validation `continue`s. In the v1.2 `_timed_create` rewrite (E5), this is restructured as:

```python
# Inside fetch_article_summary, after _timed_create:
response, latency_s, model_version = self._timed_create(
    search_model, system_message, prompt
)

# Extract cost FIRST (regardless of content quality):
prompt_tokens, completion_tokens, cost_from_response = self._extract_usage(response)
self._record_call(
    model_name=search_model,
    generation_id=response.id,
    prompt_tokens=prompt_tokens,
    completion_tokens=completion_tokens,
    cost_from_response=cost_from_response,
    latency_s=latency_s,
    temperature=self.temperature,
    top_p=self.top_p,
    model_version=model_version,
)

# THEN check content quality:
if not response.choices:
    print(Fore.YELLOW + f"No response choices from {search_model}" + Style.RESET_ALL)
    continue
llm_response = response.choices[0].message.content.strip()
if llm_response == "SUMMARY_NOT_FOUND":
    # ... continue  (cost already recorded above)
```

This ensures every API call that returns a response object (with or without usable content) has its cost tracked. Integrated into E5.

### C3 — `_estimate_cost` uses requested model, not actual model [LOW]

**Location:** `llm_query.py:223-242`

When the fallback pricing table is used, `_estimate_cost(model_name, ...)` receives the *requested* model name, not the *actual* model (`response.model`). OpenRouter may serve a different model snapshot (e.g., request `google/gemini-2.5-flash`, get `google/gemini-2.5-flash-preview-05-20`). The pricing difference between snapshots is usually negligible, but could matter if a model is rerouted to a different tier entirely.

**Impact:** LOW — this only affects the last-resort fallback path, and pricing differences within the same model family are typically small.

**Fix (not in etapas — documented as known limitation):** After the v1.2 spec is implemented, `_record_call` will have `model_version` available. A future enhancement could pass `model_version` to `_estimate_cost` instead of `model_name`. For now, document as a known limitation.

### C4 — `_estimate_cost` substring matching may match wrong model [LOW]

**Location:** `llm_query.py:229-232`

The current matching logic `if key in model_lower` uses Python dict iteration order (insertion order in 3.7+). If a model name is a substring of another, the first match wins. For example, `"openai/gpt-4.1"` would match before `"openai/gpt-4.1-mini"` only because it appears first in the dict. This is fragile — reordering the dict silently changes behavior.

**Impact:** LOW — in the current table, no key is a substring of another key in a way that causes incorrect matching. But adding new models could break this.

**Fix (not in etapas — documented as known limitation):** Replace `key in model_lower` with exact prefix matching (e.g., `model_lower.startswith(key)`) or use longest-match (sort keys by length descending). This is a future cleanup item.

### C5 — `_estimate_cost` ignores reasoning/thinking tokens [LOW]

Some models (o1, o3, gemini-2.5-flash with thinking) generate internal reasoning tokens billed at output rate. The `_estimate_cost` method uses only `prompt_tokens` and `completion_tokens` from `response.usage`, which may or may not include reasoning tokens depending on the provider. When the primary cost path works (path 1), this is fine — OpenRouter includes all costs. But the fallback estimate will undercount for thinking-enabled models.

**Impact:** LOW — only affects the last-resort fallback path. The primary path captures the correct total.

**Fix (not in etapas — documented as known limitation):** A future enhancement could read `completion_tokens_details.reasoning_tokens` from the OpenAI SDK response object (available in SDK >= 1.40) and add them at the output rate. For now, document as known limitation.

### C6 — Missing-model fallback default is too low [MEDIUM]

**Location:** `llm_query.py:234-239`

When a model is not found in `_fallback_pricing`, the code defaults to $0.10/$0.40 per 1M tokens. This is appropriate for cheap models but catastrophically wrong for expensive ones (e.g., GPT-5 at $1.25/$10.00 would be reported at 8%/4% of actual cost; Grok-4 at $3.00/$15.00 would be at 3%/2.7%).

**Impact:** MEDIUM — users who add custom models to `models.txt` without updating the pricing table will get wildly inaccurate cost reports if the fallback fires.

**Fix (recommended, integrated into E4):** Two changes:
1. Change the default from $0.10/$0.40 to **$2.00/$8.00** (the GPT-4.1/GPT-4o midpoint — a safer conservative default that over-estimates cheap models but avoids dramatic under-estimates for expensive ones).
2. Emit a louder warning (Fore.RED instead of Fore.YELLOW) when the unknown-model fallback fires, so the user knows the cost is unreliable.

```python
# OLD:
print(Fore.YELLOW + f"Warning: No fallback pricing for '{model_name}'. Using $0.10/$0.40 per 1M." + Style.RESET_ALL)
prices = {"prompt": 0.10, "completion": 0.40}

# NEW:
print(Fore.RED + f"WARNING: No fallback pricing for '{model_name}'. Using conservative $2.00/$8.00 per 1M — cost may be inaccurate!" + Style.RESET_ALL)
prices = {"prompt": 2.00, "completion": 8.00}
```

### Summary of cost issues

| ID | Issue | Severity | Fix in etapas? | Status |
|---|---|---|---|---|
| C1 | 4 pricing entries wrong in `_fallback_pricing` | HIGH | Yes (E4) | Pending |
| C2 | `fetch_article_summary` cost leak on non-exception failures | MEDIUM | Yes (E5) | Pending |
| C3 | `_estimate_cost` uses requested model, not actual | LOW | No (known limitation) | Documented |
| C4 | `_estimate_cost` substring matching fragile | LOW | No (known limitation) | Documented |
| C5 | `_estimate_cost` ignores reasoning/thinking tokens | LOW | No (known limitation) | Documented |
| C6 | Missing-model fallback default too low | MEDIUM | Yes (E4) | Pending |
