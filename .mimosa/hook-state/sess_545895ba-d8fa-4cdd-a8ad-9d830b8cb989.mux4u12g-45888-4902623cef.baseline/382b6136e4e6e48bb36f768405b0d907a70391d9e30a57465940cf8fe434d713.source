"""
编码工具模块

提供跨平台的Unicode安全输出功能，解决Windows控制台GBK编码问题。

使用方法:
    from src.utils.encoding_utils import safe_print, setup_console_encoding
    
    # 在脚本开始时调用
    setup_console_encoding()
    
    # 使用safe_print代替print
    safe_print("包含中文的输出 ✓")
"""

import sys
import io
import locale
from typing import Any, Optional


def setup_console_encoding(encoding: str = 'utf-8'):
    """
    配置控制台使用UTF-8编码
    
    Args:
        encoding: 目标编码，默认utf-8
    
    注意:
        Windows用户如果仍看到乱码，请使用以下方法之一：
        1. 使用Windows Terminal代替CMD/PowerShell
        2. 重定向输出到文件: python script.py > output.txt 2>&1
        3. 在PowerShell中运行: chcp 65001; python script.py
    """
    # Windows平台特殊处理
    if sys.platform == 'win32':
        # 尝试设置控制台代码页为UTF-8 (65001)
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # 设置输入和输出代码页
            kernel32.SetConsoleCP(65001)
            kernel32.SetConsoleOutputCP(65001)
            # 尝试设置控制台模式以支持ANSI转义序列
            STD_OUTPUT_HANDLE = -11
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        except Exception as e:
            # 如果设置失败，静默忽略
            pass
    
    # 重新配置stdout和stderr为UTF-8
    try:
        # 检查是否在真实的终端环境中
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding=encoding,
                errors='replace',  # 遇到无法编码的字符时替换为?
                line_buffering=True
            )
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer,
                encoding=encoding,
                errors='replace',
                line_buffering=True
            )
    except (AttributeError, io.UnsupportedOperation):
        # 如果stdout/stderr没有buffer属性（某些IDE环境），跳过
        pass


def safe_print(*args, **kwargs):
    """
    安全的打印函数，自动处理编码错误
    
    使用方法与内置print相同，但会自动处理编码问题。
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        # 如果遇到编码错误，尝试使用ASCII安全模式
        safe_args = []
        for arg in args:
            try:
                safe_args.append(str(arg).encode('ascii', 'replace').decode('ascii'))
            except Exception:
                safe_args.append('[encoding error]')
        print(*safe_args, **kwargs)


def safe_format(text: str, fallback: str = '?') -> str:
    """
    安全地格式化字符串，替换无法编码的字符
    
    Args:
        text: 要格式化的文本
        fallback: 替换字符，默认为'?'
        
    Returns:
        安全的字符串
    """
    try:
        # 尝试编码到当前系统编码
        encoding = sys.stdout.encoding or locale.getpreferredencoding()
        return text.encode(encoding, errors='replace').decode(encoding)
    except Exception:
        # 如果失败，使用ASCII安全模式
        return text.encode('ascii', errors='replace').decode('ascii')


def get_console_encoding() -> str:
    """
    获取当前控制台编码
    
    Returns:
        编码名称
    """
    if hasattr(sys.stdout, 'encoding') and sys.stdout.encoding:
        return sys.stdout.encoding
    return locale.getpreferredencoding() or 'utf-8'


def is_encoding_safe(text: str) -> bool:
    """
    检查文本是否可以安全地在当前控制台输出
    
    Args:
        text: 要检查的文本
        
    Returns:
        True if 可以安全输出
    """
    try:
        encoding = get_console_encoding()
        text.encode(encoding)
        return True
    except UnicodeEncodeError:
        return False


class SafeLogger:
    """
    安全的日志记录器，自动处理编码问题
    
    Example:
        logger = SafeLogger()
        logger.info("战斗开始 ✓")
        logger.error("错误信息 ✗")
    """
    
    def __init__(self, prefix: str = ""):
        self.prefix = prefix
    
    def _log(self, level: str, message: str):
        """内部日志方法"""
        full_message = f"[{level}] {self.prefix}{message}"
        safe_print(full_message)
    
    def info(self, message: str):
        """信息日志"""
        self._log("INFO", message)
    
    def warning(self, message: str):
        """警告日志"""
        self._log("WARN", message)
    
    def error(self, message: str):
        """错误日志"""
        self._log("ERROR", message)
    
    def debug(self, message: str):
        """调试日志"""
        self._log("DEBUG", message)


# 自动初始化（导入时执行）
def _auto_setup():
    """自动配置编码（可选）"""
    # 可以在这里自动调用setup_console_encoding()
    # 但为了给用户更多控制权，默认不自动调用
    pass


if __name__ == "__main__":
    # 测试代码
    print("测试编码工具...")
    print(f"当前控制台编码: {get_console_encoding()}")
    
    setup_console_encoding()
    print(f"配置后编码: {get_console_encoding()}")
    
    # 测试safe_print
    safe_print("\n测试 safe_print:")
    safe_print("中文测试 ✓")
    safe_print("日文测试: びしょ濡れだねー！")
    safe_print("特殊符号: ✓ ✗ ⚠ ★")
    
    # 测试SafeLogger
    logger = SafeLogger(prefix="[测试] ")
    logger.info("信息日志 ✓")
    logger.warning("警告日志 ⚠")
    logger.error("错误日志 ✗")
