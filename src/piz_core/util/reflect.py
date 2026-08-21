""" 系统（system）处理工具

:version: 0.3.260820
"""
import re
from inspect import signature, Parameter, Signature, ismethod, getdoc
from types import MappingProxyType
from typing import Callable, ParamSpec, TypeVar, Any, Iterator, Iterable, Literal

from piz_core.deco import validate_types
from piz_core.util.prim import default_string

# 捕获任意参数签名
P = ParamSpec("P")
# 捕获返回值类型
T = TypeVar("T")
# 处理":param x:"描述或":raises Error:"描述或":return:"描述
_RE_FIELD = re.compile(r"^\s*:(param|raises|returns?)\s*(?:([\w.]+)\s*)?:\s*(.*)$")
""" 注释字段行正则 """
# 任何注释字段起始（包括":return:"）
_RE_ANY_FIELD = re.compile(r"^\s*:\w+")
""" 注释字段起始正则 """
# 为第一个注释字段行出现的位置
_RE_FIRST_FIELD = re.compile(r"^\s*:(?:param|raises|return|returns|rtype|yield|yields)\b", re.M)
""" 描述与字段的分割正则 """


def get_func_path(func: Callable | None) -> str:
    """ 安全获取函数的完整限定名

    - 类方法/静态方法/实例方法: 模块名.类名.方法名
    - 模块级裸函数: 模块名.函数名
    - 可调用对象实例: 模块名.类名.__call__
    """
    if func is None:
        return "unknown"
    # 标准函数/方法：__module__.__qualname__
    module = getattr(func, "__module__", None)
    # 直接输出模块.类.方法
    if qualname := getattr(func, "__qualname__", None):
        return f"{module}.{qualname}" if module else str(qualname)
    # 无__qualname__时（如partial或某些C扩展）
    elif name := getattr(func, "__name__", None):
        return f"{module}.{name}" if module else str(name)
    # 所有剩余callable（类对象 或 可调用实例）
    elif callable(func):
        # 类对象
        if isinstance(func, type):
            cls_name = getattr(func, "__name__", None) or getattr(func, "__qualname__", None)

            if (cls_module := getattr(func, "__module__", None)) and cls_name:
                return f"{cls_module}.{cls_name}"
        # 可调用对象实例
        else:
            # 可调用对象实例（实现了 __call__）
            cls_name = getattr(cls := type(func), "__qualname__", None) or getattr(cls, "__name__", None)

            if cls_name:
                prefix = f"{cls_module}.{cls_name}" if (cls_module := getattr(cls, "__module__", None)) else cls_name
                return f"{prefix}.__call__"
    # 未知对象
    return f"<unresolvable:{type(func).__name__}:{id(func)}>"

def get_class_path(value: object | type) -> str:
    """ 获取类型路径名称
    """
    cls = value if isinstance(value, type) else type(value)
    return f"{cls.__module__}.{cls.__qualname__}"

@validate_types
def method_kind(func: Callable) -> tuple[bool, bool]:
    """ 判断函数是否是方法和定义在类中（是否是方法，是否定义在类中）

    - 类的 @staticmethod 识别为非方法，但是定义在类中，返回（False，True）
    - 类的 @classmethod 识别为方法，也是定义在类中，返回（True，True）
    - 模块的 def func3() 识别为非方法，没有定义在类中，返回（False，False）
    - Sample().func1() 识别为方法，也是定义在类中，返回（True，True）
    - Sample.func2() 识别为非方法，但是定义在类中，返回（False，True）

    :param func: 函数
    """
    # 已被@classmethod包装
    if isinstance(func, classmethod):
        return True, True
    # 已被@staticmethod包装
    elif isinstance(func, staticmethod):
        return False, True
    elif ismethod(func):
        return True, True
    qualname = getattr(func, '__qualname__', '')
    # 剥掉 "outer.<locals>." 前缀：局部类方法 "f.<locals>.C.m" 仍是类成员，
    # 而局部函数 "f.<locals>.inner" 剥完后不含 '.'，正确判为模块级
    return (False, False) if '.' not in qualname.split('<locals>.')[-1] else (False, True)

