# PDFAnalyzer — Statistics Enhancement Spec v1.0

> **Status:** Draft v1.0 — pending user approval.
> **Date:** 2026-06-11
> **Scope:** Method 1 (`main.py`) + Method 2 (`full_pdf_analyzer.py`). Both share `LLMAnalyzer` in `llm_query.py`.
> **Codebase:** PDFAnalyzer repo (public), main branch
> **Python:** 3.12.3 | **OS:** Linux
>
> **Revision history:**
> - v1.0 (2026-06-11) — initial draft. Scope closed to 4 items: latency, temperature, top-p, model version. Prompt versioning deferred (user decision 2026-06-11).
> - v1.1 (2026-06-11) — conservative sampling validation added (R6 mitigation, user decision option A). New helper `validate_sampling_for_model()` in `llm_query.py`; enforcement at CLI parse time and at runtime in `_complete`. Acceptance criteria A9–A11 added. Implementation order grew from 9 to 12 etapas (new E3 for helper, E7 for CLI validation, E11 for reasoning-model rejection check).

---

## 1. Goal

Enhance the per-PDF cost/execution statistics emitted by PDFAnalyzer so users can:

1. **Diagnose performance** — know the latency distribution of individual LLM calls (min/max/mean/p50/p95/p99) and identify outliers.
2. **Reproduce runs** — record the exact `temperature` and `top_p` used per call so a re-run with the same flags produces the same sampling behavior.
3. **Identify the actual model served** — OpenRouter may return a different model string than requested (snapshot versions, fallbacks). Capture the real `response.model` so cost reports show what was actually billed.
4. **Tune sampling on demand** — expose `--temperature` and `--top-p` as CLI flags (currently hardcoded to OpenRouter's implicit defaults of 1.0/1.0).

All changes must be **backwards compatible**: existing invocations without the new flags produce bit-identical `*_cost.txt` (modulo the new sections appended at the end) and identical significant-occurrence counts.

**Non-goals (deferred from TOOLS-002):** prompt versioning, retries, error type breakdown, per-phase timing, ETA projection, histogram of latencies, cache tracking, inter-call gaps, per-category cost. These remain in `TOOLS-002-estatisticas-pdfanalyzer.md` as future work.

---

## 2. Scope

### IN

- `llm_query.py`:
  - Add 4 new fields to `CallRecord` dataclass (with defaults — backwards compat).
  - Extend `LLMAnalyzer.__init__` signature to accept `temperature` and `top_p`.
  - Extend `_complete` to: time the call, pass `temperature`/`top_p` to the SDK, capture `response.model`.
  - Extend `_record_call` to receive and store the 4 new values.
  - Extend `print_usage_summary` to emit 2 new sections (`LATENCY` + `SAMPLING & MODEL`) and extend `PER-MODEL BREAKDOWN` to show `model_version`.
- `main.py`:
  - Add 2 new CLI flags: `--temperature`, `--top-p`.
  - Pass them to `LLMAnalyzer()` constructor (line 393).
- `full_pdf_analyzer.py`:
  - Add the same 2 CLI flags.
  - Pass them to its `LLMAnalyzer` instance.

### OUT (DO NOT TOUCH)

- `analyze_occurrences` (main.py) — internal loop, not affected.
- `analyze_single_occurrence` (llm_query.py) — caller of `_complete`, no change needed (it just receives the result string).
- `parallel.py` — parallel orchestration is unaffected. The per-worker `LLMAnalyzer` already has the new fields; the cost aggregation pattern (scan `_cost.txt` after workers finish) is preserved.
- `process_category` (main.py) — dead code, untouched.
- `load_prompt`, `load_enabler_keywords`, `_load_models` — no change.
- Prompt files (`*.txt`) — no change. No versioning system introduced.
- `readme.md` — updated in E9 with a one-paragraph mention, not a full new section.

### MINIMAL TOUCH (rough estimate)

- `llm_query.py`: ~50 LOC added (4 dataclass fields, 2 instance attrs, 5-line wrap in `_complete`, 5-line print section, 2-LOC PER-MODEL extension).
- `main.py`: ~10 LOC added (2 argparse entries + 1-line pass to constructor).
- `full_pdf_analyzer.py`: ~10 LOC added (same as main.py).
- Total: ~70 LOC across 3 files. No new dependencies.

---

## 3. Codebase Facts (verified against real code, 2026-06-11)

| Fact | Detail |
|---|---|
| **`CallRecord` is a `@dataclass` at llm_query.py:22** | Adding fields with defaults is safe — existing constructors with positional args (none external) keep working. |
| **`_complete` at llm_query.py:462** | Calls `self.client.chat.completions.create(model=model_name, messages=[...])`. **No `temperature` or `top_p` is passed today** — OpenRouter's implicit defaults (1.0/1.0) are used. |
| **`_record_call` at llm_query.py:248** | Receives `model_name, generation_id, ...` and appends to `self.call_records`. Has access to the parsed usage data; does **NOT** currently receive the response object. **Decision**: pass the 4 new values as explicit kwargs from `_complete` — keeps `_record_call`'s signature stable. |
| **`response.model` exists in OpenAI Python SDK** | `ChatCompletion.model` is the actual model used by the server. With OpenRouter, this may differ from the requested string (e.g. request `"google/gemini-2.5-flash"`, response may be `"google/gemini-2.5-flash-preview-05-20"`). |
| **OpenRouter's `temperature` default is 1.0** | Confirmed via OpenRouter API docs. Explicitly passing `temperature=1.0` is **bit-identical** to omitting it. Same for `top_p`. |
| **OpenRouter supports `temperature` and `top_p`** | Both are passed via the OpenAI-compatible API in the standard `chat.completions.create(...)` kwargs. |
| **`print_usage_summary` at llm_query.py:332** | Writes a human-readable text file. The downstream `generate_cost_summary.py` parses it with regex on `Total cost:` and `calls=` only — new appended sections don't break the parser. |
| **CLI flags of `main.py`** (verified) | Positional: `source_folder, start_index, end_index, keywords_path`. Optional: `--model`, `--min-representative-matches`, `--debug`, `--parallel`, `--max-workers`, `--num-processes`, `--log-level`, `--profile`. New `--temperature` and `--top-p` slot in cleanly. |
| **`load_prompt` is a `@staticmethod` at llm_query.py:453** | Returns the file contents as a string. **No change required** for this spec. |
| **Cost file path** | `<pdf_path.stem>_cost.txt` written by `llm_analyzer.print_usage_summary(str(cost_file))` at main.py:556. New sections append inside the same file. |
| **Thread-safety** | TOOLS-001's lock around `self.call_records.append(...)` is preserved. The new fields are read/written only inside the lock (the entire `_record_call` body is locked per the v2.0 design). |

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
        │  ┌─ time.perf_counter()  ─┐
        │  │   response = client.chat.completions.create(  │
        │  │       model=model_name,                                │
        │  │       temperature=self.temperature,                    │
        │  │       top_p=self.top_p,                                │
        │  │       messages=[...])                                  │
        │  │   latency_s = perf_counter() - t0                      │
        │  └────────────────────────────────────────┘
        │
        ▼
_record_call(model_name, generation_id, prompt_tokens, completion_tokens,
             cost_usd, source, latency_s, temperature, top_p, model_version)
        │  appends to self.call_records (under lock)
        ▼
... (N occurrences) ...

print_usage_summary(output_file)
        │  reads self.call_records
        │  aggregates:
        │    - latency_s: min/max/mean/p50/p95/p99
        │    - temperature/top_p: distribution
        │    - model_version: per-model breakdown
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
    latency_s: float = 0.0           # wall-clock seconds of the SDK call
    temperature: float | None = None # value passed to the API (None = not set)
    top_p: float | None = None       # value passed to the API (None = not set)
    model_version: str | None = None # response.model from the server
```

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

### `_complete` diff (illustrative)

```python
def _complete(self, model_name, system_message, user_message) -> str:
    t0 = time.perf_counter()  # NEW
    response = self.client.chat.completions.create(
        model=model_name,
        temperature=self.temperature,   # NEW
        top_p=self.top_p,               # NEW
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user",   "content": user_message},
        ],
    )
    latency_s = time.perf_counter() - t0  # NEW
    model_version = getattr(response, "model", None)  # NEW
    reply = response.choices[0].message.content.strip()

    # Pass new values to _record_call
    self._record_call(
        model_name=model_name,
        generation_id=response.usage.model_extra.get("id", ""),
        prompt_tokens=...,
        completion_tokens=...,
        cost_usd=...,
        source="openrouter",
        latency_s=latency_s,            # NEW
        temperature=self.temperature,   # NEW
        top_p=self.top_p,               # NEW
        model_version=model_version,    # NEW
    )
    return reply
