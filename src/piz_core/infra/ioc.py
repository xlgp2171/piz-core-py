""" 控制反转组件

:version: 0.3.260807
"""
from __future__ import annotations

import inspect
import logging
import threading
import tomllib
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, TypeVar, overload, Generic, Final, Sequence

from piz_core.constants import CORE_TAG, ErrorCode, ConfigConstant, NAMESPACE
from piz_core.deco import validate_types
from piz_core.util import get_class_path, real_path, is_file, path_exists, get_resource_as_stream, get_nested, \
    dict_deep_merge, current_time_millis, method_unavailable_exception, path_stat, LazyMessage

# 捕获返回值类型
T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Qualifier:
    """ 类型名称定义
    """
    name: str
    """ 实例名称 """


class _Container:
    """ 容器配置
    """
    # 实例缓存（格式为k: instance_name, v: instance），存储为单例
    _instance_cache: dict[str, Any] = {}
    # 辅助索引（格式为k: instance_type, v: instance_names）
    _type_index: dict[type, set[str]] = defaultdict(set)
    # 线程锁，保护对共享状态的并发访问
    _lock = threading.RLock()

    def inspect(self) -> MappingProxyType:
        """ 检查容器主缓存（k: 实例名称, v: 实例类型）
        """
        with self._lock:
            return MappingProxyType({k: get_class_path(v) for k, v in self._instance_cache.items()})

    def _get_instance(self, name: str) -> Any:
        """ 获取实例（调用方必须已持有 self._lock） """
        ...
        if name in self._instance_cache:
            logger.debug(LazyMessage(lambda: f"{CORE_TAG}Resolve instance,\t\n\tinstance_name: {name}"))
            return self._instance_cache[name]
        return None

    @validate_types
    def resolve(self, *, instance_type: type | None = None, instance_name: str | None = None,
                     ignore_errors: bool = False) -> Any:
        """ 按名称和/或类型获取已注册的实例

        - 同时传入类型和名称：以类型优先查找，并校验名称是指定名称的实例
        - 只传名称：返回该名称对应的实例
        - 只传类型：返回该类型下唯一注册的实例

        :param instance_type: 期望的实例类型。按名称命中时用于类型校验；未传名称时用于按类型精确查找
        :param instance_name: 实例名称。为 None 时按类型查找
        :param ignore_errors: 是否忽略异常（默认False）
        :raises TypeError: 名称存在，但实例类型与 instance_type 不兼容
        :raises LookupError: 按类型查找时存在多个实例，无法确定
        :raises ValueError: 名称或类型未匹配到任何实例，或两者均未提供
        """
        with self._lock:
            # 若类型设置且不为空类型
            if instance_type is not inspect.Parameter.empty and instance_type:
                # 先绝对匹配命中类型的实例
                if instance_type in self._type_index:
                    instance_names: set[str] = self._type_index[instance_type]
                # 尝试遍历并匹配父子类型
                else:
                    instance_names: set[str] = set()
                    # 获取所有的可能关联类型
                    for k, v in self._type_index.items():
                        try:
                            # 判断输入类型是否是缓存的子类
                            if issubclass(k, instance_type):
                                instance_names |= v
                        except TypeError:
                            continue
                # 若无法按类型进行匹配
                if not instance_names:
                    # 是否忽略异常
                    if not ignore_errors:
                        # 类型无法匹配
                        raise TypeError(ErrorCode.D_110.format_message(get_class_path(instance_type)))
                # 若类型对应名称只有一个则直接返回
                elif len(instance_names) == 1:
                    return self._get_instance(next(iter(instance_names)))
                # 若实例名称存在且匹配，直接返回
                elif instance_name and instance_name in instance_names:
                    return self._get_instance(instance_name)
                # 若类型对应名称有多个且无指定名称则抛出异常
                else:
                    # 是否忽略异常
                    if not ignore_errors:
                        # 类型匹配到多个实例名称
                        raise LookupError(ErrorCode.D_120.format_message(
                            get_class_path(instance_type), "; ".join(instance_names)))
            # 若类型未设置名称设置
            elif instance_name and instance_name in self._instance_cache:
                # 匹配命中名称的实例
                return self._get_instance(instance_name)
        error_hint = ErrorCode.D_130.format_message(
            get_class_path(instance_type) if instance_type else "None", instance_name)
        # 是否忽略异常
        if not ignore_errors:
            # 若都无法匹配
            raise ValueError(error_hint)
        logger.debug(LazyMessage(lambda: f"{CORE_TAG}Ignore error,\t\n\thint: {error_hint}"))
        return None

    @validate_types
    def ensure(self, instance_name: str, instance_func: Callable[[], Any]) -> Any:
        """ 注册实例到容器，若已注册则直接返回实例

        - 若指定名称已存在实例，返回已有实例（幂等）
        - 若实例为 None，抛出 ValueError
        - 同时建立类型索引，支持按类型查找

        :param instance_name: 实例唯一标识名
        :param instance_func: 要注册的实例初始化函数
        :raises ValueError: 实例函数无效
        """
        # 若实例已注册则直接返回
        if (existing := self.resolve(instance_name=instance_name, ignore_errors=True)) is not None:
            logger.debug(LazyMessage(lambda: f"{CORE_TAG}Instance existing,\t\n\tname: {instance_name}"))
            return existing
        # 若实例生成函数为None
        elif instance_func is None or (instance := instance_func()) is None:
            # 生成函数无效
            raise ValueError(ErrorCode.P_111.format_message(instance_name))
        else:
            with self._lock:
                if (existing := self._get_instance(instance_name)) is not None:
                    logger.debug(LazyMessage(lambda: f"{CORE_TAG}Instance existing,\t\n\tname: {instance_name}"))
                    return existing
                # 这个时候再实例化
                self._instance_cache[instance_name] = instance
                logger.info(f"{CORE_TAG}Register instance,\tname: {instance_name},\tclass: {get_class_path(instance)}")
                # 将实例名称加入类型缓存
                self._type_index[type(instance)].add(instance_name)
                return instance

