"""显式离线角色导出入口；真实实现与装配统一归safe，不维护第二套模型代码。"""

from pathlib import Path
import sys

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps/agentOS/src"))
    from components.safe.bootstrap.cli import main

    raise SystemExit(main())
