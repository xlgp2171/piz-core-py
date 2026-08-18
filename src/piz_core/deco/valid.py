""" 验证装饰器

:version: 0.3.260818
"""
from functools import wraps
from typing import TypeVar, Callable, Any, overload, cast

from piz_core.setting import Settings


F = TypeVar("F", bound=Callable[..., Any])


@overload
def validate_types(target_func: F, /) -> F: ...

@overload
def validate_types(target_func: None = None, /, *, strict: bool = True) -> Callable[[F], F]: ...

def validate_types(target_func: F | None = None, /, *, strict: bool = True) -> Callable[[F], F] | F:
    """ 基于期望类型的自动验证参数类型装饰器

    :param target_func: 输入函数
    :param strict: 是否判断复杂类型（默认False）
    :raises TypeError: 类型不匹配异常；参数类型不是约束类型异常
    :raises ValueError: 超出范围的异常；参数未找到异常
    """
    def _decorator(func: F) -> F:
        # 保留原函数的元数据装饰器
        @wraps(func)
        def _wrapper(*args, **kwargs) -> F:
            # 全局开关
            if Settings.validate_types_enabled:
                from piz_core.util import iter_arguments, validate_type, validate_constraint, get_func_path
                # 处理每个参数
                for _name, annotation, _value, arguments in iter_arguments(func, *args, **kwargs):
                    # 验证参数和类型
                    validate_type(
                        _value, annotation, error_hint=f",\tfunc: {get_func_path(func)},\targs: {_name}", strict=strict)
                    # 验证取值范围（针对Annotated类型）
                    validate_constraint(annotation, _name, arguments, error_hint=f",\tfunc: {get_func_path(func)}")
            return func(*args, **kwargs)
        return cast(F, _wrapper)
    # 如果target_func不是None，说明是直接使用无参装饰器
    return _decorator(target_func) if target_func is not None else _decorator