# 这个函数不能使用@validate_types
def bind_arguments(func: Callable[P, T], /, *args: P.args, eval_str: bool = True, partial: bool = False,
                   **kwargs: P.kwargs) -> tuple[dict[str, Any], Signature]:
    """ 把实参按签名绑定到形参名上并返回参数字典

    :param func: 被检查的目标函数（可调用对象），仅限位置传参
    :param args: 转发给 func 的位置实参
    :param eval_str: 是否将字符串形式的类型注释解析为真实类型对象（默认True）
    :param partial: 是否采用宽松绑定方式（默认False）
    :param kwargs: 转发给 func 的关键字实参
    """
    # 获取函数签名（参数名、默认值、类型注释等）
    _signature = signature(func, eval_str=eval_str)
    # 宽松绑定
    if partial:
        # 宽松绑定不会考虑有默认值的参数
        bound = _signature.bind_partial(*args, **kwargs)
        # 无默认值时占位置为 Parameter.empty，供调用方判断
        return ({name: bound.arguments.get(name, param.default) for name, param in _signature.parameters.items()},
                _signature)
    else:
        # 按函数签名绑定到对应参数名，把未传入但有默认值的参数也进行绑定
        (bound := _signature.bind(*args, **kwargs)).apply_defaults()
        return dict(bound.arguments), _signature

# 这个函数不能使用@validate_types
def iter_arguments(func: Callable[P, T], /, *args: P.args, include_variadic: bool = False,
                   include_unannotated: bool = False, eval_str: bool = True, partial: bool = False, **kwargs: P.kwargs
                   ) -> Iterator[tuple[str, Any, Any, dict[str, Any]]]:
    """ 按目标函数签名绑定一次调用的实参，逐个产出：参数名，类型注释，参数值，参数集

    - 未显式传入的参数以默认值绑定后同样产出
    - ``self``/``cls`` 始终跳过
    - 开启 ``include_variadic`` 后，``*args`` 绑定为 tuple、``**kwargs`` 绑定为 dict，
      各自以整体形式产出一次，类型注释为变长参数自身的注释（语义上作用于每个元素/值）
    - 开启 ``include_unannotated`` 后，无类型注释的参数同样产出，注释为 ``inspect.Parameter.empty``

    :param func: 被检查的目标函数（可调用对象），仅限位置传参
    :param args: 转发给 func 的位置实参
    :param include_variadic: 是否产出 ``*args``/``**kwargs`` 变长参数（默认False）
    :param include_unannotated: 是否产出无类型注释的参数（默认False）
    :param eval_str: 是否将字符串形式的类型注释解析为真实类型对象（默认True）
    :param partial: 是否采用宽松绑定方式
    :param kwargs: 转发给 func 的关键字实参
    :raises TypeError: 实参与 func 的签名不匹配时抛出
    :raises NameError: ``eval_str=True`` 且类型注释中的名字无法解析时抛出
    """
    # 绑定参数
    arguments_dict, _signature = bind_arguments(func, *args, eval_str=eval_str, partial=partial, **kwargs)
    # 遍历所有已绑定参数
    for name, value in arguments_dict.items():
        # 跳过 self/cls
        if name in ('self', 'cls') or (
                # 未开启 include_variadic 时跳过*args和**kwargs的特殊情况
                (param := _signature.parameters[name]).kind in (
                Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD) and not include_variadic) or (
                # 未开启 include_unannotated 时跳过没有类型标识的参数
                (annotation := param.annotation) is Parameter.empty and not include_unannotated):
            continue
        yield name, annotation, value, arguments_dict

@validate_types
def get_parameters(obj: Any, /, *, eval_str: bool = True) -> MappingProxyType[str, Parameter]:
    """ 获取函数签名的有序参数字典（只读视图）

    :param obj: 被检查的对象，包括函数、类型、对象、描述符等（仅限位置传参）
    :param eval_str: 是否将字符串形式的类型注释解析为真实类型对象（默认True）
    """
    return signature(obj, eval_str=eval_str).parameters

