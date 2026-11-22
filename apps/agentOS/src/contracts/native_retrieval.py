"""Stable ledger slots for the native read-only retrieval prologue."""

RETRIEVAL_LEDGER_VERSION = "native-retrieval.v1"
RETRIEVAL_COMMIT_SUFFIXES = {
    "knowledge_search": "",
    "web_search": ":web-search",
    "web_extract": ":web-extract",
}


def retrieval_operation_key(commit_id: str, tool: str) -> str:
    return f"{commit_id}:retrieval:{tool}"