def inject_hook(instance: Any, member_name: str, member: Any):
    """ 注入钩子函数

    :param instance: 实例
    :param member_name: 成员名称
    :param member: 实例成员
    """
    # 若为@inject标记则调用方法一次（注入）
    if getattr(member, "__inject", None) == NAMESPACE:
        getattr(instance, member_name)()


container: Final[_Container] = _Container()
""" 容器处理单例 """


@validate_types
def trigger_hooks(instance: Any, *hook_funcs: Callable[[Any, str, Any], None]):
    """ 扫描实例所有标记的方法并按函数处理（沿 MRO 覆盖父类）

    :param instance: 实例
    :param hook_funcs: 实例初始化时的钩子函数组合（输入为：实例，成员名称，实例成员）
    """
    if not hook_funcs:
        return
    called = set()
    # 扫描实例的所有MRO（包括父类）
    for klass in inspect.getmro(type(instance)):
        # 遍历对应类的所有成员（若重写方法也会被再次调用）
        for member_name, member in vars(klass).items():
            # __init__ 的注入在实例化时已由 wrapper 完成，必须跳过，重写的方法调用也跳过
            if member_name == "__init__" or member_name in called:
                continue
            called.add(member_name)
            # 依次调用每个函数
            for func in hook_funcs:
                func(instance, member_name, member)


