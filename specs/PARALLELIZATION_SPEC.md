# PDFAnalyzer — Parallelization Spec v2.0

> **Status:** Draft v2.0 — clean rewrite, pending user approval.
> **Date:** 2026-06-13
> **Scope:** Method 1 (occurrence filtering) only. Method 2 unaffected.
> **Codebase:** `/home/gandalf/CodeRepository/PDFAnalyzer` (main branch)
> **Python:** 3.12.3 | **OS:** Linux (fork multiprocessing)
>
> **Revision history:**
> - v1.0 (2026-06-11) — initial draft
> - v1.1 (2026-06-11) — approved: A=5 + C=2, tqdm, auto-clamp
> - v1.2 (2026-06-13) — critical review: 14 issues found
> - v2.0 (2026-06-13) — clean rewrite; all findings integrated; new issues from deep audit

---

## 1. Goal

Reduce PDFAnalyzer execution time by parallelizing LLM calls in Method 1's
occurrence significance filter — without changing observable outputs and
without modifying existing functions (except ~8 LOC of thread-safety in
`llm_query.py`).

Two layers of parallelism:

- **A) Intra-PDF:** `ThreadPoolExecutor` — N workers per process (default 5)
- **C) Inter-PDF:** `ProcessPoolExecutor` — M processes dividing the batch (default 2)

**Default concurrency:** 2 × 5 = 10 simultaneous LLM calls.

**Opt-outs:**
- Omit `--parallel` → unchanged sequential behavior
- `--parallel --num-processes 1` → A=5 only
- `--parallel --max-workers 1` → C=2 only (mostly pointless but allowed)

---

## 2. Scope

### IN

- Method 1 occurrence loop → parallelized in new `parallel.py`
- `llm_query.py`: minimal thread-safety (~8 LOC)
- CLI: opt-in flags
- `requirements.txt`: add `tqdm`

### OUT (DO NOT TOUCH)

- `analyze_occurrences` (main.py L118-201)
- `analyze_single_occurrence` (llm_query.py L483-495)
- `_complete` (llm_query.py L428-456)
- `process_category` (main.py L294-356) — defined but never called (dead code)
- `read_pdf`, `extract_extended_context`, `keyword_search`, prompt/taxonomy files

### MINIMAL TOUCH (~8 LOC in `llm_query.py`)

- `_record_call`: add `with self._lock:` around `self.call_records.append(...)` only
  (NOT the entire function — `_fetch_generation_stats` HTTP calls run lock-free;
  `call_records.append` is atomic in CPython but the lock ensures safety across
  Python implementations and provides a clear contract)
- `get_random_model`: replace `random.choice(self.models)` with `self._rng.choice(self.models)`
  (`random.Random()` per instance — `random.choice()` uses shared global state, NOT thread-safe)
- `__init__`: add `self._lock = threading.Lock()` and `self._rng = random.Random()`

---

## 3. Codebase Facts (verified against real code)

These facts drove the design. All verified 2026-06-13.

| Fact | Detail |
|---|---|
| **OpenAI client is thread-safe** | OpenAI Python SDK v2.41.1 (httpx v0.28.1) — `client.chat.completions.create()` can be called concurrently from multiple threads sharing one `OpenAI` client instance. No lock needed around `_complete()`. |
| **`httpx.Client` is NOT fork-safe** | `ProcessPoolExecutor` with `fork` copies parent memory including connection pools. A forked `httpx.Client` may deadlock or corrupt. **Each worker process MUST create its own `LLMAnalyzer`** — never pass from parent. |
| **`KeywordSearcher` is thread-safe** | All methods are `@staticmethod` (pure) or read `self.enabler_keywords` (immutable after init). No locks needed. |
| **`random.choice()` is NOT thread-safe** | Uses global `random._inst` state. Concurrent calls corrupt state or skew selection. Fix: `random.Random()` per instance. |
| **CWD-relative file reads** | `load_prompt("keyword_occurrence_prompt.txt")`, `_load_models("models.txt")` all use `open(path)` relative to CWD. `ProcessPoolExecutor` workers inherit parent CWD — safe as long as main doesn't change CWD. **Document: caller must set CWD to project root before invoking.** |
| **`load_dotenv()` called inside `process_single_pdf`** | L376. Sets env vars including `ROUTER_API_KEY`. With `fork`, workers inherit env vars from parent. **Main process must call `load_dotenv()` before creating `ProcessPoolExecutor`** — otherwise workers lack the API key. |
| **`colorama.init()` is fork-safe** | `autoreset=True` wraps stdout/stderr. In `fork` mode, child inherits the wrapped streams. Works. |
| **Multiprocessing start method: `fork`** | Default on Linux. Workers inherit CWD, env vars, and stdout. Must NOT inherit `LLMAnalyzer` instances (httpx pool issue). |
| **`process_category` is dead code** | Defined at L294-356 but never called. Actual category loop is **inlined** at L466-518 in `process_single_pdf`. Parallel version mirrors the inline version. |
| **`generate_notes_table` import is a no-op** | `try: from generate_notes_table import ... except ImportError: pass`. Module doesn't exist. `process_single_pdf_v2` replicates the same try/except. |
| **Output files per PDF go to `pdf_path.parent`** | Each PDF writes to its own directory with unique filename stems. No collision between different PDFs in the same directory. |
| **`seen_paragraphs` dedup** | L133-135, L186-188. Prevents duplicate paragraphs in significant files when same paragraph matches multiple keywords. Must be replicated in parallel. |
| **Early returns** | L420-430 (no significant occurrences) and L443-449 (total < min_representative_matches). Both write summary and return early. Must be handled in `process_single_pdf_v2`. |

