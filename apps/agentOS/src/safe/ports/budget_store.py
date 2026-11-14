"""本机预算持久化端口；查询结构不构成可用发布事务。

TODO(P4)：在会计数值表示冻结后定义原子reserve、release去重和commit接口。
TODO(P4)：发布前提交消费；账本不可写时拒绝，不以内存账户临时替代。
TODO(P4)：定义崩溃恢复扫描与noisy bytes绑定，未知出站消费不可自动退款。
"""

from typing import Protocol

from safe.contracts.privacy import BudgetSnapshot


class BudgetStore(Protocol):
    def snapshot(self, owner_id: str) -> BudgetSnapshot:
        """返回版本化审计视图；当前合同未包含可消费余额。"""
        ...

    def close(self) -> None:
        """等待事务完成并关闭；不能删除或重建预算历史。"""
        ...
