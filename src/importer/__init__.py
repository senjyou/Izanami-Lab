# -*- coding: utf-8 -*-
"""游戏数据导入：把 /api/data/user 抓包快照转换成模拟器的账号配置。

模块划分::

    wire.py        msgpack 流 + KMS(LZ4) 容器解码（纯 Python，零依赖）
    schema.py      实体 typeId → 字段名（只声明本功能用到的表）
    lut.py         运行时查找表 + 模拟器数据的只读访问
    map_user.py    实体行 → ImportPayload（纯函数，无 IO）
    apply.py       合并到 char_config / global_config，备份与审计
    cli.py         命令行入口（python -m src.importer.cli）
    build_luts.py  开发期：从 split_data/ 生成 data/ 下的 LUT
"""

__all__ = ["wire", "schema", "lut", "map_user", "apply", "cli", "build_luts"]