---

## 4. Architecture

### New module: `PDFAnalyzer/parallel.py` (~300 LOC)

```
main.py ---> run_pipeline_parallel()                    [NEW]
                |
                +-- load_dotenv() in MAIN PROCESS before fork
                |
                +-- auto-clamp: M = min(num_processes, len(files))
                |
                +-- M > 1 ? --> ProcessPoolExecutor(max_workers=M)
                |                  |
                |                  +-- _worker_process_entry()   [NEW]
                |                  |   (creates own LLMAnalyzer + load_dotenv)
                |                  +-- process_single_pdf_v2()  [NEW]
                |                       |
                |                       +-- analyze_occurrences_parallel()  [NEW]
                |                            |
                |                            +-- ThreadPoolExecutor(max_workers=N)
                |                            |   +-- _evaluate_one_occurrence() × N  [NEW]
                |                            |
                |                            +-- SharedAccumulator (in-memory, 1 lock)
                |                            +-- write significant files AT END
                |
                +-- M == 1 --> process_single_pdf_v2() in calling process
                                   (creates own LLMAnalyzer, no fork)
```

### Function inventory

| Function | Purpose | LOC |
|---|---|---|
| `_evaluate_one_occurrence(llm_analyzer, enabler, page_num, keyword, paragraph, pdf_text, abs_start, prompt_template, model_name)` | Builds prompt, calls `analyze_single_occurrence()`, returns `(page_num, keyword, paragraph)` if "significant" else `None`. Includes 429 retry (§6). **Not pure** — does HTTP I/O, appends to `call_records` (lock-protected). | ~35 |
| `SharedAccumulator` | Thread-safe dataclass: `filtered`, `seen_paragraphs`, `sig_paragraphs_by_enabler`. One `threading.Lock`. Methods: `record_significant(enabler, page_num, keyword, paragraph)` — dedup via `seen_paragraphs`, atomic with filtered update. `snapshot() → FilteredOccurrencesByEnabler`. **No file I/O.** | ~50 |
| `analyze_occurrences_parallel(pdf_text, enabler_occurrences, prompt_template, llm_analyzer, model_name, max_workers, total_occurrences)` | Same inputs/outputs as `analyze_occurrences`. Per category: submits occurrences to `ThreadPoolExecutor`; `SharedAccumulator` collects results. **After pool completes**: (1) deletes old significant files, (2) writes new significant files from accumulator. Returns `FilteredOccurrencesByEnabler`. tqdm bar per category. | ~65 |
| `process_single_pdf_v2(file_path, keywords_path, max_workers, min_representative_matches, model_name, log_level)` | Mirrors `process_single_pdf`. Calls `analyze_occurrences_parallel` instead of `analyze_occurrences`. Handles **both early returns** (no matches, total < min). Includes `fetch_article_summary`, inline category analysis loop (mirrors L466-518), all file writes, cost summary. | ~120 |
| `_worker_process_entry(pdf_path, keywords_path, max_workers, min_representative_matches, model_name, log_level)` | Top-level function (picklable). **Creates its own `LLMAnalyzer`** inside. Calls `process_single_pdf_v2`. Returns `pdf_path_str`. | ~15 |
| `run_pipeline_parallel(files, keywords_path, max_workers, num_processes, min_representative_matches, model_name, log_level, profile)` | Coordinator. Auto-clamps `num_processes`. Calls `load_dotenv()` in main process (so fork inherits env). `ProcessPoolExecutor` for M>1, direct call for M==1. After completion: scans `_cost.txt` files for aggregate summary. If `profile=True`, prints wall-clock time. | ~50 |

