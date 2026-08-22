""" 标识工具

:version: 0.3.260822
"""
import functools
import uuid
from typing import Callable

from piz_core.const import ErrorCode
from piz_core.deco import validate_types
from piz_core.util.reflect import method_kind, get_func_path


@validate_types
def next_uuid(simple: bool = False) -> str:
    """ 生成UUID
    """
    _id = str(uuid.uuid1())
    return _id.replace("-", "") if simple else _id

@validate_types
def func_identity(func: Callable) -> int:
    """ 获取方法的唯一标识

    - 普通函数：直接用id(func)
    - bound method：用(id(self)和id(函数))的元组哈希值
    - 不支持functools.partial类型

    :raises TypeError:
    """
    _, in_class = method_kind(func)

    if in_class and (_self := getattr(func, "__self__", None)) is not None and (
            _func := getattr(func, "__func__", None)) is not None:
        return hash((id(_self), id(_func)))
    # 处理 functools.partial —— 用 isinstance 让 IDE 正确推断类型
    elif isinstance(func, functools.partial):
        raise TypeError(ErrorCode.S_232.format_message(get_func_path(func)))
    return id(func)