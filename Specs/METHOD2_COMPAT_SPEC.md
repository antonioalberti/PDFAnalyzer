# PDFAnalyzer — Method 2 (full_pdf_analyzer.py) Compatibility Spec v1.0

> **Status:** Draft v1.0 — pending user approval.
> **Date:** 2026-06-19
> **Scope:** `full_pdf_analyzer.py` (Method 2) alignment with STATISTICS_SPEC v1.3 and MULTIPROVIDER_SPEC v1.2 for fair, scientific cross-method and cross-provider comparison.
> **Codebase:** PDFAnalyzer repo (public), main branch
> **Python:** 3.12.3 | **OS:** Linux (VM 100, 192.168.0.178)

---

## 1. Goal

Make `full_pdf_analyzer.py` produce output that is **structurally and semantically comparable** with Method 1 (`main.py`) runs, so that a future external comparison tool can:

1. Compare Method 1 vs Method 2 results (same PDF, same provider, same model).
2. Compare local vs OpenRouter results (same method, same PDF).
3. Compute variance and reproducibility metrics from multiple runs.

Currently `full_pdf_analyzer.py` has several gaps that break fair comparison:

| Gap | Impact on Comparison |
|-----|---------------------|
| **G1: Hardcoded model** (`google/gemini-2.5-pro`) — no `--model` flag | Cannot run Method 2 with the same model as Method 1; local provider always fails (model not in `local_models.txt`) |
| **G2: No `--temperature` / `--top-p` CLI flags** | Cannot control sampling; stats JSON always shows 1.0/1.0 with no way to vary for experiments |
| **G3: ThreadPoolExecutor fixed at max_workers=3** | No control over concurrency; with local provider, 3 concurrent requests to llama-server cause queuing and inflated latency |
| **G4: `analyze()` called without sampling params** | `self.llm_analyzer.analyze({}, prompt, model_name=...)` — the `analyze` method uses the LLMAnalyzer's stored temperature/top_p, but the model is not validated against the active provider's models file |
| **G5: Per-PDF cost/token/summary files missing** | Method 2 writes only a single `2_full_text_analysis_cost.txt` and `2_full_text_analysis_summary.json` for all PDFs combined; Method 1 writes per-PDF files. A comparison tool cannot match PDFs across methods. |
| **G6: No provider-model validation** | `--provider local` with hardcoded `google/gemini-2.5-pro` will fail at call time (model not served by llama-server), not at startup |
| **G7: `--output` flag is unused** | R7 already creates a timestamped Results dir; the `--output` flag is accepted but ignored. Misleading. |

---

## 2. Current State (Baseline)

| Aspect | Current `full_pdf_analyzer.py` | Method 1 (`main.py`) |
|--------|-------------------------------|---------------------|
| **Model** | Hardcoded `google/gemini-2.5-pro` | `--model` flag or random from models file |
| **Temperature** | Constructor param (default 1.0), no CLI flag | `--temperature` CLI flag |
| **Top-p** | Constructor param (default 1.0), no CLI flag | `--top-p` CLI flag |
| **Provider** | `--provider` / `--local-url` (added E9) | `--provider` / `--local-url` (added E8) |
| **Concurrency** | ThreadPoolExecutor(max_workers=3) hardcoded | `--max-workers` / `--num-processes` |
| **Output dir** | R7 timestamped dir (correct), `--output` ignored | R7 timestamped dir |
| **Cost file** | Single `2_full_text_analysis_cost.txt` | Per-PDF `*_cost.txt` |
| **Summary JSON** | Single `2_full_text_analysis_summary.json` | Per-PDF `*_summary.json` |
| **Per-PDF stats** | Not tracked | Per-PDF latency, tokens, cost |
| **Provider validation** | None | `--provider local --model <remote_model>` should fail at startup |

---

## 3. Architecture

### 3.1 CLI Flags

Add 3 new flags to bring parity with Method 1:

```
--model MODEL            Model name or 'random' (default: random). Must exist in active provider's models file.
--temperature TEMP       Sampling temperature (default: 1.0). Reasoning models only support 1.0.
--top-p P                Top-p (nucleus sampling) (default: 1.0). Reasoning models only support 1.0.
```

Remove the misleading `--output` flag (R7 already handles the output directory).

Updated CLI:

```
python full_pdf_analyzer.py --source <dir> --keywords <json> --provider local --model Qwen3-4B-Instruct-IQ3_XS.gguf --temperature 0.7
```

### 3.2 Model Selection

Replace the hardcoded `self.model_name = "google/gemini-2.5-pro"` with:

```python
self.model_name = model_name  # from --model flag or "random"
```

When `model_name == "random"`, use `self.llm_analyzer.get_random_model()` at call time.

### 3.3 Provider-Model Validation

At startup, after creating the `LLMAnalyzer`, validate that the requested model exists in the active provider's models file:

```python
if model_name != "random" and model_name not in self.llm_analyzer.models:
    print(Fore.RED + f"Error: Model '{model_name}' not found in {self.llm_analyzer.active_provider.models_file}" + Style.RESET_ALL)
    sys.exit(2)
```

This prevents the common mistake: `--provider local` without `--model`, which would try to call `google/gemini-2.5-pro` on the local server and fail mid-run.

### 3.4 Concurrency Control

Replace the hardcoded `ThreadPoolExecutor(max_workers=3)` with a configurable `--max-workers` flag:

```python
parser.add_argument("--max-workers", type=int, default=3, help="Max concurrent category threads (default: 3).")
```

Pass to `ThreadPoolExecutor(max_workers=args.max_workers)`.

**Recommendation for local provider:** `--max-workers 1` (sequential) to avoid queuing on the single llama-server instance.

### 3.5 Per-PDF Statistics

Currently Method 2 processes all PDFs through a single `LLMAnalyzer` instance, so `call_records` accumulate across PDFs. The single cost file and summary JSON reflect totals.

For fair comparison with Method 1 (which produces per-PDF files), add **per-PDF cost and summary files**:

For each PDF processed:
1. Record the number of API calls before and after processing that PDF.
2. Write `<pdf_stem>_2_cost.txt` with the delta statistics for that PDF.
3. Write `<pdf_stem>_2_summary.json` with per-PDF structured metrics.

The existing aggregate files (`2_full_text_analysis_cost.txt`, `2_full_text_analysis_summary.json`) are **kept** — they reflect the entire run.

**Per-PDF cost file** uses the same `print_usage_summary` but with a slice of `call_records` for that PDF only. Implementation:

```python
# Before processing PDF:
start_idx = len(self.llm_analyzer.call_records)

# After processing PDF:
end_idx = len(self.llm_analyzer.call_records)
pdf_records = self.llm_analyzer.call_records[start_idx:end_idx]

# Write per-PDF cost file using a temporary view
pdf_cost_file = self._run_dir / f"{pdf_path.stem}_2_cost.txt"
self.llm_analyzer.print_usage_summary(str(pdf_cost_file), records=pdf_records)
```

This requires extending `print_usage_summary` and `write_summary_json` to accept an optional `records` parameter (default: `self.call_records`). The change is in `llm_query.py` and is backwards compatible.

### 3.6 Remove `--output` Flag

The `--output` flag is misleading because R7 already creates `<source>/Results/<timestamp>/`. Remove it from the argparse and constructor.

### 3.7 Constructor Signature

```python
class FullPDFAnalyzer:
    def __init__(self, source_folder: str, keywords_path: str,
                 temperature: float = 1.0, top_p: float = 1.0,
                 provider: str = "openrouter", local_url: str | None = None,
                 model_name: str = "random", max_workers: int = 3):
        ...
        self.model_name = model_name
        self.max_workers = max_workers
        self.llm_analyzer = LLMAnalyzer(temperature=temperature, top_p=top_p,
                                         provider=provider, local_base_url=local_url)
        # Validate model
        if model_name != "random" and model_name not in self.llm_analyzer.models:
            raise SystemExit(f"Error: Model '{model_name}' not found in {self.llm_analyzer.active_provider.models_file}")
```

### 3.8 Summary JSON Schema Alignment

The per-PDF summary JSON from Method 2 must have the same schema as Method 1's `*_summary.json`:

```json
{
  "run_id": "2026-06-19_10-30-00",
  "provider": "local",
  "pdf_file": "NIST.SP.500-292.pdf",
  "method": "full_text",
  "model_requested": "Qwen3-4B-Instruct-IQ3_XS.gguf",
  "temperature": 0.7,
  "top_p": 1.0,
  "total_api_calls": 9,
  "total_prompt_tokens": 45678,
  "total_completion_tokens": 1234,
  "total_cost_usd": 0.0,
  "cost_source": "local",
  "latency": { ... },
  "categories_found": 9,
  "category_notes": { "Cloud Computing": 7.5, "Microservices": 4.0, ... }
}
```

The `"method": "full_text"` field distinguishes Method 2 from Method 1 in cross-method comparison. The `"category_notes"` field captures the per-category evaluation scores (unique to Method 2).

The aggregate summary JSON (`2_full_text_analysis_summary.json`) also gets the `"method"` field.

---

## 4. Implementation Order (incremental, "test 1 by 1")

- [ ] **M1 — Add `--model` flag + remove hardcoded model**: Add argparse `--model` with default `"random"`. Replace `self.model_name = "google/gemini-2.5-pro"` with `self.model_name = model_name`. When `"random"`, call `self.llm_analyzer.get_random_model()` at each `analyze_category` call. **Test:** `python full_pdf_analyzer.py --help` shows `--model`. `--provider local --model Qwen3-4B-Instruct-IQ3_XS.gguf` creates LLMAnalyzer with correct model.