### Modifications in `main.py` (~15 LOC, additive)

```python
# In parse_arguments — add 5 new flags:
--max-workers N          [default 5, type=int]
--num-processes N        [default 2, type=int]
--parallel               [store_true]
--log-level LEVEL        [quiet|normal|verbose|debug, default normal]
--profile                [store_true]

# In main() — routing (8 LOC):
if args.parallel:
    from parallel import run_pipeline_parallel
    run_pipeline_parallel(
        files_to_process=files_to_process,
        keywords_path=keywords_path,
        max_workers=args.max_workers,
        num_processes=args.num_processes,
        min_representative_matches=args.min_representative_matches,
        model_name=args.model,
        log_level=args.log_level,
        profile=args.profile,
    )
else:
    # existing sequential loop unchanged
```

### Modifications in `llm_query.py` (~8 LOC, thread-safety)

```python
# In __init__ (add 2 lines):
import threading
self._lock = threading.Lock()
self._rng = random.Random()

# In get_random_model (1 line change):
selected_model = self._rng.choice(self.models)  # was: random.choice(self.models)

# In _record_call (wrap append with lock, ~5 lines changed):
def _record_call(self, model_name, generation_id, prompt_tokens, completion_tokens, cost_from_response):
    # ... cost resolution logic UNCHANGED (runs lock-free) ...
    # ... print statements UNCHANGED (see §7 for parallel-mode suppression) ...
    with self._lock:
        self.call_records.append(CallRecord(
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            source=source,
        ))
```

Key: lock covers **only** `call_records.append`. The cost-resolution logic
(`_fetch_generation_stats` HTTP calls, `_estimate_cost`, print statements)
runs **outside** the lock. This maximizes concurrency since:
- `_fetch_generation_stats` is idempotent per `generation_id` — safe to call concurrently
- `call_records.append` is atomic in CPython but the lock provides a clear contract
- No lock needed around `_complete()` — OpenAI client is thread-safe per SDK docs

---

## 5. Shared State — Complete Protection Map

| Item | Owner | Threads/Processes | Protection |
|---|---|---|---|
| `OpenAI client` (httpx) | 1 per `LLMAnalyzer` instance | Shared across threads (A layer) | **No lock needed** — SDK is thread-safe. NOT shared across processes (C layer) — each worker creates its own. |
| `call_records` list | `LLMAnalyzer` instance | Shared across threads (A layer) | `self._lock` around `append` only |
| `random` model selection | `LLMAnalyzer._rng` | Per-instance `random.Random()` | No shared state — each instance has its own RNG |
| `SharedAccumulator.filtered` | `parallel.py` | Shared across threads (A layer) | `threading.Lock` (same as `seen_paragraphs`) |
| `SharedAccumulator.seen_paragraphs` | `parallel.py` | Shared across threads (A layer) | Same lock as `filtered` — atomic check+add prevents dedup races |
| `SharedAccumulator.sig_paragraphs_by_enabler` | `parallel.py` | Shared across threads (A layer) | Same lock |
| `_significant_paragraphs_*.txt` files | `analyze_occurrences_parallel` | Written **after** pool completes | No lock needed — single-threaded write at end |
| Output files (`_cost.txt`, `_occurrences.txt`, etc.) | `process_single_pdf_v2` | 1 per PDF, 1 per process | No collision — each PDF has unique stem |
| stdout | All | Threads + processes | In parallel mode: `_record_call` prints → `logging.debug`. Only tqdm + summary visible. |

**Deadlock rule:** never hold 2 locks simultaneously.

---

## 6. Error Handling & Retry

