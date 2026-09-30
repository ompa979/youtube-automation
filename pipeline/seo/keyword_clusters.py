"""SEO V3 — Keyword Cluster Engine."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

@dataclass
class KeywordCluster:
    primary_query: str
    exam_query: str
    concept_query: str
    question_query: str
    example_query: str
    short_query: str
    long_tail: list[str] = field(default_factory=list)
    domain: list[str] = field(default_factory=list)
    exams: list[str] = field(default_factory=list)

KEYWORD_CLUSTERS: dict[str, KeywordCluster] = {
    "bcnf_vs_3nf": KeywordCluster(
        primary_query="BCNF vs 3NF",
        exam_query="BCNF vs 3NF IBPS SO IT",
        concept_query="BCNF vs 3NF in DBMS",
        question_query="difference between BCNF and 3NF",
        example_query="BCNF vs 3NF example",
        short_query="BCNF vs 3NF explained",
        long_tail=["BCNF vs 3NF for IBPS SO IT", "BCNF vs 3NF DBMS interview question"],
        domain=["DBMS", "database normalization", "normal forms"],
        exams=["IBPS SO IT", "SBI SO", "bank IT officer"],
    ),
    "1nf_2nf_3nf": KeywordCluster(
        primary_query="1NF 2NF 3NF",
        exam_query="1NF 2NF 3NF IBPS SO IT",
        concept_query="normal forms in DBMS",
        question_query="difference between 1NF 2NF and 3NF",
        example_query="1NF 2NF 3NF example",
        short_query="normalization explained",
        long_tail=["database normalization for bank exams", "1NF 2NF 3NF DBMS interview"],
        domain=["DBMS", "normalization", "relational database"],
        exams=["IBPS SO IT", "SBI SO"],
    ),
    "functional_dependency": KeywordCluster(
        primary_query="functional dependency in DBMS",
        exam_query="functional dependency IBPS SO IT",
        concept_query="functional dependency and normalization",
        question_query="what is functional dependency in DBMS",
        example_query="functional dependency example DBMS",
        short_query="functional dependency explained",
        long_tail=["functional dependency for bank IT officer"],
        domain=["DBMS", "relational algebra", "keys"],
        exams=["IBPS SO IT"],
    ),
    "acid_properties": KeywordCluster(
        primary_query="ACID properties in DBMS",
        exam_query="ACID properties IBPS SO IT",
        concept_query="ACID properties database transactions",
        question_query="what are ACID properties",
        example_query="ACID properties example",
        short_query="ACID properties explained",
        long_tail=["ACID properties for bank exams", "atomicity consistency isolation durability"],
        domain=["DBMS", "transactions", "database"],
        exams=["IBPS SO IT", "SBI SO"],
    ),
    "sql_joins": KeywordCluster(
        primary_query="SQL Joins",
        exam_query="SQL Joins IBPS SO IT",
        concept_query="SQL inner outer join difference",
        question_query="difference between SQL joins",
        example_query="SQL join example",
        short_query="SQL joins explained",
        long_tail=["SQL joins for bank IT officer"],
        domain=["SQL", "DBMS", "relational database"],
        exams=["IBPS SO IT"],
    ),
    "deadlock": KeywordCluster(
        primary_query="deadlock in OS",
        exam_query="deadlock IBPS SO IT",
        concept_query="deadlock detection and prevention",
        question_query="what is deadlock in operating system",
        example_query="deadlock example OS",
        short_query="deadlock explained",
        long_tail=["deadlock banker algorithm bank exams"],
        domain=["Operating Systems", "process management", "OS"],
        exams=["IBPS SO IT"],
    ),
    "tcp_handshake": KeywordCluster(
        primary_query="TCP 3-Way Handshake",
        exam_query="TCP 3-Way Handshake IBPS SO IT",
        concept_query="TCP SYN SYN-ACK ACK",
        question_query="how does TCP 3-way handshake work",
        example_query="TCP handshake example",
        short_query="TCP 3-way handshake explained",
        long_tail=["TCP handshake for bank IT officer"],
        domain=["networking", "TCP/IP", "computer networks"],
        exams=["IBPS SO IT"],
    ),
    "osi_model": KeywordCluster(
        primary_query="OSI Model 7 Layers",
        exam_query="OSI Model 7 Layers IBPS SO IT",
        concept_query="OSI model layers and functions",
        question_query="what are the 7 layers of OSI model",
        example_query="OSI model example",
        short_query="OSI model explained",
        long_tail=["OSI model for bank IT officer"],
        domain=["networking", "OSI", "computer networks"],
        exams=["IBPS SO IT"],
    ),
    "crr_vs_slr": KeywordCluster(
        primary_query="CRR vs SLR",
        exam_query="CRR vs SLR bank exam",
        concept_query="CRR vs SLR difference RBI",
        question_query="difference between CRR and SLR",
        example_query="CRR vs SLR example",
        short_query="CRR vs SLR explained",
        long_tail=["CRR vs SLR for IBPS PO", "CRR vs SLR RBI monetary policy"],
        domain=["banking awareness", "RBI", "monetary policy"],
        exams=["IBPS PO", "SBI PO", "RBI Grade B"],
    ),
    "repo_reverse_repo": KeywordCluster(
        primary_query="Repo Rate vs Reverse Repo Rate",
        exam_query="Repo Rate vs Reverse Repo Rate bank exam",
        concept_query="repo rate reverse repo RBI",
        question_query="difference between repo rate and reverse repo rate",
        example_query="repo rate example",
        short_query="repo rate explained",
        long_tail=["repo rate for SBI PO"],
        domain=["banking awareness", "RBI", "monetary policy"],
        exams=["IBPS PO", "SBI PO", "RBI Grade B"],
    ),
    "npa_classification": KeywordCluster(
        primary_query="NPA classification",
        exam_query="NPA classification bank exam",
        concept_query="NPA 90-day rule RBI",
        question_query="what is NPA in banking",
        example_query="NPA classification example",
        short_query="NPA explained",
        long_tail=["NPA for IBPS PO", "NPA 90-day rule SBI PO"],
        domain=["banking awareness", "NPA", "RBI regulation"],
        exams=["IBPS PO", "SBI PO"],
    ),
    "neft_rtgs_imps": KeywordCluster(
        primary_query="NEFT vs RTGS vs IMPS",
        exam_query="NEFT vs RTGS vs IMPS bank exam",
        concept_query="NEFT RTGS IMPS settlement time",
        question_query="difference between NEFT RTGS and IMPS",
        example_query="NEFT RTGS IMPS example",
        short_query="NEFT RTGS IMPS explained",
        long_tail=["NEFT vs RTGS for IBPS PO"],
        domain=["banking awareness", "payment systems", "digital banking"],
        exams=["IBPS PO", "SBI PO", "RBI Grade B"],
    ),
    "gdp_vs_gnp": KeywordCluster(
        primary_query="GDP vs GNP",
        exam_query="GDP vs GNP RBI Grade B",
        concept_query="GDP vs GNP difference economics",
        question_query="difference between GDP and GNP",
        example_query="GDP vs GNP example",
        short_query="GDP vs GNP explained",
        long_tail=["GDP vs GNP for RBI Grade B"],
        domain=["economy", "macroeconomics", "national income"],
        exams=["RBI Grade B", "NABARD", "SEBI"],
    ),
    "m1_vs_m3": KeywordCluster(
        primary_query="M1 vs M3 Money Supply",
        exam_query="M1 M2 M3 money supply RBI Grade B",
        concept_query="M1 M3 money supply difference",
        question_query="difference between M1 M2 M3 money supply",
        example_query="M1 M3 money supply example",
        short_query="money supply M1 M3 explained",
        long_tail=["money supply for RBI Grade B"],
        domain=["economy", "monetary economics", "RBI"],
        exams=["RBI Grade B", "NABARD"],
    ),
    "fiscal_deficit": KeywordCluster(
        primary_query="Fiscal Deficit vs Revenue Deficit",
        exam_query="Fiscal Deficit Revenue Deficit RBI Grade B",
        concept_query="fiscal deficit revenue deficit primary deficit",
        question_query="difference between fiscal deficit and revenue deficit",
        example_query="fiscal deficit example",
        short_query="fiscal deficit explained",
        long_tail=["fiscal deficit for RBI Grade B"],
        domain=["economy", "government finance", "fiscal policy"],
        exams=["RBI Grade B", "UPSC"],
    ),
}

SYNONYM_MAP: dict[str, list[str]] = {
    "BCNF vs 3NF": ["BCNF vs 3NF difference", "difference between BCNF and 3NF", "BCNF and 3NF", "3NF vs BCNF"],
    "CRR vs SLR": ["CRR vs SLR difference", "difference between CRR and SLR", "CRR SLR RBI"],
    "Repo Rate vs Reverse Repo Rate": ["repo vs reverse repo", "repo rate reverse repo difference"],
    "TCP 3-Way Handshake": ["TCP handshake", "SYN SYN-ACK ACK", "TCP 3 way handshake"],
    "OSI Model 7 Layers": ["OSI 7 layers", "OSI model layers", "OSI model explained"],
    "GDP vs GNP": ["GDP GNP difference", "GDP vs GNP economics", "GDP NNP GNP"],
    "M1 vs M3 Money Supply": ["M1 M2 M3 money", "money supply types", "near money M3"],
    "ACID properties in DBMS": ["ACID DBMS", "atomicity consistency isolation durability", "ACID transactions"],
}

def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def get_cluster_for_topic(topic: str) -> KeywordCluster | None:
    topic_lower = topic.lower()
    topic_norm = _normalise(topic)

    if topic_norm in KEYWORD_CLUSTERS:
        return KEYWORD_CLUSTERS[topic_norm]

    best_key: str | None = None
    best_score = 0
    for key, cluster in KEYWORD_CLUSTERS.items():
        signals = [cluster.primary_query, cluster.concept_query, cluster.question_query]
        signals += cluster.long_tail + cluster.domain + cluster.exams
        score = sum(
            1 for sig in signals
            if sig.lower() in topic_lower or any(
                w in topic_lower for w in sig.lower().split() if len(w) > 3
            )
        )
        if score > best_score:
            best_score = score
            best_key = key

    if best_score >= 2 and best_key:
        return KEYWORD_CLUSTERS[best_key]

    return None


# V6 fallback: every curated topic receives a usable search cluster even when it is not in the static map.
def get_cluster_for_topic(topic: str) -> KeywordCluster | None:  # type: ignore[no-redef]
    topic_text = re.sub(r"\s+", " ", (topic or "").strip())
    if not topic_text:
        return None
    # Prefer a concept before ':' / dash; strip exam suffixes so the primary query stays human-searchable.
    primary = re.split(r":|\s+—\s+|\s+-\s+", topic_text, maxsplit=1)[0].strip()
    if len(primary.split()) > 8:
        primary = " ".join(primary.split()[:8])
    exams = []
    for exam in ["IBPS SO IT", "IBPS PO", "SBI PO", "SBI Clerk", "RBI Grade B", "NABARD", "SEBI", "RRB", "SSC"]:
        if exam.lower() in topic_text.lower():
            exams.append(exam)
    domain_map = {
        "sql": "SQL", "dbms": "DBMS", "tcp": "Computer Networks", "osi": "Computer Networks",
        "subnet": "Computer Networks", "rsa": "Cyber Security", "aes": "Cyber Security", "deadlock": "Operating Systems",
        "crr": "Banking Awareness", "slr": "Banking Awareness", "repo": "Banking Awareness", "npa": "Banking Awareness",
        "neft": "Digital Banking", "rtgs": "Digital Banking", "imps": "Digital Banking", "gdp": "Economics",
        "gnp": "Economics", "fiscal": "Economics", "inflation": "Economics", "m1": "Monetary Economics",
        "m3": "Monetary Economics", "syllogism": "Reasoning", "percentage": "Quantitative Aptitude",
        "profit": "Quantitative Aptitude", "quadratic": "Quantitative Aptitude", "series": "Quantitative Aptitude",
        "agreement": "English", "para jumble": "English", "cloze": "English"
    }
    lower = primary.lower()
    domain = next((v for k, v in domain_map.items() if k in lower), "Exam Preparation")
    return KeywordCluster(
        primary_query=primary,
        exam_query=f"{primary} {exams[0]}" if exams else primary,
        concept_query=f"{primary} in {domain}",
        question_query=f"what is {primary}",
        example_query=f"{primary} example",
        short_query=f"{primary} explained",
        long_tail=[f"{primary} for {exams[0]}" if exams else f"{primary} explained", f"{primary} example {domain}"],
        domain=[domain],
        exams=exams,
    )
