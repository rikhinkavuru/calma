"""runner.data_catalog — canonical download URLs for well-known public datasets (deterministic, no AI variance).

The AI-plan data-source step (planner.data_sources) is powerful but inconsistent: a small model recalls
`clinvar.vcf.gz` from NCBI one run and guesses a wrong path the next. For the STANDARD reference datasets — the
ones a large fraction of genomics/ML repos need — the URL is fully deterministic, so we don't need a model to
recall it. This catalog augments the plan with those canonical URLs (and corrects nothing the plan got right),
so the common data-blocked repo resolves reliably.

Scope is deliberately narrow: only datasets with ONE stable, public, canonical file URL (reference genomes,
ClinVar). Datasets whose exact file path varies per repo (arbitrary HuggingFace files, gnomAD per-shard) stay
AI-driven — a wrong catalog URL would fetch wrong data (capped to INCONCLUSIVE, but still noise). Pure stdlib.
"""
from __future__ import annotations

import os
import re

# key → {match: substrings that identify the dataset, url: canonical https source, path: default repo-relative
# path the repo is likely to expect it at}. The fetcher auto-grabs a companion .tbi/.csi for bgzipped files.
_CATALOG: dict[str, dict] = {
    "clinvar_grch38": {
        "match": ("clinvar",),
        "url": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz",
        "path": "data/clinvar/clinvar.vcf.gz",
    },
    "grch38_ref": {
        "match": ("grch38", "hg38", "reference genome", "reference fasta", "primary_assembly"),
        "url": ("https://ftp.ensembl.org/pub/release-110/fasta/homo_sapiens/dna/"
                "Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz"),
        "path": "data/reference/GRCh38.fa.gz",
    },
    "grch37_ref": {
        "match": ("grch37", "hg19"),
        "url": ("https://ftp.ensembl.org/pub/grch37/release-110/fasta/homo_sapiens/dna/"
                "Homo_sapiens.GRCh37.dna.primary_assembly.fa.gz"),
        "path": "data/reference/GRCh37.fa.gz",
    },
    "encode_ccre": {
        "match": ("encode ccre", "ccres", "candidate cis-regulatory", "ccre"),
        "url": "https://downloads.wenglab.org/Registry-V4/GRCh38-cCREs.bed",
        "path": "data/encode/GRCh38-cCREs.bed",
    },
}


# Filename → canonical URL rules, for REACTIVE resolution: when a repo step fails on a missing file, we know the
# EXACT path the repo wants (from its error), so we resolve by the file's basename. The value may be a fixed URL
# or a callable(basename) → URL for files whose URL is a function of the name (a per-chromosome VCF, etc.).
_FILE_RULES: list[tuple] = [
    (re.compile(r"clinvar.*\.vcf\.gz$", re.I),
     "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz"),
    (re.compile(r"(grch38|hg38).*\.(fa|fasta)(\.gz)?$", re.I),
     "https://ftp.ensembl.org/pub/release-110/fasta/homo_sapiens/dna/"
     "Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz"),
    (re.compile(r"(grch37|hg19).*\.(fa|fasta)(\.gz)?$", re.I),
     "https://ftp.ensembl.org/pub/grch37/release-110/fasta/homo_sapiens/dna/"
     "Homo_sapiens.GRCh37.dna.primary_assembly.fa.gz"),
    (re.compile(r"(ccre|ccres).*\.bed$", re.I),
     "https://downloads.wenglab.org/Registry-V4/GRCh38-cCREs.bed"),
]


def resolve_path(path: str) -> str | None:
    """The canonical URL for a missing file, matched on its BASENAME (deterministic). Used by the reactive
    resolve loop: the repo's error gives the exact path, so we place the fetch exactly where it's read. None if
    the file isn't a recognized standard dataset (then the AI resolver is tried)."""
    base = os.path.basename(str(path or ""))
    if not base:
        return None
    for rx, val in _FILE_RULES:
        if rx.search(base):
            return val(base) if callable(val) else val
    return None


def _text_of(sources, data_needed) -> str:
    parts = [(data_needed or "")]
    for s in sources or []:
        parts.append(str(s.get("path", "")) + " " + str(s.get("url", "")))
    return " ".join(parts).lower()


def augment_sources(sources, data_needed: str = "") -> list[dict]:
    """Return the plan's data sources plus a canonical entry for any catalog dataset the run references (via the
    plan's data_needed text or an existing source path/url) that isn't already covered. Never overrides a source
    the plan already provided (dedup by URL); only ADDS the deterministic ones the plan may have missed/fumbled."""
    out = [dict(s) for s in (sources or []) if isinstance(s, dict)]
    text = _text_of(out, data_needed)
    have = {s.get("url") for s in out}
    for _key, ent in _CATALOG.items():
        if not any(m in text for m in ent["match"]):
            continue
        if ent["url"] in have:
            continue
        # Always land it at the catalog's canonical default path — NOT a fuzzy-matched plan path (the substring
        # "clinvar" collides with "evo2_clinvar", which would drop the ClinVar VCF onto a different dataset's
        # file). The default paths are the standard conventions; the plan's own entry (if any) still covers a
        # non-standard path with the plan's URL, so both get tried.
        out.append({"path": ent["path"], "url": ent["url"]})
        have.add(ent["url"])
    return out