| Scenario | Behavior |
|---|---|
| **429 rate-limit** | `_evaluate_one_occurrence` catches `RateLimitError`. **Never skips.** Retry with exponential backoff (1s → 2s → 4s → 8s → 16s → 30s cap), unlimited retries until the API responds. The rate limit will clear — we just wait. **Zero occurrence loss from parallelization.** |
| **Other errors (5xx, timeout, network)** | Same behavior as sequential: `analyze_single_occurrence` has try/except → returns error string ≠ "significant" → effectively skipped. These are genuine failures unrelated to parallelism. Sequential code does the same (`except Exception: continue` at L176-182). |
| Timeout (stuck worker) | `concurrent.futures.as_completed` with per-category timeout. Incomplete futures logged; completed results preserved. |
| Worker process crash | `future.result()` raises exception. Catch `BrokenProcessPool`. Log failed PDF, continue with remaining. |
| **Early return: no significant occurrences** | `process_single_pdf_v2` writes `write_occurrences_summary` + returns (mirrors L420-430). |
| **Early return: total < min** | `process_single_pdf_v2` writes `write_occurrences_summary` + returns (mirrors L443-449). |
| Ctrl+C | `ProcessPoolExecutor` workers are daemonic → killed. In-flight HTTP calls time out (~30s). Known limitation. |

### 429 retry detail (in `_evaluate_one_occurrence`)

```python
import time
from openai import RateLimitError

_BACKOFF_CAP = 30  # seconds

def _evaluate_one_occurrence(llm_analyzer, enabler, page_num, keyword,
                             paragraph, pdf_text, abs_start, prompt_template, model_name):
    extended_context = extract_extended_context(pdf_text, abs_start, abs_start + len(keyword))
    prompt_text = f"{prompt_template}\n\nEnabler: {enabler}\nKeyword: {keyword}\nContext:\n{extended_context}"
    backoff = 1
    while True:  # 429: retry forever (rate limit always clears)
        try:
            response = llm_analyzer.analyze_single_occurrence(prompt_text, model_name)
            if response and response.strip().lower() == "significant":
                return (page_num, keyword, paragraph)
            return None
        except RateLimitError:
            # log: "429 rate limit, retrying in {backoff}s..."
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_CAP)
        except Exception:
            return None  # non-429 error: same as sequential (skip)
```

Key: **429 retries forever** — the rate limit always clears. **Non-429 errors skip** — same as sequential.
Zero occurrence loss caused by parallelization.

---

## 7. Observability

### Parallel mode

- **Per-process tqdm:** Each `process_single_pdf_v2` shows a `tqdm` bar with PDF name prefix, advancing over total occurrences. No cross-process bar (fragile, adds complexity).
- **Print suppression:** In parallel mode, `_record_call` cost-logging and `get_random_model` model-selection prints go to `logging.debug` instead of stdout. Mechanism: `process_single_pdf_v2` sets a flag on `LLMAnalyzer` (e.g., `llm_analyzer.quiet = True`) checked by `_record_call` before printing.
- **Final summary:** total wall-clock time, total calls, total cost, $/PDF, count of skipped 429s.
- **`--log-level`:** `quiet` (tqdm only), `normal` (tqdm + final summary), `verbose` (+ per-category counts), `debug` (everything to log file — screen unreadable).
- **`--debug` + `--parallel`:** warning — debug output is unreadable when interleaved.

### Sequential mode (no `--parallel`)

Unchanged.

---

## 8. CLI

### New flags

```
--max-workers N      # 1..50, default 5
--num-processes N    # 1..cpu_count, default 2
--parallel           # opt-in (without = sequential, backwards compat)
--log-level LEVEL    # quiet|normal|verbose|debug, default normal
--profile            # print wall-clock time at end
```

### Validations

| Condition | Action |
|---|---|
| `max_workers < 1` | Error |
| `max_workers > 50` | Error (safety cap) |
| `num_processes < 1` | Error |
| `num_processes > cpu_count()` | Warning + clamp |
| `num_processes > len(pdf_indices)` | Silent auto-clamp |
| `--parallel` + `--debug` | Warning (debug unreadable in parallel) |

### Examples

```bash
# Sequential (unchanged)
python main.py /papers 0 5 cloud.json

# Parallel defaults: 2 procs × 5 threads = 10 concurrent
python main.py /papers 0 5 cloud.json --parallel

# A-only: 1 proc × 5 threads = 5 concurrent (debugging)
python main.py /papers 0 5 cloud.json --parallel --num-processes 1

# Profile mode
python main.py /papers 0 5 cloud.json --parallel --profile
```

---

## 9. Fork Safety Rules