```

### `print_usage_summary` output (new sections appended)

```
======================================================================
LATENCY (per LLM call, seconds)
----------------------------------------------------------------------
calls:    1,644
min:      0.182
max:      4.713
mean:     0.781
p50:      0.612
p95:      1.943
p99:      3.221
======================================================================
SAMPLING & MODEL
----------------------------------------------------------------------
temperature: 1.0   (used in 1,644/1,644 calls)
top_p:       1.0   (used in 1,644/1,644 calls)
======================================================================
PER-MODEL BREAKDOWN
----------------------------------------------------------------------
  google/gemini-3-flash-preview
    actual: google/gemini-3-flash-preview-05-20
    calls=1,640  prompt=655,645  completion=3,477  cost=$0.33825350  [openrouter]
    latency: min=0.182  max=4.713  mean=0.781  p50=0.612  p95=1.943
  ...
======================================================================
```

The original `Total API calls`, `Prompt tokens`, `Total cost` sections stay byte-identical.

### Sampling validation (conservative — R6 mitigation)

OpenRouter's reasoning models (OpenAI o1/o1-mini/o1-preview/o3/o3-mini, GPT-5 family, DeepSeek r1, Claude `*-thinking`) reject `temperature != 1.0` or `top_p != 1.0` with HTTP 400. A user invoking the tool with `--temperature 0.0 --model openai/o1` would burn the API key on 1644 failed calls. **Decision (user, 2026-06-11): reject at parse time + safety net at runtime.**

A helper in `llm_query.py`:

```python
REASONING_MODEL_PATTERNS: tuple[str, ...] = (
    "o1", "o3", "gpt-5", "r1", "thinking",
)

