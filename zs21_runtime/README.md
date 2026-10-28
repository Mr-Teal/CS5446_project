# ZS21 Dark Chess agent：运行与接入手册

这是 Zhang–Sandholm 2021《Subgame solving without common knowledge》的本地复现，包含完整信息集维护、sequence-form LP、nested 1-KLSS、Stockfish 13 估值、matched baseline、人机界面和三视角观战。算法及数值解释采用项目已确认的决定，详见 [实现说明](docs/IMPLEMENTATION.md) 和 [决策记录](docs/decisions.md)。本次原始资料核验未找到作者的完整 2021 agent 实现；本项目不是作者官方代码。

**先看这里：** 新系统推荐直接接入 `PaperAgent.observe/act`；现有仓库 `fow_shared.AgentInput` 调用方使用 `SharedAgent`；其他语言或独立进程使用 `pair_a_prep.zs21.serve`。三种接入方式都调用真实 paper agent，`protocol --random-example` 仅是另外的接口演示。

## 1. 从新电脑启动

当前已验证 **Windows x64 + AVX2/BMI2 CPU**，预编译 DLL/EXE 不适用于 Linux/macOS。使用 [Pixi 官方安装说明](https://pixi.prefix.dev/latest/installation/)，然后从仓库根目录执行以下命令。PR #37 当前目标为 `main`；合并前检出 `pair-a/zs21-agent-integration`，合并后可使用包含本改动的 `main`。

```powershell
git clone --branch pair-a/zs21-agent-integration https://github.com/Mr-Teal/CS5446_project.git
cd CS5446_project
pixi install --manifest-path zs21_runtime/pixi.toml --locked -e darkchess
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess doctor
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess smoke
```

私有仓库需要团队 GitHub 权限；也可在对应分支下载 ZIP。项目不依赖原作者机器上的 `D:\workspace` 目录、父目录 Pixi 环境或下载目录。环境定义与锁文件均在本目录；两个环境名 `default` / `darkchess` 共用相同依赖和 solve group，未包含其他课程的 GPU/Notebook 依赖。[Pixi 环境说明](https://pixi.prefix.dev/latest/workspace/multi_environment/)

`doctor` 会校验随包资源哈希、DLL 规则版本，启动真正的四个 Stockfish 13 单线程实例并完成估值。`smoke` 只运行两个行动，每次最多一次展开；输出 `unfinished_smoke` 是预期结果，不是和棋成绩，也不是正式比赛。报告写入被 Git 忽略的 `zs21_runtime/out/`。

`test` 会把仓库已有的 `pair_b/src` 加入当前测试进程的导入路径，以运行 main 中 #36 引入的 Material-only 接入测试。它不安装 Pair B 的训练依赖，也不改变其他运行命令的导入路径。

共享裁判和 ZS21 裁判现在统一使用 `fow_shared.values` 的 FoW 重复判定。有效的吃过路兵权按 FoW 可走性判断，不因王受攻击而删除；重复判定需要完整棋局历史，单独 FEN 不足以恢复。修复依据及回归范围见 [规则一致性记录](validation/repetition-consistency.md)。

## 2. 人机对战与观战

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess play --white human --black paper
```

保持终端打开，使用打印出的 `white` 链接进行人机对战；点击棋子，再点高亮目标，升变时选择 Q/R/B/N。`spectator` 链接同时显示白方视野、真实棋盘、黑方视野。玩家和观战使用不同访问 token；玩家接口不发送隐藏棋子。主动打开观战页会获知真局面，评测时不要将其提供给 agent。

可交换颜色，或把 `paper` 换成 `baseline`。两边也可以使用 `module:factory` 或 `process:配置文件路径`。Ctrl+C 退出。每步默认 16 秒，资源为一个包含四个单线程引擎的共享池；需要显式改变预算时使用 `--seconds`，新预算应作为另一实验配置。

## 3. 原生 Python 接口：推荐

在仓库根目录，通过本目录 Pixi 环境运行调用脚本。核心类型：

```python
from time import perf_counter
from pair_a_prep.zs21.agent import PaperAgent
from pair_a_prep.zs21.config import load
from pair_a_prep.zs21.engine import EnginePool

runtime = load()
with EnginePool(runtime["engine"]) as pool:
    agent = PaperAgent("white", 2106, pool, **runtime["agent_kwargs"])
    try:
        deadline = perf_counter() + 16.0
        agent.observe(initial_white_observation, deadline=deadline)
        decision = agent.act(deadline)
        # The host applies decision.move, then delivers the new private observations.
    finally:
        agent.close()
```

上面的 `initial_white_observation` 由你的 FoW 裁判生成，不是完整 FEN。可直接运行的完整对局循环见 [examples/python_match.py](examples/python_match.py)，其中只有 host 持有 `Referee`。它演示了双方初始化、交接计时、观测通知、动作校验和资源释放。

| 接口 | 要求 |
| --- | --- |
| `PaperAgent(player, seed, pool, baseline=False, initial_fen=None, ...)` | `player` 为 `white` / `black`；每局创建新对象。`initial_fen` 只能用于双方事先知道的公开起始局面，不能注入中途隐藏真棋盘。 |
| `observe(observation, own_move=None, deadline=None)` | 初始 ply 0 及每个半回合后调用一次，包括对手回合和终局；不能丢弃自己刚走完时的即时观测。 |
| `act(deadline)` | 只在该方行动、且非终局时调用。`deadline` 是绝对 `time.perf_counter()` 时间，不是秒数。 |
| `Decision` | `move` 为实际选中的 UCI 动作；`root_policy` 包含所有合法动作及其概率，包含零概率项；`diagnostics` 记录 population、roots、depth、gap 等。 |
| `close()` | 释放该 agent 的原生信息集；共享 `EnginePool` 由 host 在双方都退出后关闭。 |

**通知顺序示例：** 白方走 `e2e4` 后，向白方发送 ply 1 的本方观测和 `own_move="e2e4"`，向黑方发送 ply 1 的黑方观测和 `own_move=None`。黑方行动后，对黑方传它自己的动作，对白方仍传 `None`。不要把对手真实动作传入 `own_move`。

**预算：** host 在行动权交接时设置一次 `deadline = turn_start + 16`，信息集更新、等待、搜索、策略抽样和提交共用它；不能在 `observe` 之后重新领取 16 秒。两个内置 agent 共用一个池，按行动权轮流搜索。用于回归的 `max_rounds` 是固定工作量限制，正式运行保持默认 `None`。

### Observation 的精确含义

复用 `fow_shared.contracts.Observation`，schema version 为 1：

| 字段 | 含义 |
| --- | --- |
| `player`, `side_to_move`, `ply` | 该视角所属方、当前行动方、从公开起始局面算起的半回合数。 |
| `visible_squares` | 可见格坐标，如 `a1`。 |
| `visible_pieces` | 键必须恰好等于 `visible_squares`；FEN 字母表示棋子，`None` 表示可见空格。不可见格不应加入这个映射。 |
| `legal_moves` | 裁判按 FoW 规则允许的 UCI 动作；只有行动方得到其合法动作，非行动方/终局为 `[]`。 |
| `captured_own_piece_at` | 规则允许知道的己方被吃位置，或 `None`；不能额外泄露吃子者。 |
| `halfmove_clock` | 当前规则下保持 `None`，不披露裁判隐藏的 quiet clock。 |
| `terminal`, `outcome` | 终局为 `True`，该方结果为 -1/0/+1；非终局为 `False` / `None`。公共结果字段不随六倍内部估值版本变成 ±6。 |

输入中没有真实棋盘 FEN、对手私有视野、隐藏升变、全盘 material count 或隐藏动作序列。信息集由 agent 自己从允许的观测推导。不要直接用 `python-chess.Board.legal_moves` 当作 FoW 合法动作。

## 4. 接入现有 fow_shared AgentInput

```python
from pair_a_prep.zs21.integration import SharedAgent

agent = SharedAgent(pool, baseline=False, **runtime["agent_kwargs"])
agent.reset("white", seed=2106)
decision = agent.act(turn)  # turn is fow_shared.contracts.AgentInput
```

`turn.history` 必须完整包含从 ply 0 到当前 ply 前一个快照的**本方** `HistoryEvent`，顺序连续。注意两种 `own_move` 的语义：

- `HistoryEvent.own_move` 是该事件观测**之后**我方采取的动作。
- 原生 `observe(..., own_move=...)` 是导致本次观测的、**之前**我方采取的动作。

适配器按这个对应关系补齐尚未处理的观测，保留核心 agent 的完整 I 和搜索树，不把 `turn.belief` 的外部采样集合当作完整 I。它拒绝缺失、改变、重复的历史或行动；agent 内部只读取 `turn.observation`、本方 `history` 和预算。

可运行示例：[examples/shared_runner.py](examples/shared_runner.py)：

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 zs21_runtime/examples/shared_runner.py
```

该示例复用仓库的 `fow_shared.evaluation.play_game` 和既有 `BeliefTracker`。共享 runner 在外部 tracker 更新之后才计时，且将 ply cap 表示为 `stopped_at_ply_limit`；因此它用于接口兼容验证，论文评测应使用下一节的专用 match runner。不要把 capped game 算作真实和棋；示例将其明确输出为 `unfinished_smoke`。本 adapter 不替换共享 runner 的计时或规则实现。

## 5. 独立进程 / 其他语言：JSON Lines

每个服务进程拥有自己的四实例引擎池；两个这样的服务不会共享池。正式比较的“四实例总量”配置应使用同一进程内的专用 match runner；本节用于跨进程接入。

真正的 paper agent 服务：

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess serve
```

每行一个 JSON 请求、对应一行 JSON 响应；标准输出只用于协议，诊断应写 stderr。一个进程服务一局、一个 seat，持有自己的四实例引擎池。EOF 或 `close` 释放资源；新游戏使用新进程。`--baseline` 选择 baseline，`--variant sixfold` 选择对照版本。

| 请求 | 响应 |
| --- | --- |
| `{"type":"start","schema_version":1,"rules_id":"paper2021_fow_no_moves_draw_v1","player":"white","seed":2106,"remaining_seconds":30}` | `{"ok":true,"agent":"zs21-paper","rules_id":"...","schema_version":1}` |
| `{"type":"observe","observation":完整Observation对象,"own_move":null,"remaining_seconds":剩余时间}` | `{"ok":true}` |
| `{"type":"act","remaining_seconds":剩余时间}` | `{"decision":{"move":"...","root_policy":{所有合法动作:概率},"diagnostics":{...}}}` |
| `{"type":"close","remaining_seconds":2}` | `{"ok":true}`，随后进程退出。 |

表中的中文占位说明必须替换成真实 JSON 数据；可用 `dataclasses.asdict(observation)` 产生完整观测。每次请求的 `remaining_seconds` 来自 host 的同一个当前回合截止时间。不能将不同进程的绝对 `perf_counter` 值直接互传，也不能每个请求重新给 16 秒。host 还应独立检查收到响应时是否超时、策略是否完整、动作是否合法。

遇到非法顺序、规则不匹配、推断失败或无有效策略时返回 `{"error":"类型: 原因"}`，随后关闭资源并结束；不伪装随机动作或和棋。`start` 最好总是携带本规则标识；为兼容既有 schema-v1 客户端，省略标识时按本版本解释。公开自定义初始局面使用服务端 `--initial-fen`，由双方提前约定。

### 使用现成 ProcessAgent 客户端

先生成当前 checkout 的启动配置，不要复制别人的绝对路径：

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess make-spec
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess play --white human --black process:zs21_runtime/out/paper-agent.json
```

也可直接调用：

```python
from time import perf_counter
from pair_a_prep.zs21.protocol import ProcessAgent

agent = ProcessAgent("zs21_runtime/out/paper-agent.json", "white", seed=2106)
try:
    deadline = perf_counter() + 16
    agent.observe(initial_white_observation, deadline=deadline)
    decision = agent.act(deadline)
finally:
    agent.close()
```

进程版本每个 seat 都会独立启动四个引擎。正式的 paper-versus-baseline 对比使用内置共享池，避免把两个独立进程的资源配置误当作原实验配置。客户端先发送 EOF 尝试正常清理，超时才终止它创建的进程树。

## 6. 测试与比赛

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess test
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess evaluate --games 2 --output zs21_runtime/out/pilot-001
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess replay zs21_runtime/out/pilot-001 --expected-games 2
```

`evaluate` 从标准开局组织 paper agent 与 baseline 对弈，交替执白/执黑；默认预算 16 秒、完整信息集、M=10^7、L=200 的补样下限。baseline 只搜索一层 FoW 树，叶上使用 Stockfish iterative deepening。省略 `--games` 默认 100 局，但安装、doctor、测试和 smoke **不会自动启动这 100 局**。

每批保存源码/配置/引擎哈希、seed、双方观测、真实裁判棋盘、动作分布、LP gap 和失败。完整日志具有观战权限，不能交给对局中的 agent。`--resume` 只允许相同源码、环境、配置且无失败记录的批次；任何变化使用新的输出目录。`--max-plies` 是诊断中止，不会被本专用 runner 统计为和棋。

此前用户指定的旧版 34 局为 17 胜 / 0 和 / 17 负；它们不是本交付版新跑的 34 局。完整结果留在原本地复现项目，本 PR 不上传庞大的历史失败批次或训练资料。[验证说明](validation/README.md)

## 7. 重建、资源与故障定位

- 预编译 agent 内核在 `pair_a_prep/zs21/native/inference.dll`，源码同目录；匹配的规则标识由 Python 启动时检查。
- 选定引擎和 NNUE 在 `engines/stockfish13-batch-v6/`；完整对应 C++ 源码在 `third_party/stockfish13/src/`。[来源、改动与许可证](THIRD_PARTY.md)
- 在没有对局或 agent 服务运行时，可执行 `build-native` 或 `build-all`。为验证构建且保留随包资产，可运行 `pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 zs21_runtime/scripts/build.py --output zs21_runtime/out/rebuilt`。
- 构建会产生 `build-manifest.json`。重新编译的二进制哈希可能受工具链/构建时间影响；`doctor` 对随包资产做严格比对，替换它们后应登记新版本并重跑测试，不能静默继承原验证结论。没有 AVX2/BMI2 的 Windows CPU 可用 `--generic --output ...` 构建 SSE2 引擎，再显式配置引擎路径；其 16 秒时限需重新测量。
- DLL 错误：确认 clone 完整、Python 为 64 位、从 Pixi 启动；规则版本旧时重建，不能直接换成不匹配的旧 DLL。
- `empty full information set`：检查是否漏掉即时观测、传入了对手动作、跳过/重复 ply，或裁判 FoW 规则与本版本不同。不要用真实棋盘重置 I 来掩盖错误。
- 引擎退出：确认使用随包 v6 引擎和原 NNUE，而非普通未适配的 Stockfish。其王安全假设和本项目 UCI batch 扩展不同。
- LP/超时：后续求解失败会保留本次决策的有效策略；没有有效解时显式失败。历史上两次 `HiGHS Status 0: Not Set` 的根因仍未定位，不能声称全部潜在问题都已消除。

其他 AI 接手时先运行 doctor/test，阅读本手册和实现说明，再修改算法；保持玩家信息隔离、两种 agent 的匹配配置，以及新旧实验版本分离。
