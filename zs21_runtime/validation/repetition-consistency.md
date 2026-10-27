# FoW 重复判定一致性修复

来源：[PR #37 的规则审查](https://github.com/Mr-Teal/CS5446_project/pull/37#issuecomment-6431500298)。原共享规则使用 python-chess 的 orthodox 重复判定，可能把仅在 FoW 中可执行的 en passant 权利忽略，从而提前判和。

`fow_shared.values.fog_position_key` 统一局面身份：棋子、行动方、有效易位权和 FoW 有效 EP 权。共享重复判断在保留的 move stack 上回溯，最多检查自最近 pawn move / capture 以来的历史，不更改输入棋盘。`RulesAdapter`、合法动作与终局估值都使用同一入口。ZS21 的 `position_key` 保持原导入接口，指向共享 helper；`RefereeRules` 委托共享裁判，只有旧结果回放的 no-move 开关仍单独处理。

新回归覆盖评论中的在将军状态下 EP、EP 暴露己王、普通合法 EP、无可执行 EP、易位权丢失及颜色镜像，同时核对两裁判的终局、私有观测、合法动作和历史不变性。对前两种情况，八个 ply 后仍非终局；下一次实际第三次重复时判和。修复前新增测试为 **4 failed / 6 passed**，修复后与共享估值和 ZS21 模型的定向回归为 **64 passed**。

PR 的目标已由维护者改为 main，其中 #36 新增测试需要导入仓库已有 `pairb` 模块。因此便携 test 入口显式加入 `pair_b/src`，无需设置额外 PYTHONPATH 或安装整个训练环境；此路径只用于 test 命令。

将修复提交 `edef410` 与当前 main `abfc868` 做隔离组合，没有合并冲突；清除额外 PYTHONPATH 后运行原便携测试入口，**627 passed（80.00 秒），0 failures / errors / skipped**。它包含 main 的五项 #36 接入测试。doctor 校验 66 个资产，加载 native DLL，启动四个单线程 Stockfish 13 并实际估值成功。原 154 个冻结历史文件哈希仍一致。

完整验证结果、精确版本与源文件哈希在 `repetition-consistency.json` 中记录，分别保存 Git blob 与实际测试文件的 SHA-256，并注明两份普通文本发生的 CRLF 检出转换。`release-verification.json` 是初始提交 `00982c9` 的历史验证，保留原样；其“八个核心文件逐字节一致”结论不再描述重构后的 `model.py`。本次不更改 agent 搜索算法、D-09 搜索和棋近似、native ABI 或引擎资产，不重新运行正式比赛。