@validate_types
def iter_parameters(obj: Any, /, include_variadic: bool = False, include_unannotated: bool = False,
                    eval_str: bool = True) -> Iterator[tuple[str, Parameter, MappingProxyType[str, Parameter]]]:
    """ 按目标函数参数签名逐个产出：参数名，类型注释，参数值，参数集

    :param obj: 被检查的对象，包括函数、类型、对象、描述符等（仅限位置传参）
    :param include_variadic: 是否产出 ``*args``/``**kwargs`` 变长参数（默认False）
    :param include_unannotated: 是否产出无类型注释的参数（默认False）
    :param eval_str: 是否将字符串形式的类型注释解析为真实类型对象（默认True）
    """
    # 获取参数字典
    params = get_parameters(obj, eval_str=eval_str)
    # 遍历所有已绑定参数
    for name, param in params.items():
        # 跳过 self/cls
        if name in ('self', 'cls') or (
                # 未开启 include_variadic 时跳过*args和**kwargs的特殊情况
                param.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD) and not include_variadic) or (
                # 未开启 include_unannotated 时跳过没有类型标识的参数
                (annotation := param.annotation) is Parameter.empty and not include_unannotated):
            continue
        yield name, param, params

@validate_types
def has_kwargs_param(params: Iterable[Parameter]) -> bool:
    """ 检查参数是否包含**kwargs
    """
    return any(i.kind is Parameter.VAR_KEYWORD for i in params)

@validate_types
def has_args_param(params: Iterable[Parameter]) -> bool:
    """ 检查参数是否包含**args
    """
    return any(i.kind is Parameter.VAR_POSITIONAL for i in params)

@validate_types
def get_return_annotation(func: Callable[P, T], /, *, eval_str: bool = True) -> Any:
    """ 获取函数的返回值类型

    :param func: 被检查的目标函数（可调用对象），仅限位置传参
    :param eval_str: 是否将字符串形式的类型注释解析为真实类型对象（默认True）
    """
    return signature(func, eval_str=eval_str).return_annotation

@validate_types
def get_func_doc(func: Callable) -> str:
    """ 获取方法本身的注释（含特性说明，不含参数、异常、返回）
    """
    # 获取方法全部注释
    if not (doc := getdoc(func)):
        return ""
    # 若找到分隔则截取，若没有则使用全部
    matched = _RE_FIRST_FIELD.search(doc)
    return default_string(doc[: matched.start()] if matched else doc, strip=True)

@validate_types
def get_field_doc(func: Callable, name: str, kind: Literal["param", "raises", "return"]) -> str:
    """获取指定参数或异常的注释（支持注释换行续写）

    :param func: 函数对象
    :param name: 参数名或异常名
    :param kind: 可选为"param"或"raises"或"return"
    """
    # 获取方法全部注释
    if not (doc := getdoc(func)):
        return ""
    lines = doc.splitlines(keepends=True)
    # 目标字段起始位置；每行的起始偏移；偏移集合
    target_idx, pos, offsets = None, 0, []
    # 记录每一行起始位置
    for i in lines:
        offsets.append(pos)
        pos += len(i)
    # 查找目标字段的索引位置
    for n, i in enumerate(lines):
        # 匹配字段
        if not (matched := _RE_FIELD.match(i)):
            continue
        field_kind, field_name = matched.group(1), matched.group(2)
        # returns统一为return
        if field_kind in ("return", "returns"):
            field_kind = "return"
        # 排除不匹配
        if field_kind != kind:
            continue
        # return 不比名字
        if kind == "return" or field_name == name:
            target_idx = n
            break
    # 若未找到，则直接返回空自负床
    if target_idx is None:
        return ""
    # 包括：首行描述+换行描述
    # NOTE(xlgp2171): group处理前置已判断
    parts = [_RE_FIELD.match(lines[target_idx]).group(3).strip()]
    # 获取换行描述直到下一个字段注释
    for line in lines[target_idx + 1:]:
        # 字段开头
        if _RE_ANY_FIELD.match(line):
            break
        # 若是有效的字符串
        if stripped := line.strip():
            parts.append(stripped)
    return " ".join(parts).strip()