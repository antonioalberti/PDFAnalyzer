"""Parallelization layer for PDFAnalyzer Method 1 occurrence filtering.

This module implements the intra-PDF (A) and inter-PDF (C) layers described
in ``PARALLELIZATION_SPEC.md`` v2.0. The full pipeline is split into
``_evaluate_one_occurrence`` (single LLM call with 429 retry), the
``SharedAccumulator`` (thread-safe result collection), the
``analyze_occurrences_parallel`` coordinator (per-category thread pool +
post-pool file writes), and the multi-PDF driver filled in by later steps.

Design contracts (do not change without spec update):
    * ``_evaluate_one_occurrence`` mirrors the prompt construction used by
      ``main.analyze_occurrences`` and reuses its ``extract_extended_context``
      via lazy import to keep outputs identical to the sequential path.
    * ``SharedAccumulator.record_significant`` is the only place that mutates
      the result set. The lock covers the dedup check + set add + list append
      so no occurrence can be lost or duplicated under thread contention.
    * The accumulator owns NO file handles. Significant files are written
      once at the end of the per-category pool by ``analyze_occurrences_parallel``
      (this module).
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from colorama import Fore, Style
from openai import RateLimitError
from tqdm import tqdm

if TYPE_CHECKING:
    # Only needed for type-checking of SignificantFileMap values; imported
    # lazily to avoid forcing the path dependency on every load.
    pass

# -- retry policy for OpenRouter 429s -----------------------------------------
# The rate limit always clears, so we retry indefinitely. Non-429 errors are
# treated like the sequential code (skip the occurrence) because they reflect
# a genuine failure unrelated to parallelism.
_BACKOFF_INITIAL = 1.0  # seconds
_BACKOFF_CAP = 30.0     # seconds (max wait between retries)


# -- public type aliases (mirrored from main.py) ------------------------------
Occurrence = Tuple[int, str, str, int]              # (page, keyword, paragraph, abs_start)
FilteredOccurrence = Tuple[int, str, str]           # (page, keyword, paragraph)
OccurrencesByEnabler = Dict[str, List[Occurrence]]
FilteredOccurrencesByEnabler = Dict[str, List[FilteredOccurrence]]
SignificantFileMap = Dict[str, Path]               # enabler -> significant file path
ParallelLLM = object                                # duck-typed: needs .analyze_single_occurrence


# ---------------------------------------------------------------------------
# Step 1.1 — single-occurrence worker (with infinite 429 retry)
# ---------------------------------------------------------------------------

def _evaluate_one_occurrence(
    llm_analyzer,
    enabler: str,
    page_num: int,
    keyword: str,
    paragraph: str,
    pdf_text: str,
    abs_start: int,
    prompt_template: str,
    model_name,
) -> FilteredOccurrence | None:
    """Call the LLM to decide whether one keyword occurrence is significant.

    Returns ``(page_num, keyword, paragraph)`` if the LLM answer (case
    insensitive, stripped) equals ``"significant"``, else ``None``.

    Retry policy:
        * ``openai.RateLimitError`` (HTTP 429): exponential backoff
          1s → 2s → 4s → 8s → 16s → 30s cap, retried indefinitely. We do
          NOT skip the occurrence because the rate limit always clears
          and we want zero loss from parallelization.
        * Any other exception: logged at debug and the occurrence is
          skipped, matching the sequential path's behavior.
    """
    # Lazy import: ``main`` imports ``parallel`` for the routing block added
    # in Etapa 5, so a top-level ``from main import …`` would create a
    # circular import. By the time this function runs both modules are
    # fully loaded.
    from main import extract_extended_context

    extended_context = extract_extended_context(
        pdf_text, abs_start, abs_start + len(keyword)
    )
    prompt_text = (
        f"{prompt_template}\n\n"
        f"Enabler: {enabler}\n"
        f"Keyword: {keyword}\n"
        f"Context:\n{extended_context}"
    )

    backoff = _BACKOFF_INITIAL
    while True:
        try:
            response = llm_analyzer.analyze_single_occurrence(
                prompt_text, model_name
            )
            if response and response.strip().lower() == "significant":
                return (page_num, keyword, paragraph)
            return None
        except RateLimitError:
            logging.debug(
                "429 rate limit for keyword=%r page=%d; sleeping %.1fs",
                keyword, page_num, backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2.0, _BACKOFF_CAP)
        except Exception as exc:  # pragma: no cover - defensive
            logging.debug(
                "LLM call failed (non-429) for keyword=%r page=%d: %s",
                keyword, page_num, exc,
            )
            return None


# ---------------------------------------------------------------------------
# Step 1.2 — thread-safe result accumulator
# ---------------------------------------------------------------------------

class SharedAccumulator:
    """Thread-safe collector for parallel occurrence evaluation.

    Three maps are kept consistent under a single lock so the dedup check
    and the append cannot race:

        * ``filtered`` — what ``analyze_occurrences`` returns, mapping
          ``enabler -> [(page, keyword, paragraph), …]``.
        * ``seen_paragraphs`` — per-enabler set of stripped paragraph
          strings already accepted (mirrors the dedup at main.py L186-188).
        * ``sig_paragraphs_by_enabler`` — per-enabler list of accepted
          paragraph bodies in arrival order, used to write the
          ``*_significant_paragraphs_category_*.txt`` files at the end of
          the pool (avoids a file-write race; see spec §5).

    The lock is the only synchronization primitive used here. ``record_*``
    and the snapshot are O(1) amortized. No file I/O happens in this class.
    """

    def __init__(self, enablers) -> None:
        # Pre-populate empty containers so callers never need to handle a
        # missing key for an enabler with zero matches.
        self._filtered: FilteredOccurrencesByEnabler = {
            enabler: [] for enabler in enablers
        }
        self._seen: Dict[str, Set[str]] = {
            enabler: set() for enabler in enablers
        }
        self._sig_paragraphs: Dict[str, List[str]] = {
            enabler: [] for enabler in enablers
        }
        self._lock = threading.Lock()

    # -- mutation -----------------------------------------------------------

    def record_significant(
        self,
        enabler: str,
        page_num: int,
        keyword: str,
        paragraph: str,
    ) -> bool:
        """Record one significant occurrence if its paragraph is new.

        Returns ``True`` if the occurrence was recorded, ``False`` if it
        was rejected as a duplicate of a paragraph already in the file
        for this enabler. The check + add + append is atomic.
        """
        normalized = paragraph.strip()
        with self._lock:
            if normalized in self._seen[enabler]:
                return False
            self._seen[enabler].add(normalized)
            self._filtered[enabler].append((page_num, keyword, paragraph))
            self._sig_paragraphs[enabler].append(paragraph)
            return True

    def record_skipped(self, enabler: str) -> None:
        """Reserve a slot for a non-significant occurrence.

        Currently a no-op kept for future accounting (e.g., per-enabler
        "considered / significant" counters used by the verbose log
        level). Kept on the class to keep the call sites symmetric.
        """
        del enabler  # unused — reserved for future use

    # -- read access --------------------------------------------------------

    def snapshot_filtered(self) -> FilteredOccurrencesByEnabler:
        """Return a shallow copy of the filtered map (main.py return shape)."""
        with self._lock:
            return {enabler: list(items) for enabler, items in self._filtered.items()}

    def snapshot_significant_paragraphs(self) -> Dict[str, List[str]]:
        """Return a shallow copy of the per-enabler paragraph lists.

        Used by ``analyze_occurrences_parallel`` to write the significant
        files at the end of the pool, after all threads have joined.
        """
        with self._lock:
            return {enabler: list(items) for enabler, items in self._sig_paragraphs.items()}

    # -- diagnostics --------------------------------------------------------

    def counts(self) -> Dict[str, int]:
        """Return per-enabler counts of significant occurrences (for tests)."""
        with self._lock:
            return {enabler: len(items) for enabler, items in self._filtered.items()}


# ---------------------------------------------------------------------------
# Step 2 — per-category thread pool + post-pool file write
# ---------------------------------------------------------------------------

def analyze_occurrences_parallel(
    pdf_text: str,
    enabler_occurrences: OccurrencesByEnabler,
    prompt_template: str,
    llm_analyzer: ParallelLLM,
    model_name,
    max_workers: int,
    total_occurrences: Optional[int] = None,
    significant_files: Optional[SignificantFileMap] = None,
    pdf_stem: Optional[str] = None,
    log_level: str = "normal",
) -> FilteredOccurrencesByEnabler:
    """Same contract as ``main.analyze_occurrences`` but parallelized.

    Per enabler category a fresh :class:`ThreadPoolExecutor` is opened with
    ``max_workers`` threads. Each occurrence is submitted to
    ``_evaluate_one_occurrence`` and the result is funneled into a
    :class:`SharedAccumulator` that deduplicates paragraphs atomically.

    A ``tqdm`` progress bar advances per category (PARALLELIZATION_SPEC
    v2.0 — Etapa 6). It is disabled when ``log_level == "quiet"`` so that
    mode produces no per-occurrence output at all.

    File I/O is deliberately deferred until *after* all threads in all
    categories have joined: we delete the old significant files and then
    write the new ones from the accumulator's snapshot, single-threaded.
    This avoids the file-write race that would occur if threads appended
    concurrently to the same file (see spec §5 / §11 risk
    "Significant file write race").

    The function returns the same shape as ``analyze_occurrences``:
    ``{enabler: [(page, keyword, paragraph), …]}`` with paragraphs
    deduplicated.
    """
    accumulator = SharedAccumulator(enabler_occurrences.keys())
    show_progress = log_level != "quiet"

    for category_index, (enabler, occurrences) in enumerate(
        enabler_occurrences.items(), start=1
    ):
        if not occurrences:
            continue

        prefix = (
            f"{pdf_stem} cat{category_index}"
            if pdf_stem
            else f"cat{category_index}"
        )
        # Fresh pool per category: keeps memory bounded and matches the
        # sequential category-by-category structure of the original code.
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        ) as executor:
            future_to_occ = {
                executor.submit(
                    _evaluate_one_occurrence,
                    llm_analyzer,
                    enabler,
                    page_num,
                    keyword,
                    paragraph,
                    pdf_text,
                    abs_start,
                    prompt_template,
                    model_name,
                ): (page_num, keyword, paragraph)
                for (page_num, keyword, paragraph, abs_start) in occurrences
            }

            # ``as_completed`` lets the function also surface non-significant
            # (None) results without forcing every future to be awaited
            # before any thread can finish — keeps tail latency low when
            # 429s are hitting only some threads. The tqdm bar advances
            # once per completed future so the user sees per-occurrence
            # progress in real time.
            futures_iter = concurrent.futures.as_completed(future_to_occ)
            if show_progress:
                futures_iter = tqdm(
                    futures_iter,
                    total=len(future_to_occ),
                    desc=prefix,
                    unit="occ",
                )
            for fut in futures_iter:
                # _occ not used; kept for future verbose logging
                _occ = future_to_occ[fut]
                try:
                    result = fut.result()
                except Exception as exc:  # pragma: no cover - defensive
                    logging.debug(
                        "Worker raised in analyze_occurrences_parallel: %s",
                        exc,
                    )
                    continue
                if result is not None:
                    page_num, keyword, paragraph = result
                    accumulator.record_significant(
                        enabler, page_num, keyword, paragraph
                    )

        if log_level == "verbose":
            print(
                Fore.CYAN
                + f"  [{prefix}] {accumulator.counts().get(enabler, 0)}/{len(occurrences)} significant"
                + Style.RESET_ALL
            )

    # All threads have joined across all categories. Snapshot the
    # accumulator, then delete + write significant files in the calling
    # thread (no I/O race).
    filtered = accumulator.snapshot_filtered()

    if significant_files:
        # 1) Delete old files
        for enabler, file_path in significant_files.items():
            try:
                if file_path.exists():
                    file_path.unlink()
            except OSError as exc:  # pragma: no cover - defensive
                logging.warning(
                    "Failed to delete old significant file %s: %s",
                    file_path, exc,
                )

        # 2) Write new files from the accumulator (single-threaded)
        sig_paragraphs = accumulator.snapshot_significant_paragraphs()
        for enabler, paragraphs in sig_paragraphs.items():
            if not paragraphs:
                continue
            file_path = significant_files.get(enabler)
            if file_path is None:
                continue
            try:
                with file_path.open("w", encoding="utf-8") as handle:
                    for paragraph in paragraphs:
                        handle.write(paragraph)
                        handle.write("\n\n")
            except OSError as exc:  # pragma: no cover - defensive
                logging.warning(
                    "Failed to write significant file %s: %s",
                    file_path, exc,
                )

    return filtered


# ---------------------------------------------------------------------------
# Step 3 — per-PDF worker (mirrors main.process_single_pdf, parallelized)
# ---------------------------------------------------------------------------

def process_single_pdf_v2(
    file_path,
    keywords_path,
    max_workers: int = 5,
    min_representative_matches: int = 1,
    model_name = "random",
    log_level: str = "normal",
) -> None:
    """Process a single PDF using the parallel occurrence filter.

    Behaviorally identical to :func:`main.process_single_pdf` except that
    the occurrence-significance step runs through
    :func:`analyze_occurrences_parallel` with ``max_workers`` threads.

    All side effects (significant files, cost file, category results, notes,
    occurrences summary) match the sequential path:
        * ``<pdf_stem>_significant_paragraphs_category_<i>.txt`` — written
          by ``analyze_occurrences_parallel`` *after* the pool joins.
        * ``<pdf_stem>_cost.txt`` — written by ``print_usage_summary``.
        * ``<pdf_stem>_all_category_results.txt`` — written here.
        * ``<pdf_stem>_all_category_notes.txt`` — written here.
        * ``<pdf_stem>_occurrences.txt`` — written by
          ``write_occurrences_summary``.
        * ``<pdf_stem>_article_summary.txt`` — written here.
        * LaTeX notes table — best-effort; silently no-ops if the optional
          module is missing (same as the sequential path).

    Early-return paths mirror the original at L420-430 and L443-449:
        1. No significant occurrences anywhere → write summary, return.
        2. Total significant < ``min_representative_matches`` → write
           summary, return.
    """
    # Lazy import everything main-side that we touch. ``process_single_pdf``
    # in main is the canonical reference; importing only what we need keeps
    # the circular main↔parallel dependency one-directional.
    from main import (
        Counter,
        Fore,
        KeywordSearcher,
        LLMAnalyzer,
        Style,
        extract_article_title_from_filename,
        load_enabler_keywords,
        read_pdf,
        write_occurrences_summary,
    )
    from dotenv import load_dotenv
    from pathlib import Path as _Path

    pdf_path = _Path(file_path)
    keywords_file_path = _Path(keywords_path)

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if not keywords_file_path.is_file():
        raise FileNotFoundError(f"Keywords file not found: {keywords_file_path}")

    # ``load_dotenv`` is idempotent and cheap. Etapa 4 also requires the
    # main process to call it before forking; calling here too is harmless
    # and makes ``process_single_pdf_v2`` correct even when used standalone
    # (e.g., in Etapa 7's smoke test where it's called from the calling
    # process and the per-PDF workers do not exist).
    load_dotenv()
    effective_model = None if model_name == "random" else model_name

    print(Fore.CYAN + f"Reading PDF file: {pdf_path}" + Style.RESET_ALL)
    pdf_text = read_pdf(pdf_path)
    print(
        Fore.BLUE
        + "\n\n\n-------------> PDF text extraction completed!!\n\n"
        + Style.RESET_ALL
    )

    print(Fore.CYAN + f"Loading keywords from: {keywords_file_path}" + Style.RESET_ALL)
    enabler_keywords = load_enabler_keywords(keywords_file_path)
    print(Fore.GREEN + f"Loaded {len(enabler_keywords)} enabler categories." + Style.RESET_ALL)

    keyword_searcher = KeywordSearcher(enabler_keywords)
    print(
        Fore.BLUE
        + "\n\n -> Searching for keyword occurrences in PDF text..."
        + Style.RESET_ALL
    )
    enabler_occurrences = keyword_searcher.check_enabler_occurrences(pdf_text)
    total_occurrences = sum(len(occ) for occ in enabler_occurrences.values())
    print(
        Fore.GREEN
        + f"Total keyword occurrences found: {total_occurrences}\n\n"
        + Style.RESET_ALL
    )

    llm_analyzer = LLMAnalyzer()
    # PARALLELIZATION_SPEC v2.0 — Etapa 6 (print suppression):
    # In parallel mode the per-call ``[Cost]`` and ``Selected model:``
    # prints would interleave across threads and processes. Route them
    # to ``logging.debug`` instead. ``--log-level debug`` still works
    # because the log handler can write the same lines to a file.
    llm_analyzer.quiet = True
    keyword_occurrence_prompt = llm_analyzer.load_prompt(
        "keyword_occurrence_prompt.txt"
    )

    # Build the per-enabler file map. The actual delete-and-write is owned
    # by ``analyze_occurrences_parallel`` (single-threaded, after the pool
    # joins — see spec §5 and Etapa-2 implementation).
    significant_files: SignificantFileMap = {}
    for index, enabler in enumerate(enabler_occurrences.keys(), start=1):
        significant_files[enabler] = (
            pdf_path.parent
            / f"{pdf_path.stem}_significant_paragraphs_category_{index}.txt"
        )

    filtered_enabler_occurrences = analyze_occurrences_parallel(
        pdf_text=pdf_text,
        enabler_occurrences=enabler_occurrences,
        prompt_template=keyword_occurrence_prompt,
        llm_analyzer=llm_analyzer,
        model_name=effective_model,
        max_workers=max_workers,
        total_occurrences=total_occurrences,
        significant_files=significant_files,
        pdf_stem=pdf_path.stem,
        log_level=log_level,
    )

    # Mirror main.print_occurrences to keep the screen output consistent.
    from main import print_occurrences  # lazy
    total_matches_summary = print_occurrences(filtered_enabler_occurrences)

    # -- Early return 1: no significant occurrences at all --
    if not any(filtered_enabler_occurrences.values()):
        print(
            Fore.RED
            + "None relevant occurrences have been found in the file under analysis."
            + Style.RESET_ALL
        )
        write_occurrences_summary(
            pdf_path, enabler_keywords, enabler_occurrences,
            filtered_enabler_occurrences, {},
        )
        return

    classified_keywords = keyword_searcher.classify_keywords(
        filtered_enabler_occurrences
    )

    print(Fore.CYAN + "Keyword Counts:" + Style.RESET_ALL)
    for category_index, (enabler, keyword_counter) in enumerate(
        classified_keywords.items(), start=1
    ):
        if keyword_counter:
            print(
                Fore.YELLOW
                + f"Category {category_index}: {enabler}:"
                + Style.RESET_ALL
            )
            for keyword, count in keyword_counter.items():
                print(
                    Fore.GREEN
                    + f"  Keyword: {keyword}, Count: {count}"
                    + Style.RESET_ALL
                )
            print()
    print(
        Fore.GREEN
        + f"Total Matches for All Families: {total_matches_summary}"
        + Style.RESET_ALL
    )

    # -- Early return 2: total significant below the representativeness floor --
    if total_matches_summary < min_representative_matches:
        print(
            Fore.RED
            + "Small number of total matches... Unrepresentative source"
            + Style.RESET_ALL
        )
        write_occurrences_summary(
            pdf_path, enabler_keywords, enabler_occurrences,
            filtered_enabler_occurrences, classified_keywords,
        )
        return

    # Fetch article summary from the internet using the PDF filename as the title
    article_title = extract_article_title_from_filename(pdf_path)
    print(
        Fore.CYAN
        + "\n\n-------------> Fetching article summary from internet..."
        + Style.RESET_ALL
    )
    article_summary = llm_analyzer.fetch_article_summary(
        article_title, effective_model
    )

    if article_summary:
        print(Fore.GREEN + "Article summary obtained successfully." + Style.RESET_ALL)
        summary_file = (
            pdf_path.parent / f"{pdf_path.stem}_article_summary.txt"
        )
        summary_content = f"{article_title}\n\n{article_summary}"
        summary_file.write_text(summary_content, encoding="utf-8")
        print(
            Fore.GREEN
            + f"Saved article summary to {summary_file}"
            + Style.RESET_ALL
        )
    else:
        print(
            Fore.YELLOW
            + "Could not obtain article summary. Proceeding without it."
            + Style.RESET_ALL
        )

    final_prompt_template = llm_analyzer.load_prompt("final_prompt.txt")

    # Collect all category results into a single file (inline L466-518 from
    # main.process_single_pdf).
    all_results = []

    for category_index, enabler in enumerate(
        filtered_enabler_occurrences.keys(), start=1
    ):
        occurrences = filtered_enabler_occurrences[enabler]
        if not occurrences:
            continue

        print(
            Fore.CYAN
            + f"\n\n-------------> Processing category {category_index}: {enabler}"
            + Style.RESET_ALL
        )

        article_summary_section = ""
        if article_summary:
            article_summary_section = (
                f"ARTICLE SUMMARY (from internet search):\n{article_summary}\n\n"
            )

        enablers_and_keywords_str = (
            f"{enabler}:\n{', '.join(enabler_keywords[enabler])}\n\n"
        )

        keyword_counts_lines = [f"{enabler}:"]
        for keyword, count in classified_keywords.get(
            enabler, Counter()
        ).items():
            keyword_counts_lines.append(f"  {keyword}: {count}")
        keyword_counts_str = "\n".join(keyword_counts_lines) + "\n\n"

        category_paragraphs = [paragraph for _, _, paragraph in occurrences]
        significant_paragraphs_str = "\n\n".join(category_paragraphs)

        final_prompt = final_prompt_template.replace(
            "{enablers_and_keywords}", enablers_and_keywords_str
        )
        final_prompt = final_prompt.replace(
            "{keyword_counts}", keyword_counts_str
        )
        final_prompt_with_paragraphs = final_prompt.replace(
            "{significant_paragraphs}", significant_paragraphs_str
        )

        if article_summary_section:
            final_prompt_with_paragraphs = (
                article_summary_section + final_prompt_with_paragraphs
            )

        # Get the model used
        selected_model = (
            effective_model
            if effective_model
            else llm_analyzer.get_random_model()
        )

        # Call LLM and collect output
        analysis = llm_analyzer.analyze(
            {}, final_prompt_with_paragraphs, None, selected_model
        )

        category_output = (
            f"-------------> Processing category {category_index}: {enabler}\n"
            f"Selected model: {selected_model}\n\n"
            f"LLM response:\n{analysis}\n"
        )
        all_results.append(category_output)

        print(
            Fore.GREEN
            + f"Category {category_index}: {enabler} analysis completed."
            + Style.RESET_ALL
        )

    # Save all results to a single file
    if all_results:
        combined_results_file = (
            pdf_path.parent / f"{pdf_path.stem}_all_category_results.txt"
        )
        combined_results_file.write_text(
            "\n\n".join(all_results), encoding="utf-8"
        )
        print(
            Fore.GREEN
            + f"\nSaved all category results to {combined_results_file}"
            + Style.RESET_ALL
        )

        # Extract notes and save to separate file
        notes_lines = []
        for result in all_results:
            lines = result.split("\n")
            for i, line in enumerate(lines):
                if line.strip().startswith("NOTE:"):
                    for l in lines:
                        if l.startswith("-------------> Processing category"):
                            cat_info = l.replace(
                                "-------------> Processing category ", ""
                            ).strip()
                            notes_lines.append(f"{cat_info}: {line.strip()}")
                            break
                    break

        if notes_lines:
            notes_file = (
                pdf_path.parent / f"{pdf_path.stem}_all_category_notes.txt"
            )
            notes_file.write_text("\n".join(notes_lines), encoding="utf-8")
            print(
                Fore.GREEN
                + f"Saved category notes to {notes_file}"
                + Style.RESET_ALL
            )

    # Write occurrences summary
    write_occurrences_summary(
        pdf_path, enabler_keywords, enabler_occurrences,
        filtered_enabler_occurrences, classified_keywords,
    )

    # Print token usage summary and save to file. ``print_usage_summary``
    # is a method on the LLMAnalyzer instance, not a free function in main.
    cost_file = pdf_path.parent / f"{pdf_path.stem}_cost.txt"
    llm_analyzer.print_usage_summary(str(cost_file))

    # Best-effort LaTeX table generation (no-op if generate_notes_table
    # is missing — same as main.process_single_pdf).
    try:
        from generate_notes_table import generate_latex_table
        generate_latex_table(str(pdf_path.parent), str(keywords_file_path))
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Step 4 — multi-PDF coordinator (ProcessPoolExecutor driver)
# ---------------------------------------------------------------------------

# Cost-file regex (matches the layout written by LLMAnalyzer.print_usage_summary,
# the same parser used by full_pdf_analyzer.generate_cost_table L131-132).
_COST_CALLS_RE = re.compile(r"Total API calls:\s+([\d,]+)")
_COST_DOLLARS_RE = re.compile(r"Total cost:\s+\$?([\d.]+)")


def _parse_cost_file(path: Path) -> tuple[int, float]:
    """Return (total_calls, total_cost_usd) parsed from a ``*_cost.txt``.

    Returns ``(0, 0.0)`` if the file is missing or unparseable — the
    aggregate summary is best-effort and should never break a run.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return (0, 0.0)
    calls_match = _COST_CALLS_RE.search(text)
    cost_match = _COST_DOLLARS_RE.search(text)
    if not (calls_match and cost_match):
        return (0, 0.0)
    try:
        calls = int(calls_match.group(1).replace(",", ""))
        cost = float(cost_match.group(1))
    except ValueError:
        return (0, 0.0)
    return (calls, cost)


