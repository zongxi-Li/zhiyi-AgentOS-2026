"""Fetch verified primary-source metadata and optional HTML for the communication review.

The candidate list is deliberately bounded and manually screened, not an exhaustive search.
Downloads and JSON are local-only under the repository's existing papers ignore policy.
No model calls or credentials are used. Run from any directory with Python + requests + bs4.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-11-25"
SEEDS = [
    ("P01", "2410.02506", "topology", "AgentPrune"),
    ("P02", "https://aclanthology.org/2025.acl-long.1170/", "topology", "AgentDropout"),
    ("P03", "2610.41378", "receiver", "Ask on Demand"),
    ("P04", "2602.05965", "shared_memory", "Learning to Share"),
    ("P05", "2605.24486", "shared_memory", "AgentFugue"),
    ("P06", "2606.05304", "budget", "PACT"),
    ("P07", "2609.20050", "receiver", "Missing Complement"),
    ("P08", "2611.24357", "context", "Semantic Context Handoff"),
    ("P09", "2609.39139", "stopping", "BELIEFRAG"),
    ("P10", "2310.08560", "context", "MemGPT"),
    ("P11", "2512.24601", "context", "Recursive Language Models"),
    ("P12", "2210.03629", "retrieval", "ReAct"),
    ("P13", "2212.10509", "retrieval", "IRCoT"),
    ("P14", "2305.06983", "retrieval", "FLARE"),
    ("P15", "2310.11511", "retrieval", "Self-RAG"),
    ("P16", "2403.14403", "retrieval", "Adaptive-RAG"),
    ("P17", "2310.05736", "compression", "LLMLingua"),
    ("P18", "2310.06839", "compression", "LongLLMLingua"),
    ("P19", "2510.12872", "latent", "KVComm"),
    ("P20", "2510.03346", "latent", "KVComm selective sharing"),
    ("P21", "2609.37017", "latent", "LatCom"),
    ("P22", "2603.01045", "benchmark", "Silo-Bench"),
    ("P23", "2503.13657", "failure", "MAST"),
    ("P24", "https://aclanthology.org/2026.findings-acl.753/", "failure", "Superficial Success"),
    ("P25", "2609.32961", "compression", "Beyond Token Savings"),
    ("P26", "2305.14627", "evidence", "ALCE"),
    ("P27", "2307.03172", "context", "Lost in the Middle"),
    ("P28", "1809.09600", "benchmark", "HotpotQA"),
    ("P29", "2108.00573", "benchmark", "MuSiQue"),
    ("P30", "2611.26957", "provenance", "Provenance-Aware Framework"),
    ("P31", "2606.04990", "provenance", "From Agent Traces to Trust"),
    ("P32", "https://aclanthology.org/2026.emnlp-main.2396/", "compression", "Context Compression Survey"),
    ("P33", "2308.00352", "framework", "MetaGPT"),
    ("P34", "2308.08155", "framework", "AutoGen"),
    ("P35", "2504.16736", "protocol", "Agent Protocols Survey"),
    ("P36", "2505.02279", "protocol", "Interoperability Survey"),
    ("P37", "2609.37590", "compression", "FOCUS"),
    ("P38", "2611.06500", "latent", "Coca-Cola"),
    ("M01", "2609.00065", "methodology", "Scientific Agent Skills"),
]
SUPPLEMENTARY_SEEDS = [
    ("S01", "2611.22169", "evidence_admission", "Not All Evidence Is Admissible"),
    ("S02", "2608.28542", "accountability", "Offline-Verifiable Accountability"),
    ("S03", "2610.24833", "consensus", "Measuring Consensus"),
]

EXPECTED_PHRASES = {
    "P01": "Cut the Crap", "P06": "What Should Agents Say", "P13": "Interleaving Retrieval",
    "P14": "Active Retrieval Augmented Generation", "P19": "Online Cross-context KV-cache",
    "P20": "Selective KV Sharing", "P23": "Why Do Multi-Agent LLM Systems Fail", "P24": "Superficial Success", "P26": "Generate Text with Citations",
    "P30": "Unsupported Claim Propagation", "P31": "From Agent Traces to Trust",
    "P32": "Context Compression for LLM Agents", "P35": "Survey of AI Agent Protocols",
    "P36": "Survey of Agent Interoperability Protocols", "P38": "Tools Need Not Speak in Text",
}


def get(url: str) -> requests.Response:
    response = requests.get(url, timeout=(12, 40), headers={"User-Agent": "Kinlin-literature-review/1.0 (academic metadata verification)"})
    response.raise_for_status()
    return response


def collect(seed, full: set[str], refresh: bool) -> dict:
    pid, source, theme, alias = seed
    url = source if source.startswith("https://") else f"https://arxiv.org/abs/{source}"
    url_key = hashlib.sha256(url.encode()).hexdigest()[:8]
    cached = ROOT / ".build" / "sources" / f"{pid}-{url_key}.html"
    record = {"id": pid, "alias": alias, "theme": theme, "url": url, "review_date": DATE,
              "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        if cached.exists() and not refresh:
            raw = cached.read_text(encoding="utf-8")
        else:
            raw = get(url).text
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(raw, encoding="utf-8")
        soup = BeautifulSoup(raw, "html.parser")
        def metas(name):
            return [x.get("content", "") for x in soup.find_all("meta", attrs={"name": name})]
        title = metas("citation_title")
        expected = EXPECTED_PHRASES.get(pid, alias)
        normalize = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
        if not title or normalize(expected) not in normalize(title[0]):
            raise ValueError(f"Title mismatch: expected {expected!r}, received {title!r}")
        abstract_node = soup.select_one("blockquote.abstract") or soup.select_one("div.acl-abstract")
        abstract = metas("citation_abstract") or ([abstract_node.get_text(" ", strip=True)] if abstract_node else [])
        version = soup.select_one(".dateline")
        record.update(title=title[0] if title else soup.title.get_text(" ", strip=True), authors=metas("citation_author"),
                      publication_date=(metas("citation_date") or metas("citation_publication_date") or [""])[0],
                      abstract=abstract[0].removeprefix("Abstract:").strip() if abstract else "",
                      version_note=version.get_text(" ", strip=True) if version else "",
                      doi=(metas("citation_doi") or [""])[0],
                      sha256=hashlib.sha256(raw.encode()).hexdigest(), status="metadata_verified", reading_depth="abstract")
        journal = soup.select_one(".jref")
        if journal:
            record["journal_reference"] = journal.get_text(" ", strip=True)
        doi_link = soup.select_one('.arxivdoi a[href^="https://doi.org/"]')
        if not record["doi"] and doi_link:
            record["doi"] = doi_link["href"].removeprefix("https://doi.org/")
        if pid in full and not source.startswith("https://"):
            full_path = ROOT / ".build" / "sources" / f"{pid}-{url_key}-full.html"
            full_url = f"https://arxiv.org/html/{source}"
            try:
                html = full_path.read_text(encoding="utf-8") if full_path.exists() and not refresh else get(full_url).text
                full_path.write_text(html, encoding="utf-8")
                doc = BeautifulSoup(html, "html.parser")
                for tag in doc(["script", "style", "nav", "header", "footer"]): tag.decompose()
                body = doc.select_one("article") or doc
                text = body.get_text("\n", strip=True)
                (full_path.with_suffix(".txt")).write_text(text, encoding="utf-8")
                record.update(fulltext_url=full_url, fulltext_chars=len(text), fulltext_retrieved=True)
            except Exception as exc:
                record["fulltext_error"] = f"{type(exc).__name__}: {exc}"
        return record
    except Exception as exc:
        return {**record, "status": "fetch_failed", "error": f"{type(exc).__name__}: {exc}"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", default="P01,P03,P04,P05,P06,P07,P08,P09,P11,P19,P20,P22,P23,P25,P30")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    full = set(args.full.split(","))
    previous = {}
    out = ROOT / "papers-reviewed.json"
    if out.exists(): previous = {x["id"]: x for x in json.loads(out.read_text(encoding="utf-8"))}
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for row in pool.map(lambda s: collect(s, full, args.refresh), SEEDS):
            # Human screening annotations survive repeat metadata retrieval.
            row.update({k: v for k, v in previous.get(row["id"], {}).items() if k in {"score", "decision", "screening_reason", "reading_depth", "selected_sections", "evidence_notes"}})
            results.append(row)
            print(json.dumps({k: row[k] for k in ("id", "status", "title", "fulltext_chars", "error") if k in row}, ensure_ascii=False), flush=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Saved {len(results)} metadata records to {out}", flush=True)
    supplements = [collect(seed, set(), args.refresh) for seed in SUPPLEMENTARY_SEEDS]
    (ROOT / "supplementary-candidates.json").write_text(json.dumps(supplements, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Saved {len(supplements)} abstract-only boundary candidates", flush=True)
    if any(row["status"] != "metadata_verified" for row in results + supplements):
        raise SystemExit("Some source verifications failed; inspect local records before rebuilding the catalogue.")


if __name__ == "__main__": main()