The multiprocessing start method on this system is `fork`. These rules prevent
deadlocks and corruption:

1. **Main process must NOT create `LLMAnalyzer` before `ProcessPoolExecutor`.**
   `httpx.Client` connection pools are not fork-safe. Workers create their own.
2. **Main process calls `load_dotenv()` before fork.** Workers inherit env vars
   (including `ROUTER_API_KEY`) via fork. If `load_dotenv()` is only called inside
   the worker, it still works — but calling it in main ensures it's available
   for any pre-fork validation.
3. **Workers do NOT inherit threads.** The architecture is:
   `main → ProcessPoolExecutor → worker → ThreadPoolExecutor`. Fork happens
   before any threads are created, so no locks are held at fork time.
4. **CWD is inherited.** Workers use CWD-relative paths (`models.txt`, prompt
   `.txt` files). Must run from project root. No `os.chdir()` in the pipeline.
5. **If Python multiprocessing start method changes to `spawn`** (e.g., macOS,
   or future Python default), `_worker_process_entry` must call `load_dotenv()`
   and `colorama.init()` explicitly. Current code handles this naturally since
   each worker creates its own `LLMAnalyzer` (which reads `models.txt` + env).

---

## 10. Cost Aggregation

Each worker process creates its own `LLMAnalyzer` with its own `call_records`.
After all workers complete, `run_pipeline_parallel` aggregates costs:

1. Each worker writes `<pdf_stem>_cost.txt` (already done by `print_usage_summary`)
2. `run_pipeline_parallel` scans the output directory for `*_cost.txt` files
3. Parses each file for total calls + cost (same pattern as
   `full_pdf_analyzer.py` `generate_cost_table` L109-166)
4. Prints aggregate summary

No shared state between processes for cost tracking. File-based handoff is simple
and proven (already used by Method 2).

---

## 11. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Interleaved stdout | MED | Suppress prints in parallel mode; tqdm per-process |
| OpenRouter 429 rate limit | MED | `max_workers=5` caps burst; 429 retry **forever** with exponential backoff (1→2→4→8→16→30s cap). Zero occurrence loss. |
| Extra cost from 429 retries | LOW | Retries are billable but rare with `max_workers=5`. Worst case: rate-limit storm slows execution but never loses data. |
| `_fetch_generation_stats` burst | LOW | Runs lock-free (concurrent, idempotent). Lock only on `append`. Common case skips this path |
| Worker crash | MED | Catch `BrokenProcessPool`; log failed PDF; continue with remaining |
| Overhead > benefit (small workloads) | LOW | Auto-clamp `num_processes` to `len(pdf_indices)` |
| Output order differs | LOW | Documented; not a requirement |
| `random` thread-safety | MED | `random.Random()` per `LLMAnalyzer` instance (fixed) |
| httpx fork-unsafe | HIGH → FIXED | Each worker creates own `LLMAnalyzer` (never inherited) |
| CWD-dependent paths break | MED → FIXED | Workers inherit CWD; document: run from project root |
| Memory (2+ processes × ~300MB) | LOW | ~600MB for C=2. Fits 16GB VM for < 50 PDFs |
| `seen_paragraphs` dedup race | MED | Protected by same lock as `filtered` — atomic check+write |
| Significant file write race | HIGH → ELIMINATED | Files written at end from accumulator (single-threaded). No incremental writes from threads. |
| Ctrl+C in-flight HTTP | LOW | Workers daemonic; in-flight times out. Documented limitation |
| Dead code `process_category` confusion | LOW | Spec explicitly mirrors inline L466-518, not `process_category` |

---

## 12. Dependencies

| Dependency | Status | Note |
|---|---|---|
| `concurrent.futures` | stdlib | Thread + process pools |
| `threading` | stdlib | Lock, Lock context manager |
| `tqdm` | **NEW** | Add to `requirements.txt`. Progress bar. |
| `logging` | stdlib | Debug output in parallel mode |
| `tenacity` | NOT added | Inline retry is sufficient (3 lines) |

---

## 13. Implementation Sequence

