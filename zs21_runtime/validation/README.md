# 发布验证

本记录对应 `pair-a/zs21-agent-integration`，基于 Pair A 提交 `dfeea4c5067d0b2d3dd0eef52f2527c9653c240f`，包含 #27–#30。2026-10-27 在 Windows x64 上使用本运行包新建的锁定 Pixi 环境验证。

- 完整回归：**612 passed，86.33 秒**，无失败、跳过或错误。包括现有 shared/Pair A 测试、论文算法验证、PR #28 规则、Python/native 对照、新接口和实际 JSON 子进程。
- `doctor`：66 个引擎/原生库/源码/许可文件哈希一致，规则 ABI 正确；实际启动四个单线程 Stockfish 13，支持 batch 查询。
- 原生 Python 和 shared runner 示例各完成两个合法行动，输出 `unfinished_smoke`。它们是接线检查，不是正式对局或棋力成绩。
- 使用随包完整源码重建 EXE/DLL。84 个局面的引擎 value/source/depth/nodes、native 合法动作与终局探针均与随包版相同。重建二进制哈希不同，验证的是上述行为，不声称 bit-for-bit 可复现或涵盖全部局面。
- 八个算法/规则核心文件与已验证的本地 PR #28 适配版逐字节一致。原研究目录中 154 个历史文件 SHA-256 未变；本次未运行新的正式比赛。
- 将 Git 暂存区以 `core.autocrlf=true` 导出到含空格的新目录，复用同一锁定环境；66 个资产校验和真实引擎启动通过，原生接入示例完成两个行动。这验证代码/资源可换目录，不是另一台机器的独立验证。

机器可读摘要见 [release-verification.json](release-verification.json)。安装版本、资源和重建哈希均记录其中。用以下命令复验（从仓库根目录）：

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess doctor
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess test
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess smoke
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 zs21_runtime/examples/shared_runner.py
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 zs21_runtime/scripts/build.py --output zs21_runtime/out/rebuilt
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 zs21_runtime/scripts/verify_build.py zs21_runtime/out/rebuilt
```

历史正式批次只按用户指定前 34 局汇总：主 agent 17 胜、0 和、17 负；此前已独立回放 2,306 次行动。本次只核验原档案未被改动，不重复生成历史成绩，不上传庞大的原始批次。D-29 所记录的两次 HiGHS Not Set 的根因仍未定位；本次成功不消除该已知不确定性。
