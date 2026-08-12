""" 事件监听发布组件

:version: 0.3.260812
"""
from __future__ import annotations

import inspect
import logging
import weakref
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar, Final

from piz_core.constants import CORE_TAG, NAMESPACE
from piz_core.deco import validate_types
from piz_core.util import current_time_millis, get_func_name, get_class_path


# 捕获返回值类型
T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass
class BaseEvent:
    """ 基础事件
    """
    # 事件时间戳
    timestamp: int = field(default_factory=lambda: current_time_millis(), init=False)

    def __str__(self):
        return f"[{self.__class__.__qualname__}]timestamp: {self.timestamp}"


class _EventBus:
    """同步事件总线：同步发布，同步执行
    """
    # 监听器集合
    _listeners: dict[type[BaseEvent], list[weakref.ReferenceType[Callable[[BaseEvent], Any]]]] = defaultdict(list)

    @validate_types
    def register(self, event_type: type[T], ref_listener_func: weakref.ReferenceType[Callable[[BaseEvent], Any]]):
        """ 注册监听器

        :param event_type: 事件类型
        :param ref_listener_func: 监听实现
        """
        if ref_listener_func not in self._listeners[event_type]:
            self._listeners[event_type].append(ref_listener_func)
            listener_func = ref_listener_func()
            logger.info(f"{CORE_TAG}Registered listener,\tevent: {get_class_path(event_type)},"
                        f"\tlistener: {get_func_name(listener_func)}")

    @validate_types
    def unregister(self, event_type: type[T], listener_func: Callable[[T], Any]):
        """注销监听器

        :param event_type: 事件类型
        :param listener_func: 监听实现
        """
        if listeners := self._listeners.get(event_type):
            for ref in list(listeners):
                # 对弱引用的处理
                if (func := ref()) is not None and func == listener_func:
                    listeners.remove(ref)
                    logger.info(f"{CORE_TAG}Unregistered listener,"
                                f"\tevent: {get_class_path(event_type)},\tlistener: {get_func_name(listener_func)}")
                    break
            # 尝试清空类型键
            if not listeners:
                del self._listeners[event_type]

    @validate_types
    def publish(self, event: BaseEvent):
        """ 时间发布
        """
        # 解析父类事件也一并响应
        for klass in inspect.getmro(event_type := type(event)):
            if isinstance(klass, type) and issubclass(klass, BaseEvent) and klass in self._listeners:
                removed, listeners = [], self._listeners[klass]

                for ref in listeners:
                    # 引用目标已被回收
                    if (func := ref()) is None:
                        removed.append(ref)
                        continue
                    try:
                        func(event)
                    except Exception:
                        logger.error(f"Error in listener,\tevent: {get_class_path(event_type)},"
                                     f"\tfunc: {get_func_name(func)}", exc_info=True)
                # 清理死引用，否则会越积越多
                for ref in removed:
                    listeners.remove(ref)
                if not listeners:
                    del self._listeners[klass]

    def clear(self):
        """ 清空所有监听器
        """
        self._listeners.clear()

def register_hook(instance: Any, member_name: str, member: Any):
    """ 注入钩子函数

    :param instance: 实例
    :param member_name: 成员名称
    :param member: 实例成员
    """
    # 若为@event_listener标记则将方法注册
    if getattr(member, "__event_listener", None) == NAMESPACE:
        func = getattr(instance, member_name)
        # 区分weakref的构造方式（WeakMethod为类方法）
        ref_func = weakref.WeakMethod(func) if hasattr(func, "__self__") else weakref.ref(func)
        # 将方法注入每个事件（采用弱引用方便释放）
        for i in func.__event_type:
            event_bus.register(i, ref_func)


event_bus: Final[_EventBus] = _EventBus()
""" 事件处理单例 """