| Step | What | LOC | Depends on |
|---|---|---|---|
| 0 | `llm_query.py`: add `self._lock`, `self._rng`, wrap `append`, fix `random.choice` | ~8 | — |
| 1 | `parallel.py`: `_evaluate_one_occurrence` (with 429 retry) | ~35 | Step 0 |
| 2 | `parallel.py`: `SharedAccumulator` (with `seen_paragraphs` dedup) | ~50 | — |
| 3 | `parallel.py`: `analyze_occurrences_parallel` (writes significant files at end) | ~65 | Steps 1-2 |
| 4 | `parallel.py`: `process_single_pdf_v2` (both early returns, fetch_article_summary, inline category loop) | ~120 | Step 3 |
| 5 | `parallel.py`: `_worker_process_entry` + `run_pipeline_parallel` (auto-clamp, cost aggregation, load_dotenv in main) | ~65 | Step 4 |
| 6 | `main.py`: new flags + routing | ~15 | Step 5 |
| 7 | tqdm per-process + print suppression (`LLMAnalyzer.quiet` flag) + `--log-level` | ~20 | Step 6 |
| 8 | Smoke test: 1 PDF (NIST.SP.800-207) with `--parallel` | — | Step 7 |
| 9 | Validation: 6 PDFs `--profile`, compare sequential vs A-only vs A+C | — | Step 8 |
| 10 | Update readme + `pdfanalyzer` skill + commit | — | Step 9 |

---

## 14. Testing Strategy

### Phase 1: Unit (new functions, mock LLM)

- `_evaluate_one_occurrence` → returns correct tuple / None
- `_evaluate_one_occurrence` → 429 retry: mock raises RateLimitError 3×, verifies backoff + eventual None
- `SharedAccumulator` → 10 threads × 100 ops: no lost updates, dedup correct
- `analyze_occurrences_parallel` → same output shape as `analyze_occurrences`
- `run_pipeline_parallel` → `num_processes=10` with 2 PDFs → uses 2

### Phase 2: Integration (1 PDF)

- Run NIST.SP.800-207 with `--parallel` (auto-clamp → C=1, A=5)
- **Time:** ≤ 3 min (sequential ~10 min)
- **Cost:** within 5% of $0.34 baseline
- **Files:** same names, valid contents
- **Counts:** `_occurrences.txt` significant/total ± any 429 skips

### Phase 3: Validation (6 PDFs)

- Run: (a) sequential, (b) `--parallel` (C=2, 10 concurrent), (c) `--parallel --num-processes 1` (5 concurrent)
- Compare time + cost across all three
- Verify all `_*.txt` files generated
- Diff `_all_category_results.txt` against sequential baseline

### Acceptance criteria

- No `--parallel` = identical to current sequential (backwards compat)
- 1 PDF `--parallel`: speedup ≥ 3x, cost delta < 5%
- 6 PDFs `--parallel`: speedup ≥ 5x
- 6 PDFs `--parallel --num-processes 1`: speedup ≥ 3x
- Zero crashes, zero data loss
- No duplicate paragraphs in significant files

---

## 15. Resolved Decisions

| # | Decision | Source |
|---|---|---|
| a | Default `--max-workers`: **5** | v1.1 (user) |
| b | Default `--num-processes`: **2** (auto-clamp to 1 for single PDF) | v1.1 (user) |
| c | Add `tqdm` to `requirements.txt` | v1.1 (user) |
| d | Save spec in Obsidian | v1.1 (user) |
| e | Write significant files at END from accumulator (not incrementally) | v2.0 (review) |
| f | `llm_query.py` gets ~8 LOC thread-safety (lock + random.Random) | v2.0 (review) |
| g | No `tenacity` — inline retry sufficient | v2.0 (review) |
| h | Per-process tqdm, not global | v2.0 (review) |
| i | 429 retries **forever** (never skip); backoff capped at 30s. Zero occurrence loss from parallelization. Non-429 errors: same as sequential (skip). | v2.0 (review + user requirement) |
| j | Cost aggregation via `_cost.txt` file scan | v2.0 (review) |
| k | Lock only `call_records.append`, not entire `_record_call` | v2.0 (deep audit — OpenAI client is thread-safe) |
| l | Each worker creates own `LLMAnalyzer` (httpx fork-unsafe) | v2.0 (deep audit) |
| m | `load_dotenv()` in main process before fork | v2.0 (deep audit — fork inherits env) |

---

## 16. Open Questions

1. **`process_category` dead code:** Remove in separate PR? **(Recommendation: out of scope — leave it.)**

---

**Next step:** User approval → implement per §13 sequence. First action: Step 0 (thread-safety in `llm_query.py`, ~8 LOC).
