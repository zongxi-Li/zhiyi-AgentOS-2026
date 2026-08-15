"""执行包引用的构建边界。"""

from contracts.execution import ExecutionPackageRef


def package_summary(package: ExecutionPackageRef) -> dict[str, str]:
    """返回可日志化的执行包摘要，不读取包正文。"""
    return {"packageId": package.package_id, "checksum": package.checksum}