class _Environment:
    """ 环境配置
    """
    # 配置缓存（格式为k: path, v: (config, timestamp)）
    _config_cache: dict[str, tuple[dict, int]] = {}
    # 默认配置
    _default_path: str = "config.toml"
    # 线程锁
    _lock = threading.Lock()

    @staticmethod
    def _file_timestamp(path: str) -> int:
        return int(round(path_stat(path).st_mtime * 1000))

    def _load_default(self):
        """ 加载默认配置

        :raises FileNotFoundError: 文件未找到异常
        """
        # 先延迟加载默认配置
        if self.is_stale(self._default_path):
            # 加锁进行延迟加载
            with self._lock:
                # 双重检查
                if self.is_stale(self._default_path):
                    self.set_default_path(self.load_config(self._default_path)[0])

    @staticmethod
    def _load_config(path: str | Path) -> tuple[str, dict]:
        """ 读取配置文件并返回文件路径和配置内容
        """
        # 若文件存在
        if path_exists(_path := real_path(path)) and is_file(_path):
            # 读取toml文件内容
            with get_resource_as_stream(_path, mode="rb") as f:
                config = tomllib.load(f)
            logger.debug(LazyMessage(
                lambda: f"{CORE_TAG}Load toml config,\t\n\tpath: {_path},\t\n\tcontent: {repr(config)}"))
            # 文件绝对路径和配置文件内容
            return _path, config
        # 文件未找到
        raise FileNotFoundError(ErrorCode.C_501.format_message(_path))

    @validate_types
    def is_stale(self, path: str | Path) -> bool:
        """ 文件配置是否已经不是最新（仅检查主配置文件时间戳；非文件配置的 key 恒返回 False）
        """
        if path_exists(_path := real_path(path)):
            return self._file_timestamp(_path) > self._config_cache[_path][1] if _path in self._config_cache else True
        # 文件不存在或时间戳小于缓存时间戳
        return False

    def loaded_paths(self) -> list[str]:
        """ 获取已经加载配置路径
        """
        return list(self._config_cache.keys())

    @validate_types
    def load_config(self, path: str | Path, timestamp: int = -1, force: bool = False) -> tuple[str, int]:
        """ 按条件加载配置并返回文件绝对路径和时间戳

        :param path: 文件路径或相对路径
        :param timestamp: 设置文件的时间戳（默认-1，即采用文件最后修改时间戳）
        :param force: 是否强制更新
        :raises FileNotFoundError: 文件未找到异常
        """
        # 先要获取文件的时间戳
        if path_exists(_path := real_path(path)):
            file_timestamp = self._file_timestamp(_path)
        else:
            # 文件未找到
            raise FileNotFoundError(ErrorCode.C_501.format_message(_path))
        cache_timestamp, _timestamp = -1, max(file_timestamp, timestamp)
        # 若path不存在或者文件时间戳>缓存的时间戳则需要重新加载配置
        if _path not in self._config_cache or _timestamp > (cache_timestamp := self._config_cache[_path][1]) or force:
            # 加载主配置
            _, config = self._load_config(_path)
            # 遍历扩展配置并合并
            for i in get_nested(config, *ConfigConstant.PROFILES_ACTIVE, expected=list, default=[]):
                config = dict_deep_merge(config, self._load_config(real_path(_path,i, parent=True))[1])
            # 设置到缓存（只考虑主文件的时间戳）
            self.set_config(_path, config, _timestamp, merge=False)
        else:
            logger.debug(LazyMessage(lambda: f"{CORE_TAG}Reload rejected,\t\n\targs: {timestamp}ms,\t"
                                             f"\n\tfile: {file_timestamp}ms,\t\n\tcache: {cache_timestamp}ms"))
        return _path, self._config_cache[_path][1]

    @validate_types
    def get_config_value(self, key_path: str, path: str | None = None, default: Any = None) -> Any:
        """ 获取配置对应的值

        :param key_path: 配置的链路（支持"."分隔）
        :param path: 配置路径（默认为None，即加载默认的配置）
        :param default: 若配置无法获取返回的默认值
        :raises FileNotFoundError: 默认配置文件未找到异常
        """
        if path is None:
            self._load_default()
            path = self._default_path
        # 若path为空则使用默认配置
        if path in self._config_cache:
            return get_nested(self._config_cache[path][0], *key_path.split("."), default=default)
        return default

    @validate_types
    def set_config(self, path: str, config: dict, timestamp: int = -1, merge: bool = True):
        """ 设置配置

        :param path: 配置路径
        :param config: 配置内容
        :param timestamp: 配置时间戳（默认-1，即以当前时间戳）
        :param merge: 是否融合同Key的配置，若False则先移除当前配置
        """
        if merge:
            if path in self._config_cache:
                config = dict_deep_merge(self._config_cache[path][0], config)
        else:
            self.remove_config(path)
        # 缓存配置，若时间戳未设置则以当前时间戳进行设置
        self._config_cache[path] = (config, (_timestamp := timestamp if timestamp > 0 else current_time_millis()))
        logger.info(f"{CORE_TAG}Config cached,\tpath: {path},\ttimestamp: {_timestamp}")

    @validate_types
    def remove_config(self, path: str):
        """ 根据key清除缓存
        """
        if path in self._config_cache:
            del self._config_cache[path]
            logger.info(f"{CORE_TAG}Clean config,\tpath: {path}")

    @classmethod
    @validate_types
    def set_default_path(cls, path: str | Path):
        """ 设置默认配置路径
        """
        cls._default_path = real_path(path)

    @property
    def default_path(self) -> str:
        return self._default_path


