""" 系统（system）处理工具

:version: 0.2.260730
"""
import inspect
from typing import Callable, ParamSpec, TypeVar, Any, Iterator

from piz_core.deco import validate_types


# 捕获任意参数签名
P = ParamSpec("P")
# 捕获返回值类型
T = TypeVar("T")


def get_func_name(func: Callable | None) -> str:
    """ 安全获取函数的完整限定名
    """
    if not func:
        return "unknown"
    if hasattr(func, '__qualname__'):
        return func.__qualname__
    elif hasattr(func, '__name__'):
        return func.__name__
    elif hasattr(func, '__class__'):
        return f"{func.__class__.__name__}.__call__"
    return repr(func)

@validate_types
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
    elif inspect.ismethod(func):
        return True, True
    qualname = getattr(func, '__qualname__', '')
    # 剥掉 "outer.<locals>." 前缀：局部类方法 "f.<locals>.C.m" 仍是类成员，
    # 而局部函数 "f.<locals>.inner" 剥完后不含 '.'，正确判为模块级
    return (False, False) if '.' not in qualname.split('<locals>.')[-1] else (False, True)

# 这个函数不能使用@validate_types
def bind_arguments(func: Callable[P, T], /, *args: P.args, eval_str: bool = True, partial: bool = False,
                   **kwargs: P.kwargs) -> tuple[dict[str, Any], inspect.Signature]:
    """ 把实参按签名绑定到形参名上并返回参数字典

    :param func: 被检查的目标函数（可调用对象），仅限位置传参
    :param args: 转发给 func 的位置实参
    :param eval_str: 是否将字符串形式的注解解析为真实类型对象，默认 True
    :param partial: 是否采用宽松绑定方式
    :param kwargs: 转发给 func 的关键字实参
    """
    # 获取函数签名（参数名、默认值、注解等）
    signature = inspect.signature(func, eval_str=eval_str)
    # 宽松绑定
    if partial:
        # 宽松绑定不会考虑有默认值的参数
        bound = signature.bind_partial(*args, **kwargs)
        # 无默认值时占位置为 Parameter.empty，供调用方判断
        return ({name: bound.arguments.get(name, param.default) for name, param in signature.parameters.items()},
                signature)
    else:
        # 按函数签名绑定到对应参数名，把未传入但有默认值的参数也进行绑定
        (bound := signature.bind(*args, **kwargs)).apply_defaults()
        return dict(bound.arguments), signature

# 这个函数不能使用@validate_types
def iter_arguments(func: Callable[P, T], /, *args: P.args, include_variadic: bool = False,
                   include_unannotated: bool = False, eval_str: bool = True, partial: bool = False, **kwargs: P.kwargs
                   ) -> Iterator[tuple[str, Any, Any, dict[str, Any]]]:
    """ 按目标函数签名绑定一次调用的实参，逐个产出 (参数名, 类型注解, 参数值, 参数集)四元组。

    - 未显式传入的参数以默认值绑定后同样产出
    - ``self``/``cls`` 始终跳过
    - 开启 ``include_variadic`` 后，``*args`` 绑定为 tuple、``**kwargs`` 绑定为 dict，
      各自以整体形式产出一次，注解位为变长参数自身的注解（语义上作用于每个元素/值）
    - 开启 ``include_unannotated`` 后，无注解参数同样产出，注解位为 ``inspect.Parameter.empty``

    :param func: 被检查的目标函数（可调用对象），仅限位置传参
    :param args: 转发给 func 的位置实参
    :param include_variadic: 是否产出 ``*args``/``**kwargs`` 变长参数，默认 False
    :param include_unannotated: 是否产出无类型注解的参数，默认 False
    :param eval_str: 是否将字符串形式的注解解析为真实类型对象，默认 True
    :param partial: 是否采用宽松绑定方式
    :param kwargs: 转发给 func 的关键字实参
    :raises TypeError: 实参与 func 的签名不匹配时抛出
    :raises NameError: ``eval_str=True`` 且注解中的名字无法解析时抛出
    :r
    """
    # 绑定参数
    arguments_dict, signature = bind_arguments(func, *args, eval_str=eval_str, partial=partial, **kwargs)
    # 遍历所有已绑定参数
    for name, value in arguments_dict.items():
        # 跳过 self/cls
        if name in ('self', 'cls') or (
                # 未开启 include_variadic 时跳过*args和**kwargs的特殊情况
                (param := signature.parameters[name]).kind in (
                inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD) and not include_variadic) or (
                # 未开启 include_unannotated 时跳过没有类型标识的参数
                (annotation := param.annotation) is inspect.Parameter.empty and not include_unannotated):
            continue
        yield name, annotation, value, arguments_dict

@validate_types
def get_return_annotation(func: Callable[P, T], /, *, eval_str: bool = True) -> Any:
    """ 获取函数返回注解

    :param func: 被检查的目标函数（可调用对象），仅限位置传参
    :param eval_str: 是否将字符串形式的注解解析为真实类型对象，默认True
    """
    return inspect.signature(func, eval_str=eval_str).return_annotation
