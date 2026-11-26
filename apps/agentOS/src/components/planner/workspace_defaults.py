"""Defaults for inferred repository exploration; never narrow caller-fixed scope."""
from pathlib import PurePosixPath

GENERATED_DIRECTORIES = (".git", "node_modules", "dist", "build", ".next", ".nuxt",
    ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".cache", "coverage")


def inferred_exclusions(path):
    prefix = "" if path == "." else str(PurePosixPath(path)) + "/"
    return tuple(prefix + name for name in GENERATED_DIRECTORIES)


EXPLORATION_GUIDANCE = (
    "For inferred repository exploration, skip dependency directories, generated builds, VCS internals "
    "and caches by default (.git, node_modules, dist, build, .venv, __pycache__, coverage). "
    "Read source/configuration text first. Do not request base64/binary file contents just to inspect code. "
    "Binary assets, archives, fonts, media and database files require a concrete task-related reason "
    "and an explicit targeted read. Preserve caller-explicit file/tree coverage; report exclusions "
    "and unresolved evidence instead of claiming excluded files were inspected. "
)
