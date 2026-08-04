""" 系统（system）处理工具

:version: 0.2.260730
"""
import inspect
import os
import traceback
from dataclasses import dataclass
from types import FrameType
from typing import Callable, ParamSpec, TypeVar


# 捕获任意参数签名
P = ParamSpec("P")
# 捕获返回值类型
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LazyMessage:
    """ 延迟记录器
    """
    func: Callable[[], object]

    def __str__(self):
        return str(self.func())

    __repr__ = __str__


def get_caller_info() -> traceback.FrameSummary:
    """ 获取调用者的栈帧摘要（文件名、行号、函数名、代码片段）
    """
    # 当前帧+调用者帧，避免遍历整个栈
    stack = traceback.extract_stack(limit=2)
    return stack[0] if len(stack) < 2 else stack[-2]

def get_caller_frame() -> FrameType | None:
    """ 获取调用者的活跃帧对象（可访问局部变量、全局变量、代码对象）
    """
    return None if (current := inspect.currentframe()) is None or (
        caller := current.f_back) is None else caller

def method_unavailable_exception() -> NotImplementedError:
    """ 方法未实现异常
    """
    info = get_caller_info()
    return NotImplementedError(f"{os.path.basename(info.filename)}#{info.name}")