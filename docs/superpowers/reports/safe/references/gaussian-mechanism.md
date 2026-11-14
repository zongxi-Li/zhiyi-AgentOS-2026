# diffprivlib 高斯机制摘录（不参与运行）

来源：IBM differential-privacy-library，固定 tag `0.6.6`。
[原文件](https://github.com/IBM/differential-privacy-library/blob/0.6.6/diffprivlib/mechanisms/gaussian.py)。
Copyright (C) IBM Corporation 2019。许可证MIT，完整许可证头见 `LICENSE.diffprivlib.txt`。
以下为原样短摘录；中文说明为本项目新增。这不是向量发布事务或可验证的safe DP实现。

## 经典机制校准与参数边界（第64–77行）

```python
    def __init__(self, *, epsilon, delta, sensitivity, random_state=None):
        super().__init__(epsilon=epsilon, delta=delta, random_state=random_state)
        self.sensitivity = self._check_sensitivity(sensitivity)
        self._scale = np.sqrt(2 * np.log(1.25 / self.delta)) * self.sensitivity / self.epsilon

    @classmethod
    def _check_epsilon_delta(cls, epsilon, delta):
        if epsilon == 0 or delta == 0:
            raise ValueError("Neither Epsilon nor Delta can be zero")

        if isinstance(epsilon, Real) and epsilon > 1.0:
            raise ValueError("Epsilon cannot be greater than 1. If required, use GaussianAnalytic instead.")

        return super()._check_epsilon_delta(epsilon, delta)
```

## 采样方法（第108–117行）

```python
    @copy_docstring(Laplace.randomise)
    def randomise(self, value):
        self._check_all(value)

        try:
            standard_normal = (self._rng.normalvariate(0, 1) + self._rng.normalvariate(0, 1)) / np.sqrt(2)
        except AttributeError:  # random_state is a np.random.RandomState
            standard_normal = (self._rng.standard_normal() + self._rng.standard_normal()) / np.sqrt(2)

        return value + standard_normal * self._scale
```

## 对应本模块的复用方式

- 优先通过固定版本库API复用机制，不复制散落的采样表达式到用例层。正确类名是 `Gaussian` / `GaussianAnalytic`。
- 经典Gaussian明确限制epsilon≤1；epsilon较大时不能继续套用相同公式。
- 激活先整向量L2裁剪到C，replacement邻接敏感度边界2C；仍需核实向量高斯机制与有限精度实现的适用证明。
- 向量各坐标的实现方式不能被误解释为N次独立的隐私保证。每步完整向量发布和跨步transcript均要组合分析。
- `infrastructure/privacy/gaussian.py` 只保留机制适配TODO；先完成校准与账本预扣，再接发布链路。
- 库支持实验random_state，不表示生产可以使用固定seed；不得绕过安全随机源和有限精度风险。