environment: Final[_Environment] = _Environment()
""" 环境处理单例 """


class BaseDescriptor(Generic[T], ABC):
    """ 描述符基类
    """
    def __init__(self):
        self._attr_name: str = ""

    def __set_name__(self, owner: Any, name: str):
        """ 类初始化完后调用

        :param owner: 描述符的宿主的类型
        :param name: 对应描述符的属性名称
        """
        self._attr_name = name

    @abstractmethod
    def __get__(self, instance: Any, owner: Any = None) -> T:
        """ 描述符对应属性被调用时

        :param instance: 描述符宿主的实例
        :param owner: 描述符的宿主的类型
        """
        raise method_unavailable_exception()

    # def __set__(self, instance: Any, value: T):
    #     # 当前实例设置属性值
    #     instance.__dict__[self._attr_name] = value


class Injected(BaseDescriptor[T]):
    """ 获取实例的描述符
    """
    @validate_types
    def __init__(self, *, instance_type: type[T] | None = None, instance_name: str | None = None):
        """
        :param instance_type: 实例类型（泛型）
        :param instance_name: 实例名称（当类型有多个名称时）
        """
        super().__init__()
        self._type = instance_type
        self._name = instance_name

    # 通过类访问（Sample.prop）返回描述符自身
    @overload
    def __get__(self, instance: None, owner: Any = None) -> "Injected[T]": ...

    # 通过实例访问（Sample().prop）返回解析出的泛型
    @overload
    def __get__(self, instance: Any, owner: Any = None) -> T: ...

    def __get__(self, instance: Any, owner: Any = None) -> T:
        """ 描述符对应属性被调用时

        :param instance: 描述符宿主的实例
        :param owner: 描述符的宿主的类型
        """
        if instance is None:
            return self
        # 首次访问时从容器解析并缓存
        if self._attr_name not in instance.__dict__:
            instance.__dict__[self._attr_name] = container.resolve(
                instance_type=self._type, instance_name=self._name)
        return instance.__dict__[self._attr_name]


class Prop(BaseDescriptor[Any]):
    """ 获取配置的描述符
    """
    @validate_types
    def __init__(self, key_path: str, /, *, default: Any = None, process_func: Callable[[Any], Any] | None = None):
        """
        :param key_path: 配置路线
        :param default: 若配置不存在的默认值
        :param process_func: 数据加工函数
        """
        super().__init__()
        self._key_path = key_path
        self._default = default
        self._process_func = process_func

    def get_value(self) -> Any:
        """ 获取配置值
        """
        value = environment.get_config_value(self._key_path, default=self._default)
        # 加工函数处理数据
        return value if self._process_func is None else self._process_func(value)

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        """ 描述符对应属性被调用时

        :param instance: 描述符宿主的实例
        :param owner: 描述符的宿主的类型
        """
        return self.get_value()

    def __set__(self, instance: Any, value: Any):
        """ 设置参数

        :raises AttributeError: 属性为只读
        """
        # 属性为只读
        raise AttributeError(ErrorCode.C_311.format_message(self._attr_name))
