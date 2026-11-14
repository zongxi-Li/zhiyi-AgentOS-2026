"""无副作用命令解析层；用例通过参数注入。

状态：离线export参数解析已实现；verify/benchmark子命令仍待扩展。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：补齐verify/benchmark命令；保留当前export的显式参数和非零失败语义。
TODO(P2-3)：报告仅合成数据、版本、摘要、耗时和误差，不保存真实用户输入。
TODO(P2-4)：未实现命令使用明确非零退出码，不输出伪造的成功报告。

验收：--help无需Torch或网络；不合法参数不执行任何外部操作。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

import argparse
from pathlib import Path
from collections.abc import Callable, Sequence


def run_export_cli(exporter: Callable[..., str], argv: Sequence[str] | None = None) -> int:
    """只解析参数并调用注入的离线导出用例；--help不加载模型。"""
    parser = argparse.ArgumentParser(description="离线导出已批准Qwen2的prefix/suffix制品，不下载模型")
    parser.add_argument("--source", type=Path, required=True, help="已准备并核验的完整模型目录")
    parser.add_argument("--destination", type=Path, required=True, help="尚不存在的目标角色制品目录")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True, help="固定40位模型commit SHA，不能使用main")
    parser.add_argument("--cut-layer", type=int, default=2)
    parser.add_argument("--license-id", required=True, help="操作者核实的模型许可标识")
    args = parser.parse_args(argv)
    digest = exporter(args.source, args.destination, model_id=args.model_id, revision=args.revision,
                      cut_layer=args.cut_layer, license_id=args.license_id)
    print("导出完成，待配置批准的manifestDigest：" + digest)
    return 0