- [ ] **M2 — Add `--temperature` and `--top-p` flags**: Add argparse flags. Thread to constructor. **Test:** `--help` shows flags. `--temperature 0.5` is reflected in summary JSON.

- [ ] **M3 — Add `--max-workers` flag**: Add argparse flag. Replace hardcoded `ThreadPoolExecutor(max_workers=3)`. **Test:** `--max-workers 1` processes categories sequentially (no ThreadPoolExecutor overhead visible in timing).

- [ ] **M4 — Provider-model validation**: At startup, validate `model_name` against `self.llm_analyzer.models`. Exit code 2 on mismatch. **Test:** `--provider local --model google/gemini-2.5-pro` exits with error. `--provider local` (random) succeeds. `--provider local --model Qwen3-4B-Instruct-IQ3_XS.gguf` succeeds.

- [ ] **M5 — Remove `--output` flag**: Remove from argparse and constructor. Update `__main__` block. **Test:** `python full_pdf_analyzer.py --help` no longer shows `--output`.

- [ ] **M6 — Per-PDF statistics**: Extend `print_usage_summary` and `write_summary_json` in `llm_query.py` to accept optional `records` parameter. In `full_pdf_analyzer.py`, write per-PDF cost and summary files. **Test:** Run with 2+ PDFs — verify each PDF gets `<stem>_2_cost.txt` and `<stem>_2_summary.json`. Verify aggregate files still exist.

- [ ] **M7 — Summary JSON schema alignment**: Add `"method": "full_text"` and `"category_notes"` to per-PDF and aggregate summary JSONs. **Test:** Run a single PDF — verify JSON has `"method"` and `"category_notes"` fields.

- [ ] **M8 — Smoke test (local provider)**: Run `full_pdf_analyzer.py --source <dir> --keywords cloud.json --provider local --model Qwen3-4B-Instruct-IQ3_XS.gguf --max-workers 1`. Acceptance: completes, per-PDF files exist, summary JSON has `provider=local`, `method=full_text`, `cost_source=local`, `total_cost_usd=0.0`.

- [ ] **M9 — Smoke test (openrouter, backward compat)**: Run `full_pdf_analyzer.py --source <dir> --keywords cloud.json` (default provider, random model). Acceptance: same behavior as current code (minus `--output`), summary JSON has `provider=openrouter`.

- [ ] **M10 — Commit**: Update README. Commit message: `feat(method2): align full_pdf_analyzer.py with STATISTICS_SPEC and MULTIPROVIDER_SPEC for fair comparison`.

---

## 5. Acceptance Criteria

| # | Criterion | How Verified |
|---|-----------|-------------|
| A1 | `--model`, `--temperature`, `--top-p`, `--max-workers` appear in `--help` | Manual |
| A2 | `--output` no longer appears in `--help` | Manual |
| A3 | `--provider local --model Qwen3-4B-Instruct-IQ3_XS.gguf` completes successfully | Smoke test |
| A4 | `--provider local --model google/gemini-2.5-pro` exits code 2 at startup | CLI test |
| A5 | `--provider local` (random model) picks from `local_models.txt` | Run + check model in summary JSON |
| A6 | `--temperature 0.5` is reflected in summary JSON | Run + check JSON |
| A7 | `--max-workers 1` processes categories sequentially | Run + observe timing |
| A8 | Per-PDF `<stem>_2_cost.txt` files exist for each processed PDF | `ls` after run |
| A9 | Per-PDF `<stem>_2_summary.json` files exist with `method=full_text` | `ls` + JSON check |
| A10 | Aggregate `2_full_text_analysis_cost.txt` still exists | `ls` after run |
| A11 | Aggregate `2_full_text_analysis_summary.json` has `method=full_text` | JSON check |
| A12 | Per-PDF summary JSON has `category_notes` field with evaluation scores | JSON check |
| A13 | Summary JSON schema matches Method 1 (same fields: provider, cost_source, temperature, top_p, latency, etc.) | Schema diff |
| A14 | Running without `--provider` defaults to `openrouter` (backward compat) | Run + check output |
| A15 | No new dependencies | `git diff requirements.txt` empty |
| A16 | `llm_query.py` changes are backwards compatible (new `records` param has default) | Existing tests still pass |

---

## 6. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| `print_usage_summary(records=...)` breaks existing callers | Low | Default `records=None` uses `self.call_records` — existing callers unchanged |
| Removing `--output` breaks existing scripts | Low | Flag was already ignored (R7 handles output dir). No functional change. |
| Per-PDF files increase disk usage | Low | Same pattern as Method 1. Cleanup is user's responsibility. |
| Random model selection for local picks wrong model | Low | `local_models.txt` has only 1 model. If more are added, selection is random from that list — expected behavior. |
| `category_notes` in summary JSON not present in Method 1 | Low | Method 2 unique field. Comparison tool should handle missing fields gracefully. |

---

## 7. Open Questions

None.