def is_reasoning_model(model: str) -> bool:
    m = model.lower()
    return any(p in m for p in REASONING_MODEL_PATTERNS)

def validate_sampling_for_model(
    model: str, temperature: float, top_p: float,
) -> tuple[float, float]:
    """Reject sampling overrides incompatible with reasoning models.

    Raises ValueError with a clear message if the combination is invalid.
    Returns the (validated) sampling params unchanged otherwise.
    """
    if is_reasoning_model(model) and (temperature != 1.0 or top_p != 1.0):
        raise ValueError(
            f"Model '{model}' is a reasoning model and only supports "
            f"temperature=1.0 and top_p=1.0. "
            f"Got temperature={temperature}, top_p={top_p}."
        )
    return temperature, top_p
```

**Two enforcement points:**

1. **CLI parse time** (in `main.py` and `full_pdf_analyzer.py`): if `args.model != "random"` and the model matches a reasoning pattern, call `validate_sampling_for_model(args.model, args.temperature, args.top_p)` immediately after `parse_args()`. On `ValueError`, print the message in red and exit with code 2.

2. **Runtime safety net** (in `_complete`): after `model_name` is selected (whether via `--model` or `get_random_model()`), call `validate_sampling_for_model(model_name, self.temperature, self.top_p)` *before* the `client.chat.completions.create(...)` call. This catches the `--model random` case where the picked model is reasoning and the user set non-1.0 sampling.

The error path in `_complete` is a `ValueError` raised before any HTTP call — no API cost, no token spend, no `*_cost.txt` write.

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

---

## 5. Implementation order (incremental, "test 1 by 1")

Mirrors the TOOLS-001 pattern. Each step ends with a focused test the user can verify before approving the next.

- [ ] **E1 — CallRecord fields**: add 4 new fields with defaults to the dataclass. No other code changes. **Test:** import the module and instantiate `CallRecord(model=..., prompt_tokens=1, ...)` — old call style still works.
- [ ] **E2 — LLMAnalyzer constructor**: add `temperature` and `top_p` params with defaults 1.0; store as instance attrs. **Test:** instantiate `LLMAnalyzer()` and `LLMAnalyzer(temperature=0.5, top_p=0.9)`; assert `self.temperature` / `self.top_p` correct.
- [ ] **E3 — Sampling validation helper**: add `REASONING_MODEL_PATTERNS`, `is_reasoning_model()`, `validate_sampling_for_model()` to `llm_query.py` (module-level, no class). **Test:** `validate_sampling_for_model("openai/o1", 1.0, 1.0)` returns (1.0, 1.0); `validate_sampling_for_model("openai/o1", 0.5, 1.0)` raises ValueError; `validate_sampling_for_model("google/gemini-2.5-flash", 0.5, 0.9)` returns (0.5, 0.9).
- [ ] **E4 — _complete timing + params + safety net**: wrap the SDK call with `time.perf_counter()`, pass `temperature`/`top_p`, capture `response.model`, call `validate_sampling_for_model(model_name, self.temperature, self.top_p)` BEFORE the SDK call, pass the 4 new values to `_record_call`. **Test:** run a single LLM call with default model — assert `call_records[-1].latency_s > 0`, `.temperature == 1.0`, `.top_p == 1.0`, `.model_version` is a non-empty string.
- [ ] **E5 — print_usage_summary extensions**: add the 2 new sections + extend PER-MODEL. **Test:** run E4 and inspect the `*_cost.txt` — all original lines present + new sections present + parseable.
- [ ] **E6 — CLI flags in main.py**: add `--temperature` and `--top-p`, thread to `LLMAnalyzer()`. **Test:** `python main.py --help` shows the new flags; running without them behaves identically to E5.
- [ ] **E7 — CLI validation in main.py**: after `parse_args()`, if `args.model != "random"`, call `validate_sampling_for_model(args.model, args.temperature, args.top_p)`. On ValueError, print red and `sys.exit(2)`. **Test:** `python main.py /tmp/ 0 0 cloud.json --model openai/o1 --temperature 0.0` exits with code 2 and a clear message; same with `--model openai/o1` and default 1.0/1.0 passes validation.
- [ ] **E8 — CLI flags + validation in full_pdf_analyzer.py**: mirror E6 + E7. **Test:** same as E7 for the full-text script.
- [ ] **E9 — Smoke test 1 PDF (NIST.SP.800-207)**: run E6 + E7 + E8 in sequence (sequential mode, no `--parallel`). Acceptance:
  - Significant occurrences **identical** to the per-PDF baseline in `Standards/NIST.SP.800-207_*.txt` from the user's article-private repo (1644 calls expected, $0.34 ± 5%).
  - New `*_cost.txt` contains the 2 new sections + extended PER-MODEL.
  - `model_version` in PER-MODEL is non-empty and matches the expected OpenRouter snapshot string.
- [ ] **E10 — Determinism check (optional)**: run the same PDF with `--temperature 0.0 --top-p 1.0` and confirm: same cost, same call count, but `latency_s` distribution may differ (deterministic models sometimes take longer or shorter — only checked as informational, not a pass/fail).
- [ ] **E11 — Reasoning-model rejection check**: run `python main.py /tmp/ 0 0 cloud.json --model openai/o1 --temperature 0.5` and confirm: exits with code 2 BEFORE any API call (no `*_cost.txt` produced). Then run with `--model openai/o1` and default 1.0/1.0 — should proceed (whether or not it succeeds depends on key/model availability, but no validation error).
- [ ] **E12 — Skill + readme + commit**: append a one-paragraph "Statistics enhancements" section to `readme.md` and a `STATISTICS_SPEC.md` reference in the `pdfanalyzer` skill. Conventional commit `feat(stats): track latency, sampling params, model version (v1.0)`.

---

## 6. Acceptance criteria

| # | Criterion | How verified |
|---|-----------|--------------|
| A1 | `python main.py --help` shows `--temperature` and `--top-p` | Manual `--help` |
| A2 | Running without the new flags produces a `*_cost.txt` with **all** the original sections (verified by line-by-line diff against baseline) | `diff <baseline> <new>` |
| A3 | `*_cost.txt` ends with the new `LATENCY` and `SAMPLING & MODEL` sections | `tail` |
| A4 | `PER-MODEL BREAKDOWN` shows `actual: <response.model>` for each model | grep `actual:` |
| A5 | Smoke test on `NIST.SP.800-207.pdf` (cloud.json, sequential, no `--parallel`): cost within ±5% of baseline $0.339, call count identical at 1,644, significant paragraphs **bit-identical** to the article-private baseline under `Standards/` | `diff -r /tmp/smoke_results/ <article-private-repo>/Standards/`, restricted to `*_significant_paragraphs_*.txt` and `*_occurrences.txt` |
| A6 | `--temperature 0.0 --top-p 1.0` produces the same number of calls and within ±5% cost (content of significant paragraphs may differ — that's expected with T=0) | Smoke run with the flag, count + cost check |
| A7 | No new files (everything inside the existing `*_cost.txt`) | `ls` |
| A8 | No new dependencies in `requirements.txt` | `git diff requirements.txt` should be empty |
| A9 | `python main.py /tmp/ 0 0 cloud.json --model openai/o1 --temperature 0.5` exits with code 2, no `*_cost.txt` produced, error message mentions "reasoning model" | Run + check `$?` + `ls /tmp/*cost*` |
| A10 | `python main.py /tmp/ 0 0 cloud.json --model openai/o1` (defaults 1.0/1.0) passes validation and reaches the API call phase | Run + check no ValueError from `validate_sampling_for_model` |
| A11 | `validate_sampling_for_model("anthropic/claude-3.7-sonnet:thinking", 0.0, 1.0)` raises ValueError (covers the `*-thinking` pattern) | Inline Python check |

---

## 7. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Changing `temperature` from "implicit default" to "explicit 1.0" might shift OpenRouter's behavior | Low | OpenRouter docs state the default is exactly 1.0 for both. Smoke test A5 will catch any drift. |
| `response.model` may be `None` for some error responses or for non-OpenAI-compatible providers | Low | `model_version` defaults to `None` and the print section handles it (shows "n/a"). |
| Adding 4 fields to `CallRecord` breaks any external code that constructs it positionally | Low | No external constructors found via grep. All CallRecord constructions are inside `_record_call` itself. |
| `time.perf_counter()` overhead per call is significant | Negligible | ~100ns; the SDK call takes ≥180ms. |
| New print sections break `generate_cost_summary.py` regex | Low | That script only matches `Total cost:` and `Total API calls:` — both unchanged. Verified by re-reading the parser. |
| Different OpenRouter models may reject `temperature` or `top_p` (e.g. o1 reasoning models only accept `temperature=1.0`) | Medium (mitigated) | **Mitigation chosen (user, 2026-06-11, option A — conservative):** reject at parse time + safety net at runtime. `validate_sampling_for_model()` raises `ValueError` if the model matches a reasoning pattern (`o1`, `o3`, `gpt-5`, `r1`, `thinking`) AND (temperature ≠ 1.0 OR top_p ≠ 1.0). Two enforcement points: (1) CLI argparse in `main.py` / `full_pdf_analyzer.py` — `sys.exit(2)` with a clear red error before any work; (2) runtime in `_complete` — same check before `client.chat.completions.create()` catches the `--model random` case. No HTTP call, no API cost, no `*_cost.txt` write. Acceptance criteria A9, A10, A11 verify both enforcement points. |

---

## 8. Open questions

None. The user's decisions on 2026-06-11 closed the open items:

- ~~Temperature/top_p default value~~ → **1.0/1.0** (= current OpenRouter default; explicit, not implicit).
- ~~Prompt versioning~~ → **deferred**. Prompts are stable; no version system needed.
- ~~Separate `*_stats.json` file vs extend `*_cost.txt`~~ → **extend `*_cost.txt`**. JSON would be additive work; not asked.
- ~~Spec-first vs code-first~~ → **spec-first**. This document is the spec.

---

## 9. Reference: code line numbers (verified 2026-06-11)

- `CallRecord`: `llm_query.py:22-29`
- `LLMAnalyzer.__init__`: `llm_query.py:54-91`
- `_record_call`: `llm_query.py:248-311`
- `print_usage_summary`: `llm_query.py:332-396`
- `load_prompt`: `llm_query.py:453-456`
- `_complete`: `llm_query.py:462-498`
- `LLMAnalyzer()` instantiation in main: `main.py:393`
- `cost_file` write: `main.py:556-557`
- main.py argparse: `main.py:571-624`
