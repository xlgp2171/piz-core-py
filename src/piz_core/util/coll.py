""" 集合（collection）处理工具

:version: 0.3.260812
"""
import random
from dataclasses import is_dataclass, fields, InitVar
from typing import Callable, Any, Mapping, Sequence, TypeVar

from piz_core.constants import ErrorCode
from piz_core.deco import validate_types
from piz_core.util.reflect import get_class_path
from piz_core.util.valid import is_param_object


T = TypeVar("T")
_MISSING = object()
""" 哨兵对象 """


@validate_types
def split_to_set(value: str, separator: str, process_func: Callable[[str], str] | None = None) -> set[str]:
    """ 将字符串按分隔符分隔为set集合

    :param value: 源字符串
    :param separator: 分隔符
    :param process_func: 切分后的字符串处理函数
    """
    return {process_func(i) if process_func is not None else i for i in value.split(separator)}

@validate_types
def shuffle(value: set | list) -> list:
    """ 将集合或列表随机打乱并返回列表
    """
    v = list(value) if isinstance(value, set) else value
    random.shuffle(v)
    return v

@validate_types
def extract_value(value: dict[str, Any], name: str, *, error_hint: str = "") -> Any:
    """ 从参数字典中获取值

    - 先按名字/点号精确解析
    - 若按名字解析失败则向唯一实体参数获取

    :param value: 参数字典
    :param name: 属性或键名称
    :param error_hint: 获取失败的附加消息
    :raises ValueError: 字段未找到异常
    :raises KeyError: Mapping中没有找到对应的key异常
    :raises AttributeError: 对象中没有找到attr异常
    """
    # 若直接匹配则直接返回
    if name in value:
        return value[name]
    # 若是链路
    if "." in name:
        root, rest = name.split(".", 1)
        # 查看字典中是否存在第一个链路（如参数为user:User，链路为#{user.name}）
        if root in value:
            # 按链路获取值
            return deep_get(value[root], *rest.split("."))
    # 若唯一参数且是实体（dataclass/对象）则从内部获取字段值
    if len(value) == 1 and is_param_object(item := next(iter(value.values()))):
        return deep_get(item, *name.split("."))
    # 字段未找到
    raise ValueError(ErrorCode.P_101.format_message(name, error_hint))

@validate_types
def deep_get(value: Any, *keys: str, default: Any = None, ignore_errors: bool = False) -> Any:
    """ 获取指定键路径的值（支持Mapping和对象）

    :param value: 字典或对象
    :param keys: 键路径（支持多级嵌套）
    :param default: 键不存在或属性不存在时返回的默认值（默认None）
    :param ignore_errors: 是否忽略获取时的异常（默认False）
    :raises KeyError: Mapping中没有找到对应的key异常
    :raises AttributeError: 对象中没有找到attr异常
    """
    if value is None or not keys:
        return default
    for key in keys:
        if isinstance(value, Mapping):
            value = value.get(key, _MISSING) if ignore_errors else value[key]
        else:
            value = getattr(value, key, _MISSING) if ignore_errors else getattr(value, key)
        # 若没有值则直接返回默认
        if value is _MISSING:
            return default
    return value

@validate_types
def get_nested(value: Mapping | None, *keys: str, expected: type | None = None, default: Any = None) -> Any:
    """ 从源字典中获取指定键路径的值，并验证其类型

    :param value: 源字典
    :param keys: 键路径（支持多级嵌套）
    :param expected: 期望的返回值类型（默认None）
    :param default: 键不存在或类型不匹配时返回的默认值（默认None）
    """
    if not value or not keys:
        return default
    elif len(keys) == 1:
        v = value.get(keys[0], default)
    else:
        v = get_nested_as_dict(value, *keys[:-1]).get(keys[-1], default)
    return default if expected and not isinstance(v, expected) else v

@validate_types
def get_nested_as_dict(value: Mapping | None, *keys: str) -> dict:
    """ 从源字典中获取指定键路径对应的字典

    :param value: 源字典
    :param keys: 键路径，支持多级嵌套
    """
    if not value or not keys:
        return {}
    elif len(keys) == 1:
        return get_as_dict(value, keys[0])
    else:
        v: dict | None = None

        for i in keys:
            v = get_as_dict(value if v is None else v, i)
        return v if v else {}

@validate_types
def get_as_dict(value: Mapping, key: str) -> dict:
    """ 从字典中获取指定键的值，并确保返回值为字典类型

    :param value: 源字典
    :param key: 要获取的键名
    """
    return dict(v) if value and key in value and isinstance(v := value.get(key), Mapping) else {}

@validate_types
def dict_deep_merge(value: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """ 字典深层合并（遍历每一层进行合并）

    - 字典类型是直接合并，若相同内容，则override覆盖value
    - 序列类型直接替换

    :param value: 目标字典
    :param override: 需要合并的字典
    """
    result = dict(value)
    # 遍历字典覆盖和替换
    for key, override_v in override.items():
        # 将原字典没有的key进行合并
        if key not in result:
            result[key] = override_v
            continue
        # 获取源字典的key对应的值
        source_v = result[key]
        # 递归时保持类型一致
        if isinstance(source_v, Mapping) and isinstance(override_v, Mapping):
            # 若是Mapping类型则根据key进行合并
            result[key] = dict_deep_merge(source_v, override_v)
        elif isinstance(source_v, Sequence) and isinstance(override_v, Sequence) and not isinstance(
                source_v, (str, bytes)) and not isinstance(override_v, (str, bytes)):
            # 序列直接替换
            result[key] = list(override_v)
        else:
            result[key] = override_v
    return result

@validate_types
def sequence_merge(
        value: Sequence[T] | None, extra: Sequence[T] | None, *, key_func: Callable[[T], Any] | None = None) -> list[T]:
    """ 合并并可选去重（以第一次出现的顺序为主）

    :param value: 目标序列
    :param extra: 需要合并的序列
    :param key_func: 去重函数（None: 不去重; id: 复杂类型; (lambda x:x): 简单类型）
    """
    result: list[T] = []
    unique: set = set()

    for seq in (value, extra):
        if seq is None:
            continue
        for i in seq:
            if key_func is not None:
                if (k := key_func(i)) in unique:
                    continue
                unique.add(k)
            result.append(i)
    return result

@validate_types
def dataclass_values(value: Any, *, error_hint: str = "") -> tuple:
    """ 将dataclass按顺序平铺

    :param value: dataclass实例
    :param error_hint: 非dataclass的附加消息
    :raises TypeError: 非dataclass实例
    """
    if not is_dataclass(value):
        raise TypeError(ErrorCode.P_310.format_message("dataclass", get_class_path(value), error_hint))
    return tuple(getattr(value, f.name) for f in fields(value) if not isinstance(f.type, InitVar))