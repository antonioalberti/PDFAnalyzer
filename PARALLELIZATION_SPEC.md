# PDFAnalyzer — Parallelization Spec (A + C)

> **Status:** Draft v1.1 — approved 2026-06-11, ready to implement.
> **Date:** 2026-06-11
> **Scope:** PDFAnalyzer repository only. Affects Method 1 (occurrence filtering) only — Method 2 unaffected.
>
> **Revision history:**
> - v1.0 (2026-06-11) — initial draft, awaiting user approval
> - v1.1 (2026-06-11) — approved: defaults set to A=5 + C=2 (10 concurrent), `tqdm` adopted, auto-clamp added for small workloads

## 1. Goal

Reduce PDFAnalyzer pipeline execution time by parallelizing the LLM calls in the keyword-occurrence significance filter (Method 1), without changing the observable outputs and without modifying existing functions.

Two layers of parallelism:

- **A) Intra-PDF:** `ThreadPoolExecutor` with N workers per process
- **C) Inter-PDF:** `ProcessPoolExecutor` with M processes dividing the batch

**Default behavior (when `--parallel` is set):** A=on (max_workers=5) + C=on (num_processes=2). Total concurrency = 10 simultaneous LLM calls.

**Opt-outs:**
- Omit `--parallel` → unchanged sequential behavior (backwards compat)
- `--parallel --num-processes 1` → A=5 only (5 concurrent)
- `--parallel --max-workers 1` → C=2 only (2 concurrent, mostly pointless but allowed)

## 2. Scope

### IN

- Method 1 (`analyze_occurrences`): the occurrence-evaluation loop
- Output reporting for the parallel phase (status, cost)
- CLI: new opt-in flags

### OUT (DO NOT TOUCH)

- `analyze_occurrences` (existing code in `main.py` L118-201)
- `process_category` (L294-356)
- `analyze_single_occurrence` in `llm_query.py` (L483-495)
- `_complete` in `llm_query.py` (L428-456)
- `_record_call` in `llm_query.py` (L230-291) — unless it becomes a bottleneck
- Any prompt (`.txt`) or taxonomy (`.json`)
- `read_pdf`, `extract_*`, `keyword_search`, `llm_query` (structure)

## 3. Architecture

New module: `PDFAnalyzer/parallel.py` (~200-250 LOC, focus on composition).

Logical diagram:

```
main.py ---> run_pipeline_parallel()         [NEW, new entry point]
                |
                +-- len(pdfs) < num_processes ? --> auto-clamp to len(pdfs)
                |
                +-- num_processes > 1 ? --> ProcessPoolExecutor
                |                                |
                |                                +-- _worker_process_entry()      [NEW]
                |                                        |
                |                                        +-- process_single_pdf_v2()   [NEW]
                |                                                |
                |                                                +-- analyze_occurrences_parallel()  [NEW]
                |                                                        |
                |                                                        +-- _evaluate_one_occurrence()  [NEW]
                |                                                        +-- ThreadPoolExecutor(max_workers=5)
                |
                +-- num_processes == 1 --> process_single_pdf_v2() directly (in calling process)
```

### New functions in `PDFAnalyzer/parallel.py`

| Function | Purpose | Est. LOC |
|---|---|---|
| `_evaluate_one_occurrence(...)` | Pure function: (enabler, keyword, paragraph, ...) -> Result\|None. Builds prompt, calls LLM, returns tuple if "significant" else None. No shared state, no I/O. | ~25 |
| `SharedAccumulator` (dataclass + lock) | Thread-safe aggregator: `filtered`, `call_records`, `paragraphs_by_enabler`. Methods: `record_significant()`, `record_call()`, `snapshot()`. | ~50 |
| `run_with_concurrency_limit(items, worker_fn, max_workers, on_result)` | Generic bounded executor. ThreadPoolExecutor with max_workers=N; submits all items; each result calls `on_result(accumulator, result)`. | ~30 |
| `analyze_occurrences_parallel(...)` | Mirrors `analyze_occurrences` (same inputs, same outputs). Iterates categories; per category, submits occurrences to `run_with_concurrency_limit`; on_result writes to accumulator. At end, writes `_significant_paragraphs_category_N.txt` files. Returns `dict filtered_enabler_occurrences`. | ~50 |
| `process_single_pdf_v2(...)` | Mirrors `process_single_pdf` but uses `analyze_occurrences_parallel`. Loads PDF, extracts text, loads keywords, runs enabler_occurrences, writes summary files, saves cost. | ~30 |
| `_worker_process_entry(pdf_paths_chunk, ...)` | Entry point for `ProcessPoolExecutor` (top-level, picklable). Iterates PDFs in chunk, calls `process_single_pdf_v2` for each. | ~20 |
| `run_pipeline_parallel(...)` | Top-level coordinator. **First action: auto-clamp num_processes to len(pdf_indices).** Then either runs sequentially in a thread pool (num_processes==1) or uses ProcessPoolExecutor (num_processes>1). | ~40 |

