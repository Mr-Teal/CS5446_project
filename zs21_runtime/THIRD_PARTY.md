# Stockfish 13：来源、改动与许可证

随包的 `engines/stockfish13-batch-v6/stockfish13.exe` 是经过本项目修改的 Stockfish 13，不是上游未经修改的官方二进制。源头为 [official-stockfish/Stockfish commit 3597f1942ec6f2cfbd50b905683739b0900ff5dd](https://github.com/official-stockfish/Stockfish/tree/3597f1942ec6f2cfbd50b905683739b0900ff5dd)。

完整对应源代码位于 `third_party/stockfish13/src/`，包括修改后的文件与需要的 headers/NNUE/Syzygy 源码。Stockfish 的作者版权头保留，GPLv3 文本位于 [third_party/stockfish13/Copying.txt](third_party/stockfish13/Copying.txt)，引擎目录也附相同文本。修改版不提供超出原许可证的保证。原网络 `nn-62ef826d1a6d.nnue` 随包提供，SHA-256 为 `62ef826d1a6d11b9e814188025aa02a60815c037292e0ef9bbb9bf4f724e5e63`。

本项目在 2026-10-25 至 2026-10-26 的集成中修改了清理和输入路径：

1. 单线程查询的状态清理改为等价的稀疏/延迟清理，避免为独立 depth-1 查询反复清空大量无用内存。
2. 在 FoW 允许但标准棋通常不可达的多重受攻局面中，检测 king 目标攻击时先移去 king 的起点占位，修补原输入假设。
3. 添加可选 `ZS Batch Protocol` / `zs_batch`，一次传输至多 64 个独立、共享截止时间的 depth-1 查询；每个查询仍清除搜索状态，不共享前一棋盘搜索收益。

额外的 FoW 终局、近一步吃王、mate 映射、仅 UCI 输入的 en-passant 修正由 Python adapter 完成，见 `pair_a_prep/zs21/engine.py`。没有把 Stockfish 改成整个 FoW 搜索器。

构建使用随包 Pixi 锁定的 conda-forge GCC 16.2.0，完整编译命令在 `scripts/build.py` 中生成。默认 Windows x64 AVX2/BMI2、静态运行库、NNUE 外部文件；`--generic` 生成 SSE2 版本。构建不依赖原机器路径，也不需要另找未提供的源文件。`assets.manifest.json` 记录随包二进制、网络和源文件哈希。

本项目的棋盘资源和其他共享模块来自本仓库原有代码，未复制成另一份。此说明不更改其他代码的原有许可。