def _worker_process_entry(
    pdf_path,
    keywords_path,
    max_workers: int,
    min_representative_matches: int,
    model_name,
    log_level: str,
) -> str:
    """Top-level picklable worker used by ``ProcessPoolExecutor``.

    Must be a module-level function (picklable on the default ``fork``
    start method) and must create its own ``LLMAnalyzer`` inside — see
    spec §3 / §9 "each worker process must create its own LLMAnalyzer"
    because ``httpx.Client`` is not fork-safe.

    The function intentionally returns just the PDF path string so the
    coordinator can map results back without sharing LLMAnalyzer state.
    """
    # Each worker re-reads .env — fork would already have inherited the
    # variables, but reading again is idempotent and makes the function
    # safe under ``spawn`` start method too (spec §9 point 5).
    from dotenv import load_dotenv
    load_dotenv()

    process_single_pdf_v2(
        file_path=pdf_path,
        keywords_path=keywords_path,
        max_workers=max_workers,
        min_representative_matches=min_representative_matches,
        model_name=model_name,
        log_level=log_level,
    )
    return str(pdf_path)


def run_pipeline_parallel(
    files,
    keywords_path,
    max_workers: int = 5,
    num_processes: int = 2,
    min_representative_matches: int = 1,
    model_name = "random",
    log_level: str = "normal",
    profile: bool = False,
) -> None:
    """Coordinate the multi-PDF pipeline (Layer C: process pool).

    Auto-clamps ``num_processes`` to ``min(num_processes, len(files))``.
    If only one process is needed (or requested), the pipeline runs
    inline in the calling process — no ``ProcessPoolExecutor`` overhead.
    Otherwise each file is dispatched to a worker that calls
    :func:`_worker_process_entry` in a forked child.

    After all PDFs are processed, the function aggregates the per-PDF
    ``*_cost.txt`` files into a single summary. With ``profile=True`` it
    also prints the wall-clock time.
    """
    from dotenv import load_dotenv
    from time import monotonic as _mono

    # ``load_dotenv`` MUST run in the main process before fork so workers
    # inherit the API key (spec §3 / §9). The call is also done by
    # ``process_single_pdf_v2`` for the inline path, but doing it here
    # explicitly documents the fork-safety contract.
    load_dotenv()

    if not files:
        print(Fore.YELLOW + "run_pipeline_parallel: no files provided." + Style.RESET_ALL)
        return

    # Auto-clamp: never spin up more workers than there are PDFs.
    M = max(1, min(num_processes, len(files)))
    if M != num_processes:
        print(
            Fore.YELLOW
            + f"Auto-clamping num_processes from {num_processes} to {M} "
            + f"({len(files)} PDF(s) provided)."
            + Style.RESET_ALL
        )

    start = _mono() if profile else None

    if M == 1:
        # Inline path — no fork, no ProcessPoolExecutor. The single PDF
        # runs in the calling process and creates its own LLMAnalyzer.
        for pdf_path in files:
            _worker_process_entry(
                pdf_path,
                keywords_path,
                max_workers,
                min_representative_matches,
                model_name,
                log_level,
            )
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=M) as executor:
            futures = {
                executor.submit(
                    _worker_process_entry,
                    pdf_path,
                    keywords_path,
                    max_workers,
                    min_representative_matches,
                    model_name,
                    log_level,
                ): pdf_path
                for pdf_path in files
            }
            for fut in concurrent.futures.as_completed(futures):
                pdf_path = futures[fut]
                try:
                    fut.result()
                except Exception as exc:
                    # Don't kill the whole batch on a single failure —
                    # log and continue with the remaining PDFs.
                    print(
                        Fore.RED
                        + f"Worker for {pdf_path} raised: {exc!r}"
                        + Style.RESET_ALL
                    )

    # Aggregate cost by scanning the output directory of every PDF.
    total_calls = 0
    total_cost = 0.0
    pdf_dirs: set = set()
    for pdf_path in files:
        # The function may be called with str or Path; normalize once.
        pdf_dirs.add(Path(pdf_path).parent)

    for pdf_dir in pdf_dirs:
        if not pdf_dir.is_dir():
            continue
        for cost_path in pdf_dir.glob("*_cost.txt"):
            calls, cost = _parse_cost_file(cost_path)
            total_calls += calls
            total_cost += cost

    print(
        Fore.CYAN
        + "\n======================================================================"
        + Style.RESET_ALL
    )
    print(
        Fore.CYAN
        + f"PARALLEL PIPELINE SUMMARY ({len(files)} PDF(s), M={M}, A={max_workers})"
        + Style.RESET_ALL
    )
    print(
        Fore.GREEN
        + f"  Total API calls: {total_calls:,}"
        + Style.RESET_ALL
    )
    print(
        Fore.GREEN
        + f"  Total cost:      ${total_cost:.8f} USD"
        + Style.RESET_ALL
    )
    if profile and start is not None:
        elapsed = _mono() - start
        print(
            Fore.GREEN
            + f"  Wall-clock time: {elapsed:.2f} s"
            + Style.RESET_ALL
        )
    print(
        Fore.CYAN
        + "======================================================================\n"
        + Style.RESET_ALL
    )