### Modifications in `main.py` (minimal, additive only)

In `parse_arguments` (L567-606):

```python
--max-workers N          [default 5, type int]
--num-processes N        [default 2, type int]
--parallel               [store_true, opt-in flag; default off = sequential for backwards compat]
--log-level LEVEL        [quiet|normal|verbose|debug, default normal]
--profile                [store_true, prints total time at end]
```

In `main()` (L607+):

```python
if args.parallel:
    # New defaults: max_workers=5, num_processes=2 (10 concurrent)
    # run_pipeline_parallel auto-clamps num_processes to len(pdf_indices)
    from parallel import run_pipeline_parallel
    run_pipeline_parallel(
        ...,
        max_workers=args.max_workers,
        num_processes=args.num_processes,
        log_level=args.log_level,
        profile=args.profile,
    )
else:
    # existing code unchanged — backwards compatible
```

Estimated change to `main.py`: **~15-20 LOC, all additive**.

## 4. Concurrency Model

### Threads per process

- `concurrent.futures.ThreadPoolExecutor(max_workers=N)`
- N configurable, default 5
- Each thread: 1 blocking HTTP call + 1 record (with lock)
- OpenAI client is sync; GIL doesn't matter (threads blocked on I/O)

### Processes

- `concurrent.futures.ProcessPoolExecutor(max_workers=M)`
- M configurable, default 2 (active)
- Each process has its own `LLMAnalyzer`, `call_records`, files
- If M > len(pdf_indices), `run_pipeline_parallel` auto-clamps to len(pdf_indices) (no warning, no idle-process overhead)

### Total concurrency

`M × N` = 2 × 5 = 10 (default)
Clamped to `len(pdf_indices) × N` when there are fewer PDFs than processes

### Limitation

- `max_workers` on the ThreadPoolExecutor naturally bounds concurrency
- Add retry with backoff for 429 responses inside `analyze_single_occurrence` (small touch, no structural change)
- NO asyncio — sticking with threading (per user decision)

## 5. Shared State — Protection

| Item | Where | Protection |
|---|---|---|
| `call_records` (`LLMAnalyzer`) | `_record_call` | `threading.Lock` global |
| `filtered` (accumulator) | new class | `threading.Lock` |
| `paragraphs_by_enabler` | new class | `threading.Lock` |
| `_significant_paragraphs_*` | output files | per-file Lock |
| stdout (prints) | main + llm_query | global Lock OR redirect to log |
| `current_occurrence` counter | main.py | removed (not needed in parallel) |

**Rule:** 1 lock per shared resource; never hold 2 locks at the same time (avoids deadlock). All via context manager (`with lock: ...`).

## 6. Error Handling

- `analyze_single_occurrence` already has try/except; individual failures don't crash the worker
- In parallel, same guarantee: 1 failure in N calls doesn't affect the others
- Timeout per worker: `add_done_callback` with 60s timeout per call (configurable); on timeout, log and continue
- Fatal error in worker process: log + exit code != 0; main process waits for all and reports which failed

## 7. Observability

### Current (problematic in parallel)

```
"Occurrence 1620/1633: Keyword 'federated' on page 35"  <- all threads interleave
```

### New strategy

- `tqdm.progress_bar` over total occurrences (updated via callback)
- Per-thread logs suppressed in parallel mode (go to log buffer)
- Final summary: total time, calls, cost, $/PDF
- Flag `--log-level {quiet,normal,verbose|debug}` controls verbosity (default `normal`)
- Debug mode inactive in parallel (impossible to read interleaved output)

## 8. CLI / Interface

### New flags (all additive; default = current behavior when `--parallel` is omitted)

```
--max-workers N      # 1..50, default 5
--num-processes N    # 1..(cpu_count), default 2 (auto-clamped to len(pdf_indices))
--parallel           # opt-in flag; without it = unchanged sequential behavior
--log-level LEVEL    # quiet|normal|verbose|debug, default normal
--profile            # print total time at end (useful for comparing)
```

### Validations

- `max_workers < 1` → error
- `num_processes > os.cpu_count()` → warning + clamp
- `num_processes > 1` with `--debug` → warning (debug is unusable in parallel)
- `num_processes > len(pdf_indices)` → silent auto-clamp (no warning, no idle-process overhead)

### Example invocations

```bash
# current (unchanged) — no flags = sequential
python main.py /papers 0 5 cloud.json

# parallel with new defaults: 2 processes x 5 threads = 10 concurrent
python main.py /papers 0 5 cloud.json --parallel

# A-only (1 process, 5 threads) — for debugging
python main.py /papers 0 5 cloud.json --parallel --num-processes 1

# C=2 + A=5 explicit (same as default, for clarity in scripts)
python main.py /papers 0 5 cloud.json --parallel --num-processes 2 --max-workers 5

# profile to see speedup
python main.py /papers 0 5 cloud.json --parallel --profile
```

