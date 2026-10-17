# Pair A 独立准备工作

这些文件新增于 `pair_a_prep/`，不导入 `fow_shared`，也不依赖 Pair B 的
PR。根目录的接口、encoder、README、依赖文件均未修改。这里没有实现或
认领 ZS21／Obscuro，也没有批准团队设置或交付日期。

| 工作 | 文件 | 已交付内容 |
|---|---|---|
| 论文实现规格 | [paper_specs.md](docs/paper_specs.md) | 固定 v2 来源、参数与章节索引、实现与验收步骤、待确认项 |
| 微型博弈验证 | [toy_games.py](toy_games.py) | 信息集约束、机会节点、LP 参考解、行为策略 best response／Nash gap |
| Stockfish 测量 | [benchmark_stockfish.py](benchmark_stockfish.py) | 固定局面、depth 1／11、单着／全着 MultiPV、原始分数及耗时 |
| 规则案例库 | [rules_cases.json](data/rules_cases.json)、[fixtures.py](fixtures.py) | 17 个特殊局面及未来 adapter 的验收入口 |
| 复现差异记录 | [reproduction_differences.md](docs/reproduction_differences.md) | 论文、本组提案、实测与未决定事项的区分 |
| 本次验证结果 | [verification.md](docs/verification.md) | 测试范围、真实引擎试验、限制与后续接入方式 |

代码注释和详细技术说明使用英文，便于与队友共享。

## 安装与运行

在项目根目录使用独立虚拟环境；不需要合并 Pair B 的 PR：

```powershell
python -m venv pair_a_prep/.venv
pair_a_prep/.venv/Scripts/python -m pip install -r pair_a_prep/requirements.txt
pair_a_prep/.venv/Scripts/python -m pytest -q pair_a_prep/tests tests
```

生成微型博弈参考结果、检查规则案例定义：

```powershell
pair_a_prep/.venv/Scripts/python -m pair_a_prep.toy_games --output pair_a_prep/results/toy_new.json
pair_a_prep/.venv/Scripts/python -m pair_a_prep.fixtures
```

运行引擎测量时，`--engine` 指向自己的 Stockfish 可执行文件，输出使用新文件名：

```powershell
pair_a_prep/.venv/Scripts/python -m pair_a_prep.benchmark_stockfish --engine "C:/path/to/stockfish.exe" --output pair_a_prep/results/stockfish_new.jsonl
```

实际测量参数与输出格式见 [benchmark.md](docs/benchmark.md)。脚本不会覆盖已有
测量文件。Stockfish 二进制不放入仓库；本次从官方版本下载到临时目录运行。

## 微型博弈如何供两个 agent 使用

`Node` 用 `player + infoset` 表示决策者可区分的信息，机会节点另有概率。
纯策略为每个信息集选择一个动作；同一信息集中的不同隐藏节点必须用同一动作。
工具枚举两个玩家的纯策略，构造收益矩阵，然后解两个 LP，得到双方策略和
best-response 上下界。它是小规模验证基准，不适合直接扩展到棋类规模。

当前包含隐藏／公开行动的 matching pennies、隐藏／公开硬币和 Kuhn poker。
`behavioral_nash_gap(root, policies)` 可检查未来求解器输出的行为策略；policy
格式为每位玩家各自的 `{infoset: {action: probability}}`。不要把 LP 的混合纯策略
简单逐信息集取平均，当作等价行为策略；条件到达概率会影响转换。

这些游戏尚未验证 KLSS／KLUSS 的 gadget 构造，也没有实现 PCFR+。

## 规则案例如何接入未来 adapter

提供一个 `module:function`，接收完整 fixture 字典，返回：

```python
{
    "legal_moves": ["e1g1"],
    "visible_squares": ["e1", "f1", "g1"],
    "visible_pieces": {"e1": "K", "f1": None, "g1": None},
    "terminal": False,
    "winner": None,
    # Hidden observation fields should be omitted or None.
}
```

上面仅示意返回格式，并非某个案例的完整正确观察。之后可运行：

```powershell
python -m pair_a_prep.fixtures --adapter your_adapter:inspect_case
```

只检查 fixture 中列出的断言，所以可以逐项补充完整观察。包含
`initial_fen + moves_uci` 的案例必须重放历史，不能只加载最终 FEN。
不带 `--adapter` 时只验证案例结构和历史，不代表 FoW 规则测试通过。
