""" 事件监听装饰器

:version: 0.2.260814
"""
import weakref
from typing import TypeVar, Callable

from piz_core.const import NAMESPACE, ErrorCode
from piz_core.infra.event import event_bus


# 捕获返回值类型
T = TypeVar("T")


def event_listener(*event_types: type[T]):
    """ 事件监听器装饰器
    """
    def _decorator(func: Callable) -> Callable:
        from piz_core.util import get_func_path, method_kind
        # 若没有设置事件类型则异常
        if not event_types:
            # 事件类型为空
            raise ValueError(ErrorCode.P_102.format_message(f",\tfunc: {get_func_path(func)}"))
        # 获取method_kind对方法的定义
        _, in_cls = method_kind(func)
        # 若是类定义方法
        if in_cls:
            # 标记事件类型
            func.__event_listener = NAMESPACE
            func.__event_type = event_types
        else:
            for i in event_types:
                # 直接按照默认是方法处理
                event_bus.register(i, weakref.ref(func))
        return func
    return _decorator
