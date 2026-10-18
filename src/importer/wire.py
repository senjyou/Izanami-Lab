# -*- coding: utf-8 -*-
"""msgpack 流 + KMS(LZ4) 容器解码（纯 Python，零第三方依赖）。

格式依据（MGGAutoScript 抓包实测，docs/p0_report.md / src/core/kms_stream.py）::

    响应体是 msgpack 流（连续多个对象，不是单个对象），其中可能包含"压缩容器"：

        [ ExtType(code=98, data=msgpack 编码的各块解压后尺寸表),
          bin(lz4 块 1), bin(lz4 块 2), ... ]

    各块 LZ4 解压后按序拼接 = 真实载荷（其本身仍是 msgpack 流）。
    /api/data/user 的典型布局：

        []  [容器]  []  []  []        ← 顶层 5 个对象
        容器解压 → 一个列表，元素是实体行 [typeId, [字段...]]

本模块只负责"字节 → Python 对象"，不认识任何业务语义；字段名在 schema.py。
设计上刻意不依赖 ``msgpack`` / ``lz4`` 包，避免给打包版增加运行时依赖；
开发期测试会用参考实现做逐对象交叉校验（见 tests/test_import_wire.py）。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Iterator, List, Sequence, Tuple

__all__ = [
    "WireError",
    "ExtType",
    "Timestamp",
    "KMS_EXT_CODE",
    "unpack_stream",
    "is_kms_container",
    "decompress_container",
    "extract_rows",
    "rows_by_type",
]

KMS_EXT_CODE = 98
_TIMESTAMP_EXT_CODE = -1


class WireError(ValueError):
    """响应字节不符合 msgpack / KMS 容器格式。"""


@dataclass(frozen=True)
class ExtType:
    """msgpack 扩展类型（KMS 尺寸表、时间戳等）。"""

    code: int
    data: bytes


@dataclass(frozen=True)
class Timestamp:
    """msgpack timestamp 扩展（ext -1）解码结果。"""

    seconds: int
    nanoseconds: int = 0

    def __str__(self) -> str:  # 与 msgpack 库的 repr 保持一致的阅读体验
        return f"Timestamp(seconds={self.seconds}, nanoseconds={self.nanoseconds})"


# ─────────────────────────────── msgpack 读取器 ───────────────────────────────


class _Reader:
    """在 bytes 上顺序解 msgpack 对象。"""

    __slots__ = ("buf", "pos", "end")

    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.pos = 0
        self.end = len(buf)

    # -- 基础读取 --
    def _take(self, n: int) -> bytes:
        pos = self.pos
        new = pos + n
        if new > self.end:
            raise WireError(f"msgpack 截断：偏移 {pos} 需要 {n} 字节，剩余 {self.end - pos}")
        self.pos = new
        return self.buf[pos:new]

    def _u8(self) -> int:
        pos = self.pos
        if pos >= self.end:
            raise WireError(f"msgpack 截断：偏移 {pos} 无字节可读")
        self.pos = pos + 1
        return self.buf[pos]

    def _unpack(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self._take(size))[0]

    # -- 对象 --
    def read(self) -> Any:
        b = self._u8()

        if b <= 0x7F:  # positive fixint
            return b
        if b >= 0xE0:  # negative fixint
            return b - 0x100
        if 0x80 <= b <= 0x8F:  # fixmap
            return self._map(b & 0x0F)
        if 0x90 <= b <= 0x9F:  # fixarray
            return self._array(b & 0x0F)
        if 0xA0 <= b <= 0xBF:  # fixstr
            return self._str(b & 0x1F)
        if b == 0xC0:
            return None
        if b == 0xC2:
            return False
        if b == 0xC3:
            return True
        if b == 0xC4:
            return self._take(self._u8())
        if b == 0xC5:
            return self._take(self._unpack(">H"))
        if b == 0xC6:
            return self._take(self._unpack(">I"))
        if b == 0xC7:
            n = self._u8()
            return self._ext(self._u8(), self._take(n))
        if b == 0xC8:
            n = self._unpack(">H")
            return self._ext(self._u8(), self._take(n))
        if b == 0xC9:
            n = self._unpack(">I")
            return self._ext(self._u8(), self._take(n))
        if b == 0xCA:
            return self._unpack(">f")
        if b == 0xCB:
            return self._unpack(">d")
        if b == 0xCC:
            return self._u8()
        if b == 0xCD:
            return self._unpack(">H")
        if b == 0xCE:
            return self._unpack(">I")
        if b == 0xCF:
            return self._unpack(">Q")
        if b == 0xD0:
            return self._unpack(">b")
        if b == 0xD1:
            return self._unpack(">h")
        if b == 0xD2:
            return self._unpack(">i")
        if b == 0xD3:
            return self._unpack(">q")
        if b == 0xD4:
            return self._ext(self._u8(), self._take(1))
        if b == 0xD5:
            return self._ext(self._u8(), self._take(2))
        if b == 0xD6:
            return self._ext(self._u8(), self._take(4))
        if b == 0xD7:
            return self._ext(self._u8(), self._take(8))
        if b == 0xD8:
            return self._ext(self._u8(), self._take(16))
        if b == 0xD9:
            return self._str(self._u8())
        if b == 0xDA:
            return self._str(self._unpack(">H"))
        if b == 0xDB:
            return self._str(self._unpack(">I"))
        if b == 0xDC:
            return self._array(self._unpack(">H"))
        if b == 0xDD:
            return self._array(self._unpack(">I"))
        if b == 0xDE:
            return self._map(self._unpack(">H"))
        if b == 0xDF:
            return self._map(self._unpack(">I"))
        raise WireError(f"未知 msgpack 类型字节 0x{b:02x}（偏移 {self.pos - 1}）")

    def _str(self, n: int) -> str:
        raw = self._take(n)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:  # 游戏文本正常是 UTF-8；损坏时给出可定位的报错
            raise WireError(f"msgpack 字符串不是合法 UTF-8（偏移 {self.pos - n}）: {exc}") from exc

    def _array(self, n: int) -> List[Any]:
        read = self.read
        return [read() for _ in range(n)]

    def _map(self, n: int) -> dict:
        read = self.read
        out = {}
        for _ in range(n):
            key = read()
            try:
                out[key] = read()
            except TypeError as exc:  # 不可哈希的 key（本项目数据里未出现）
                raise WireError(f"msgpack map 出现不可哈希 key: {key!r}") from exc
        return out

    def _ext(self, code: int, data: bytes) -> Any:
        if code >= 0x80:  # ext type 是有符号 int8
            code -= 0x100
        if code == _TIMESTAMP_EXT_CODE:
            return _decode_timestamp(data)
        return ExtType(code, data)


def _decode_timestamp(data: bytes) -> Timestamp:
    n = len(data)
    if n == 4:
        return Timestamp(struct.unpack(">I", data)[0], 0)
    if n == 8:
        value = struct.unpack(">Q", data)[0]
        # msgpack spec: 30-bit nanoseconds | 34-bit seconds
        return Timestamp(value & 0x3FFFFFFFF, value >> 34)
    if n == 12:
        nanos, seconds = struct.unpack(">Iq", data)
        return Timestamp(seconds, nanos)
    raise WireError(f"非法 timestamp 扩展长度 {n}")


# ─────────────────────────────── 对外接口 ───────────────────────────────


def unpack_stream(data: bytes) -> List[Any]:
    """按顺序解出 msgpack 流里的全部顶层对象（不是只解第一个）。"""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("unpack_stream 需要 bytes")
    reader = _Reader(bytes(data))
    out: List[Any] = []
    while reader.pos < reader.end:
        out.append(reader.read())
    return out


def is_kms_container(obj: Any) -> bool:
    """判断对象是否为 KMS 压缩容器：[ExtType(98, 尺寸表), bin, ...]。"""
    return (
        isinstance(obj, list)
        and len(obj) >= 2
        and isinstance(obj[0], ExtType)
        and obj[0].code == KMS_EXT_CODE
    )


def decompress_container(container: Sequence[Any]) -> bytes:
    """解压 KMS 容器：尺寸表给出每块解压后长度，逐块 LZ4 解压并拼接。"""
    if not is_kms_container(container):
        raise WireError("不是 KMS 容器")
    sizes = unpack_stream(container[0].data)
    blocks = list(container[1:])
    if len(blocks) > len(sizes):
        raise WireError(f"KMS 容器块数 {len(blocks)} 多于尺寸表 {len(sizes)}")

    out = bytearray()
    for index, block in enumerate(blocks):
        if not isinstance(block, (bytes, bytearray)):
            raise WireError(f"KMS 容器第 {index} 块不是二进制: {type(block).__name__}")
        expected = sizes[index]
        if not isinstance(expected, int) or expected < 0:
            raise WireError(f"KMS 尺寸表第 {index} 项非法: {expected!r}")
        out += _lz4_block_decompress(bytes(block), expected)
    return bytes(out)


def _lz4_block_decompress(src: bytes, expected_size: int) -> bytes:
    """LZ4 block 格式解压（无帧头，输出长度由外部尺寸表给出）。"""
    dst = bytearray(expected_size)
    si = 0
    di = 0
    n = len(src)

    while si < n:
        token = src[si]
        si += 1

        literal_len = token >> 4
        if literal_len == 15:
            while True:
                if si >= n:
                    raise WireError("LZ4 截断：扩展字面量长度越界")
                extra = src[si]
                si += 1
                literal_len += extra
                if extra != 255:
                    break

        if literal_len:
            end_lit = si + literal_len
            if end_lit > n:
                raise WireError("LZ4 截断：字面量越界")
            end_dst = di + literal_len
            if end_dst > expected_size:
                raise WireError("LZ4 输出越界：字面量超出尺寸表")
            dst[di:end_dst] = src[si:end_lit]
            si = end_lit
            di = end_dst

        if si >= n:  # 最后一个 sequence 只有字面量
            break

        if si + 2 > n:
            raise WireError("LZ4 截断：缺少 match offset")
        offset = src[si] | (src[si + 1] << 8)
        si += 2
        if offset == 0 or offset > di:
            raise WireError(f"LZ4 offset 非法: {offset}（已输出 {di}）")

        match_len = token & 0x0F
        if match_len == 15:
            while True:
                if si >= n:
                    raise WireError("LZ4 截断：扩展 match 长度越界")
                extra = src[si]
                si += 1
                match_len += extra
                if extra != 255:
                    break
        match_len += 4

        end_dst = di + match_len
        if end_dst > expected_size:
            raise WireError("LZ4 输出越界：match 超出尺寸表")

        start = di - offset
        if offset >= match_len:
            dst[di:end_dst] = dst[start:start + match_len]
            di = end_dst
        else:
            # 重叠复制（offset < length），必须逐字节
            for _ in range(match_len):
                dst[di] = dst[start]
                di += 1
                start += 1

    if di != expected_size:
        raise WireError(f"LZ4 输出长度不符：得到 {di}，尺寸表要求 {expected_size}")
    return bytes(dst)


def _iter_rows(obj: Any) -> Iterator[Tuple[int, list]]:
    """从任意嵌套里挑出实体行 [typeId, [字段...]]。"""
    if isinstance(obj, list):
        if len(obj) == 2 and isinstance(obj[0], int) and isinstance(obj[1], list) and not isinstance(obj[0], bool):
            yield (obj[0], obj[1])
            return
        for item in obj:
            yield from _iter_rows(item)


def extract_rows(data: bytes) -> List[Tuple[int, list]]:
    """响应字节 → 实体行列表 [(typeId, fields), ...]。

    自动展开所有 KMS 容器；顶层与内层里的实体行都会被收集。
    """
    rows: List[Tuple[int, list]] = []
    for obj in unpack_stream(data):
        if is_kms_container(obj):
            payload = decompress_container(obj)
            for inner in unpack_stream(payload):
                rows.extend(_iter_rows(inner))
        else:
            rows.extend(_iter_rows(obj))
    return rows


def rows_by_type(rows: Sequence[Tuple[int, list]]) -> dict:
    """按 typeId 分组，保持原始顺序。"""
    out: dict = {}
    for type_id, fields in rows:
        out.setdefault(type_id, []).append(fields)
    return out
