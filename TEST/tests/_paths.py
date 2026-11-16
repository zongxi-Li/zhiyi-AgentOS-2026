"""Stable repository paths shared by moved AgentOS tests."""
from pathlib import Path
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'apps/agentOS/src').is_dir())
AGENTOS_ROOT = REPO_ROOT / 'apps/agentOS'
SRC = AGENTOS_ROOT / 'src'
TEST_ROOT = REPO_ROOT / 'TEST/tests'
