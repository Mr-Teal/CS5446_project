# 实现边界与复现参数

算法核心复制自已通过 PR #28 适配验证的本地版本，目标是 arXiv:2106.06068v2。原论文在仓库根目录 `2106.06068v2.pdf`。完整选择依据和不确定性见 [decisions.md](decisions.md)；其中的旧 `sources/`、`results/` 路径是本地研究档案路径，不是本交付包已经附带的文件。不要用文档中的历史“待实现”状态覆盖下面的当前状态。

| 项目 | 当前实现 |
| --- | --- |
| 信息集 | 完整 I 用 C++ 保留，Python 版本用于 oracle；搜索根 I' 与完整 I 区分，L=200 为补样下限，不是 I 的容量上限。 |
| Transposition | D-09 的等价局面合并，忽略隐藏 draw history；不等于仓库旧 BeliefTracker 的逐历史不合并模式。 |
| 求解 | Sequence-form LP，SciPy/HiGHS dual simplex；不是独立 PCFR+ 原型。 |
| 子博弈 | Algorithm 12 / 15 的 depth-limited 1-KLSS，reach-maxmargin 与 reach-resolving，保留旧策略/树，支持集引导展开。 |
| 主叶估值 | Stockfish 13 depth 1；cp/100 为 pawn units，再 tanh(x/6)。 |
| 六倍对照 | 6*tanh(x/6)，真实胜负 ±6；主版本 ±1，和棋两者都 0。公共 observation.outcome 保持 -1/0/+1。 |
| Mate | 主版本 sign(n)*0.9*0.78^(abs(n)-1)；mate 0 在 FoW 非终局时按被将死方取 -0.9；对照同比放大；优先采用真实 FoW 终局。 |
| 信息项 | D.3 正文的负惩罚；对当前 I' 均匀、底 2、候选动作后的即时观测熵，M=10^7。 |
| Gift / B | 统一我方收益视角、对手取 min、非负 gift 加到 B，保留旧 B 的归一化/复制贡献。 |
| 零判定 | 模式判断 epsilon=1e-15；支持集 threshold=1e-9。 |
| LP 验收 | 完整博弈 flow/gap 阈值 1e-8；仅证书超差时在同一期限内用更严 solver tolerance 重试。 |
| Baseline | 与主 agent 共用实现，仅 FoW 树深为 1，Stockfish 叶迭代加深。 |
| 预算和资源 | 默认每步 16 秒，从行动权交接开始；共享四个单线程 SF13，LP 一线程，一次一局。 |
| PR #28 | 行动方无 FoW 合法动作判和；真正和棋叶值 0，不调用 Stockfish；信息集过滤同时检查这种终局。 |

规则标识 `paper2021_fow_no_moves_draw_v1`。裁判优先级为 king capture → fifty-move → threefold repetition → no legal moves。最后一项是团队 PR #28 明确选择的项目规则；未声称全部行为与 Chess.com 平台一致。搜索中的 possible-draw cap 与裁判真实 W/D/L 分开；标准棋 checkmate/stalemate 本身不是 FoW 终局。

主程序没有训练或微调 NNUE；使用固定 SF13 网络。没有使用 Pair B 的模型。不能把近似叶值、局面合并和采样的工程 agent 描述为继承了精确模型全部理论安全保证。

发布集成新增了相对 checkout 的配置发现、JSON 进程服务、共享 AgentInput 适配器和最小 Pixi 环境。`SharedAgent` 重放本方历史，而不相信外部采样 belief 等于完整 I；其宿主 shared runner 的计时/cap 语义不同，正式评测使用 `zs21.match`。所有对局默认失败显式报告，不以随机动作补救算法失败。

已知未解决问题包括历史两次 HiGHS Not Set 的根因，以及论文/公开代码无法完全确定的作者实现细节。旧版 34 局 17/0/17 不能证明本实现优于 baseline，也不能视作新交付版重新跑出的成绩。
