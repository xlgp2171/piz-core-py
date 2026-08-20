""" 数据库相关处理工具

:version: 0.3.260820
"""
import inspect
import re
from dataclasses import is_dataclass, fields
from typing import Any, TypeVar, overload

from piz_core.const import ErrorCode
from piz_core.deco import validate_types
from piz_core.util.valid import is_param_object
from piz_core.util.reflect import get_class_path, get_parameters, has_kwargs_param
from piz_core.util.prim import regex_extract_all
from piz_core.util.coll import deep_get, extract_value


# 捕获返回值类型
T = TypeVar("T")
_PARAM_PATTERN = re.compile(r'#{([\w.]+)}')
""" 参数规范正则 """


@validate_types
def build_params(arguments: dict[str, Any], names: list[str]) -> list | tuple:
    """ 构建函数参数

    :param names: 参数字段
    :param arguments: 参数字典
    """
    # 若是唯一参数且类型为list或tuple则对每个元素提取参数值
    if len(arguments) == 1 and isinstance(item := next(iter(arguments.values())), (list, tuple)):
        return [tuple(deep_get(i, *name.split(".")) for name in names) for i in item]
    # 按照属性任意提取参数值
    return tuple(extract_value(arguments, name) for name in names)

def _is_row_data(value: Any) -> bool:
    """ 是否是row数据（包括序列数据或dict数据或实体数据）
    """
    return isinstance(value, (tuple, list, dict)) or is_param_object(value)

def _to_row(item: Any, *, error_hint: str = "") -> tuple:
    """ 转换为tuple数据

    :raises TypeError: 类型不支持
    """
    if isinstance(item, (tuple, list)):
        return tuple(item)
    if is_dataclass(item):
        return tuple(getattr(item, i.name) for i in fields(item))
    if isinstance(item, dict):
        return tuple(item.values())
    if is_param_object(item):
        return tuple(vars(item).values())
    # 类型不持支
    raise TypeError(ErrorCode.P_311.format_message(get_class_path(item), error_hint))

@validate_types
def build_sql_and_params(sql: str, arguments: dict[str, Any], *, error_hint: str = "") -> tuple[str, list | tuple]:
    """ 返回待执行的SQL语句和SQL参数（参数为list表示批量，tuple表示单条）

    - 批量判定标准（唯一参数+有值列表或有值元组+首元素是row数据）

    :param sql: 用户配置的SQL
    :param arguments: 参数字典
    :param error_hint: 异常后的附加消息
    :raises TypeError: 类型不支持
    :raises ValueError: 批量值长度不一致; 字段值获取异常; 参数值为空集合; 行数据为空; 不支持集合嵌套
    """
    # 获取参数名称集合
    names = regex_extract_all(sql, _PARAM_PATTERN)
    # 批量判定（唯一参数+有值列表或有值元组+首元素是row数据）
    if len(arguments) == 1 and isinstance(
            seq := next(iter(arguments.values())), (list, tuple)) and seq and _is_row_data(seq[0]):
        name = next(iter(arguments))
        # 若整体绑定行列表（VALUES(#{values})）
        if len(names) == 1 and names[0] == name:
            rows = [_to_row(i, error_hint=f"{error_hint},\targs: {name}") for i in seq]
            # 若数据为[]或者()则无效
            if not rows[0]:
                # 行数据为空
                raise ValueError(ErrorCode.P_332.format_message(name, error_hint))
            # 若批量数据每行不一致
            for i in rows:
                if len(i) != len(rows[0]):
                    # 长度不一致
                    raise ValueError(ErrorCode.P_331.format_message(len(rows[0]), len(i), name, error_hint))
            return _PARAM_PATTERN.sub(",".join("?" * len(rows[0])), sql), rows
        # 若为按占位符名逐元素提取（VALUES(#{uid},#{age})）
        try:
            rows = [tuple(deep_get(i, *_name.split(".")) for _name in names) for i in seq]
        except (AttributeError, KeyError, TypeError) as e:
            # 字段值获取异常
            raise ValueError(ErrorCode.P_103.format_message(name, error_hint)) from e
        return _PARAM_PATTERN.sub("?", sql), rows
    # 逐占位符解析，标量序列展开为占位符组（生成器迭代）
    params = []
    # 不读取Match，按regex_extract_all与sub的同序约定消费resolved
    def _repl(m: re.Match) -> str:
        value = extract_value(arguments, _name := m.group(1))
        # 若是集合数据（IN语句）
        if isinstance(value, (list, tuple)):
            # 若为空集合
            if not value:
                # 参数值为空集合
                raise ValueError(ErrorCode.P_104.format_message(_name, error_hint))
            # 不支持的方式
            if _is_row_data(value[0]):
                # 不支持集合嵌套
                raise ValueError(ErrorCode.P_333.format_message(_name, error_hint))
            params.extend(value)
            return ",".join("?" * len(value))
        params.append(value)
        return "?"
    return _PARAM_PATTERN.sub(_repl, sql), tuple(params)

@overload
def map_row(value: dict, res_type: None, *, strict: bool = False, error_hint: str = "") -> dict: ...

@overload
def map_row(value: dict, res_type: type[T], *, strict: bool = False, error_hint: str = "") -> T: ...

@overload
def map_row(value: None, res_type: Any, *, strict: bool = False, error_hint: str = "") -> None: ...

@validate_types
def map_row(value: dict | None, res_type: type[T] | None, *, strict: bool = False, error_hint: str = "") -> T | dict | None:
    """ 将单行dict转换为res_type实体

    - res_type为dict时原样返回
    - row为None时原样返回
    - strict=True时，若无法通过__init__正常构造则直接抛异常，不回退到setattr

    :param value: 数据结果
    :param res_type: 返回类型
    :param strict: 是否启用严谨模式（默认False）
    :param error_hint: 异常后的附加信息
    :raises TypeErrot: 构造函数不匹配
    """
    if value is None or res_type is None or not isinstance(res_type, type) or issubclass(res_type, dict):
        return value
    params = get_parameters(res_type)
    try:
        # 若存在kwargs参数，则直接设置value的结果到kwargs参数
        if has_kwargs_param(params.values()):
            return res_type(**value)
        # 直接按照__init__签名过滤参数（dataclass也支持这种传参）
        elif kwargs := {k: v for k, v in value.items() if k in params}:
            return res_type(**kwargs)
        elif strict:
            # 参数签名完全不匹配，且开启严谨模式
            raise TypeError
    except (TypeError, ValueError) as e:
        # TypeError: 调用__init__时必要参数缺失
        # ValueError: 无法提取其__init__签名；调用__init__时参数验证异常
        if strict:
            _params = {name: (param.annotation if param.annotation is not inspect.Parameter.empty else Any)
                       for name, param in params.items()}
            # 构造函数不匹配
            raise TypeError(ErrorCode.P_105.format_message(
                get_class_path(res_type), _params, value, error_hint)) from e
    # 跳过__init__直接实例化，设置每个属性
    instance = object.__new__(res_type)
    # 直接设置到对象中
    for k, v in value.items():
        try:
            setattr(instance, k, v)
        except (AttributeError, TypeError):
            continue
    return instance
