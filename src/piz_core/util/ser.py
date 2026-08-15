""" 序列化（serialization）处理工具

:version: 0.3.260813
"""
import json
import pickle
from dataclasses import is_dataclass, fields, InitVar
from datetime import datetime
from pathlib import Path
from typing import Any

from piz_core.const import ErrorCode
from piz_core.deco import validate_types
from piz_core.util.dt import format_datetime
from piz_core.util.fs import get_resource_as_stream
from piz_core.util.reflect import get_class_path


class JsonEncoder(json.JSONEncoder):
    """ 通用JSON编码器（处理包括：datetime，Path，set）
    """
    def default(self, o: Any):
        # datetime类型
        if isinstance(o, datetime):
            return format_datetime(o)
        # Path类型
        if isinstance(o, Path):
            return str(o)
        # set类型
        if isinstance(o, set):
            return list(o)
        return super().default(o)


@validate_types
def read_object(value: str | Path, **kwargs) -> Any:
    """ 从文件中读取 pickle 序列化的对象

    :param value: 文件路径
    :param kwargs: 传递给 pickle.load 的额外参数
    """
    with get_resource_as_stream(value, mode='rb') as rf:
        return pickle.load(rf, **kwargs)

@validate_types
def dump_object(value: str | Path, data: Any, **kwargs):
    """ 将 Python 对象通过 pickle 序列化后写入文件

    :param value: 目标文件路径
    :param data: 待序列化的 Python 对象
    :param kwargs: 传递给 pickle.dump 的额外参数
    """
    with get_resource_as_stream(value, mode='wb') as wf:
        pickle.dump(data, wf, **kwargs)

@validate_types
def dump_json(value: Any, **kwargs) -> str:
    """ 将对象转换为JSON（自带JsonEncoder和ensure_ascii=False）

    :param value: 任意对象
    :param kwargs: json.dumps的参数
    """
    return json.dumps(value, cls=JsonEncoder, ensure_ascii=False, **kwargs)

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
