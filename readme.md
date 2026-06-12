# PDFAnalyzer

PDFAnalyzer is a powerful toolset designed for the automated thematic analysis of PDF documents. It leverages Large Language Models (LLMs) — via OpenRouter (online) or a local llama.cpp server — to identify, categorize, and evaluate technological enablers or any specific themes defined by the user. The tool generates standardized LaTeX tables, making it ideal for researchers and professionals who need to synthesize information from large sets of technical documents. See [Multi-Provider LLM Support](#multi-provider-llm-support) for selecting the LLM backend.

## Installation

1. **Clone the repository** and navigate to the project folder.
2. **Set up a Virtual Environment** (optional but recommended):
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # Linux/Ubuntu:
   source venv/bin/activate
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure API Key**:
   Create a `.env` file in the root directory and add your OpenRouter API key:
   ```
   ROUTER_API_KEY=your_api_key_here
   ```
   *Optional:* to use a local LLM server, also set `LOCAL_LLM_BASE_URL` (default: `http://192.168.0.200:8080/v1`). See [Multi-Provider LLM Support](#multi-provider-llm-support) below.

## Analysis Methods

The project provides two complementary methods for document analysis:

### Method 1: Granular Analysis (Snippet-based)
This method extracts specific paragraphs containing user-defined keywords and uses an LLM to evaluate the significance of each occurrence. It is highly precise and cost-effective for large document sets.
```bash
python main.py "path/to/pdfs" [start_index] [end_index] keywords.json
```
*Example:* `python main.py "./documents" 0 10 my_themes.json`

#### Parallel execution (opt-in)

Method 1 ships with a two-layer parallel pipeline (spec: [`PARALLELIZATION_SPEC.md`](./PARALLELIZATION_SPEC.md), v2.0):

- **Layer A (intra-PDF)** — `ThreadPoolExecutor` with N workers (`--max-workers`, default 5) per process, deduplicating results atomically via a `SharedAccumulator`.
- **Layer C (inter-PDF)** — `ProcessPoolExecutor` with M processes (`--num-processes`, default 2), each worker creating its own `LLMAnalyzer` to avoid fork-unsafe `httpx.Client` issues.
- **Opt-in:** no flag = the original sequential behavior is preserved exactly. Add `--parallel` to enable.

| Flag | Default | Range | Purpose |
|---|---|---|---|
| `--parallel` | (off) | — | Enable Layer A + Layer C |
| `--max-workers N` | 5 | 1–50 | Threads per process (Layer A) |
| `--num-processes M` | 2 | 1–cpu_count | Processes for batch (Layer C; auto-clamped to `len(pdfs)`) |
| `--log-level LEVEL` | normal | quiet / normal / verbose / debug | Output verbosity (`quiet` = tqdm only) |
| `--profile` | (off) | — | Print wall-clock time at the end |

*Examples:*
```bash
# Sequential (unchanged, backwards compatible)
python main.py ./papers 0 5 cloud.json

# Parallel defaults: 2 procs × 5 threads = 10 concurrent LLM calls
python main.py ./papers 0 5 cloud.json --parallel

# A-only: 1 proc × 5 threads = 5 concurrent (debugging, no fork)
python main.py ./papers 0 5 cloud.json --parallel --num-processes 1

# Quiet mode (tqdm only) with profile
python main.py ./papers 0 5 cloud.json --parallel --log-level quiet --profile
```

*To run any of the above examples with a local LLM, add `--provider local`. See [Multi-Provider LLM Support](#multi-provider-llm-support) for details.*

**Design contracts:** 429 rate-limits retry forever (zero occurrence loss); significant files are written once *after* the pool joins (no file I/O race); `load_dotenv()` is called in the main process before fork so workers inherit `ROUTER_API_KEY` and `LOCAL_LLM_BASE_URL`.

### Method 2: Full-Context Analysis
This method sends the entire text of the PDF to the LLM for a holistic evaluation of each category. It provides a cohesive summary and a qualitative score (0-10) for the document's coverage of the theme.
```bash
python full_pdf_analyzer.py --source "path/to/pdfs" --keywords keywords.json --output "path/to/output"
```

*Add `--provider local` to use a local LLM (see [Multi-Provider LLM Support](#multi-provider-llm-support)).*

## Multi-Provider LLM Support

PDFAnalyzer can route LLM calls to **OpenRouter** (online models, default) or a **local llama.cpp server** (Qwen3-4B on the ProxMox host). One provider per run — select at invocation time with `--provider`. Both methods (`main.py` and `full_pdf_analyzer.py`) and both execution modes (sequential, `--parallel`) support provider selection.

### OpenRouter (default)

No extra configuration — uses `ROUTER_API_KEY` from `.env` and models listed in `remote_models.txt`.

```bash
# Default — provider omitted
python main.py ./papers 0 5 cloud.json

# Explicit
python main.py ./papers 0 5 cloud.json --provider openrouter
```

### Local LLM (Qwen3-4B)

Routes calls to a llama.cpp server at `http://192.168.0.200:8080/v1` serving `Qwen3-4B-Instruct-IQ3_XS.gguf`. **Zero cost per call**, full data privacy, LAN latency.

**Prerequisites:**
- llama.cpp server running on the ProxMox host (192.168.0.200:8080)
- Model `Qwen3-4B-Instruct-IQ3_XS.gguf` loaded
- Port 8080 reachable from the VM

```bash
# Local provider
python main.py ./papers 0 5 cloud.json --provider local

# Override the local URL
python main.py ./papers 0 5 cloud.json --provider local --local-url http://my-host:8080/v1
```

**Optional `.env` override** (default is `http://192.168.0.200:8080/v1`):
```
LOCAL_LLM_BASE_URL=http://192.168.0.200:8080/v1
```

### CLI Flags

| Flag | Default | Options | Purpose |
|---|---|---|---|
| `--provider` | `openrouter` | `openrouter`, `local` | LLM provider to use |
| `--local-url` | env / hardcoded default | URL string | Override local LLM base URL |

### Model Lists

| Provider | File | Content |
|---|---|---|
| `openrouter` | `remote_models.txt` | OpenRouter model names (one per line) |
| `local` | `local_models.txt` | Model filenames served by llama.cpp |

The `--model` flag (or `random`) picks from the active provider's list. Cross-provider model names are rejected (e.g., `--provider local --model google/gemini-3-flash-preview` exits with code 2).

### Reporting

Both providers produce **identical report structure** (`*_cost.txt`, `*_summary.json`):
- `Provider:` line at top of `*_cost.txt`
- `provider` and `cost_source` fields in `*_summary.json`
- Local: `cost_usd=0.0`, `source="local"` for every call
- OpenRouter: existing 3-tier cost resolution unchanged

This enables fair cross-provider comparison via an external tool — both providers receive the same prompt inputs, costs are reported in the same schema.

### Local Model Limitations

The Qwen3-4B local model is **less capable** than frontier OpenRouter models (GPT-5, Gemini 3) for complex analysis. Use it when:
- Cost is the primary concern (zero per-call)
- Data privacy requires no external API calls
- You can accept lower-quality category detection

For research-grade analysis, prefer OpenRouter.

### Article Summary Removed (v1.2)

The `fetch_article_summary` step (web-search enrichment) was removed from the pipeline to ensure **fair provider comparison** — it was only available via OpenRouter, creating an asymmetric prompt. The method is preserved in `llm_query.py` for ad-hoc use but is not called by the pipeline. As a side benefit, this reduces cost by 1–6 API calls per PDF (no more C2 cost leak from STATISTICS_SPEC v1.3).

## Key Features

- **Thematic Flexibility**: Define your own categories and keywords in a simple JSON format.
- **Standardized Output**: Automatically generates LaTeX code following scientific publication standards (captions on top, wide table support, bold identifiers).
- **Multi-Model Support**: Easily switch between different LLMs (Gemini, Claude, GPT) via OpenRouter.
- **Multi-Provider LLM Support** (v1.2): Route calls to OpenRouter (default) or a local llama.cpp server (Qwen3-4B) via `--provider {openrouter,local}`. Zero cost on local; fair cross-provider comparison through identical reporting structure (`Provider:` line, `provider` + `cost_source` JSON fields). See [Multi-Provider LLM Support](#multi-provider-llm-support).
- **Cost & Token Tracking**: Detailed logging and reporting of API consumption.
- **Statistics Enhancements** (v1.3): Per-call latency tracking, sampling parameter validation (temperature/top_p with reasoning-model guard), model version detection, corrected pricing fallbacks, timestamped Results directories (`<source>/Results/<timestamp>/`), and machine-readable `<stem>_summary.json` per run — enabling automated variance analysis across repeated trials. See [`STATISTICS_SPEC.md`](./STATISTICS_SPEC.md) for the full specification.
- **Optional Parallelism**: Speed up Method 1 with `--parallel` (intra-PDF threads + inter-PDF processes) — opt-in, identical outputs to sequential, ≈1.6× speedup per PDF (1 PDF), scaling to ≈5–10× on batches of 6+ PDFs. See [`PARALLELIZATION_SPEC.md`](./PARALLELIZATION_SPEC.md) for the design.

## Requirements

- Python 3.x
- Libraries: `PyPDF2`, `pdfplumber`, `openai`, `requests`, `python-dotenv`, `colorama`, `tqdm`.
- **OpenRouter provider:** an OpenRouter API key (set `ROUTER_API_KEY` in `.env`).
- **Local provider:** a running llama.cpp server reachable at the configured URL (default `http://192.168.0.200:8080/v1`). See [Multi-Provider LLM Support](#multi-provider-llm-support).

## Contact

For questions or suggestions, please contact the developer.