## 9. Testing Strategy

### Phase 1: Unit

- Test `_evaluate_one_occurrence` with mock LLM
- Test `SharedAccumulator` for race conditions (10 threads, 100 ops)
- Test `run_with_concurrency_limit` with slow mock
- Test `run_pipeline_parallel` auto-clamp when `num_processes > len(pdf_indices)`

### Phase 2: Integration (1 PDF, smoke test)

- Re-run `NIST.SP.800-207` with `--parallel` (defaults: A=5, C=2)
- **Note:** with 1 PDF, auto-clamp reduces to C=1 → A=5 only (5 concurrent)
- Verify:
  - **Time:** <= 3 min (sequential ~10 min, 3x with A=5)
  - **Cost:** within 5% of sequential
  - **Files generated:** same names, valid contents
  - **`_occurrences.txt`:** same counts (significant vs total)

### Phase 3: Validation (6 PDFs, --profile)

- Run all 6 PDFs with `--parallel` (defaults: A=5, C=2, 10 concurrent)
- Run all 6 PDFs with `--parallel --num-processes 1` (A=5 only, 5 concurrent) for comparison
- Compare time and cost across both
- Verify ALL `_*.txt` files generated
- Diff `_all_category_results.txt` against previous baseline

### Acceptance criteria

- Default (no flags) = behavior identical to current (sequential, no surprise)
- `--parallel` with 1 PDF: speedup >= 3x, cost delta < 5% (auto-clamp engages C=1)
- `--parallel` with 6 PDFs: speedup >= 5x (10 concurrent vs 1)
- `--parallel --num-processes 1` with 6 PDFs: speedup >= 3x (5 concurrent vs 1)
- Zero crashes, zero data loss

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Interleaved output (print, files) | Locks per resource; tqdm |
| OpenRouter rate limit (429) | Limited `max_workers` + retry |
| Higher cost (re-done calls) | No retry of failed calls; cost identical |
| Crash in 1 worker process | Broad try/except + reporting |
| Overhead > benefit for small workloads (num_processes > len(pdfs)) | Auto-clamp num_processes to len(pdf_indices) inside run_pipeline_parallel |
| Output order differs from sequential | Documented; not a requirement |
| Determinism (`random` model) | Already non-deterministic; OK |
| Memory (2 processes × ~200MB = ~400MB) | OK for workloads < 50 PDFs (fits 16GB VM) |
| Python GIL | Doesn't matter (I/O bound) |
| Pickling errors in `ProcessPoolExecutor` | All in top-level functions; use `if __name__ == '__main__':` |

## 11. Effort Estimate

| Item | Est. |
|---|---|
| `parallel.py` new | ~200-250 LOC |
| `main.py` modifications | ~15-20 LOC (additive) |
| `llm_query.py` modifications | 0 LOC |
| New tests | ~100 LOC (smoke + race condition + auto-clamp) |
| Docs (readme + skill) | update at end |

Time estimate: 1 focused work session.

## 12. New Dependencies

**None for core.** `concurrent.futures` is stdlib.

`tqdm` is **NEW** for progress bar; needs to be added to `requirements.txt`. **Decision (2026-06-11):** tqdm — legibility gain is worth the dependency.

## 13. Proposed Implementation Sequence

1. `parallel.py` with `_evaluate_one_occurrence` + `SharedAccumulator`
2. `run_with_concurrency_limit` generic
3. `analyze_occurrences_parallel`
4. `process_single_pdf_v2`
5. `_worker_process_entry` + `run_pipeline_parallel` (with auto-clamp logic)
6. Flags in `main.py` + routing
7. tqdm + log_level
8. Smoke test 1 PDF (NIST.SP.800-207) with `--parallel` — target ≤ 3 min, cost delta < 5%
9. Test 6 PDFs with `--profile` — both `--parallel` (C=2) and `--parallel --num-processes 1` (C=1) for comparison
10. Update readme + skill `pdfanalyzer` + commit

## 14. Resolved Decisions

Approved by user on 2026-06-11:

- **(a) Default `--max-workers`: 5** (5 concurrent LLM calls per process)
- **(b) Default `--num-processes`: 2** (2 processes → 10 concurrent total; auto-clamps to 1 process when there's only 1 PDF)
- **(c) Add `tqdm` to `requirements.txt`** (progress bar, worth the new dep)
- **(d) Save spec in Obsidian** (done — `TOOLS-001-paralelizacao-pdfanalyzer.md` + Dashboard updated)

---

**Next step:** implement per §13 sequence. No code changes will be made outside that sequence. First action: create `PDFAnalyzer/parallel.py` with `_evaluate_one_occurrence` and `SharedAccumulator`, without touching any function listed in §2 OUT.
