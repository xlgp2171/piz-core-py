""" 依赖注入装饰器

:version: 0.3.260814
"""
import inspect
from functools import wraps
from typing import TypeVar, ParamSpec, Callable, get_args, Any, Sequence

from piz_core.const import NAMESPACE, ErrorCode
from piz_core.infra.event import register_hook
from piz_core.infra.ioc import Qualifier, container, Prop, trigger_hooks, inject_hook

# 捕获任意参数签名
P = ParamSpec("P")
# 捕获返回值类型
T = TypeVar("T")


def inject(target_func: Callable[P, T]) -> Callable[P, T]:
    """ 基于依赖注入实现实例注入的装饰器

    :raises ValueError: 参数未按Annotated规范定义；名称或类型未匹配到任何实例，或两者均未提供
    :raises TypeError: 定义类型和实例类型无法匹配；名称存在，但实例类型与 instance_type 不兼容
    :raises LookupError: 按类型查找时存在多个实例，无法确定
    """
    from piz_core.util import iter_arguments
    # 保留原函数的元数据装饰器
    @wraps(target_func)
    def _wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        resolved_dict = {}
        # 处理每个参数（包括未定义类型的参数）
        for _name, annotation, _value, arguments in iter_arguments(
                target_func, include_unannotated=True, partial=True, *args,  **kwargs):
            # 跳过显示参数输入
            if _name in arguments and arguments[_name] is not inspect.Parameter.empty:
                continue
            # 若为Annotated类型
            if hasattr(annotation, '__metadata__'):
                real_type, *metadata = get_args(annotation)
                # 尝试获取配置值
                prop = next((i for i in metadata if isinstance(i, Prop)), None)
                # 尝试获取定义值
                qualifier = next((i for i in metadata if isinstance(i, Qualifier)), None)
                # 若都未配置，则异常
                if prop is None and qualifier is None:
                    from piz_core.util import get_func_path
                    # 注解缺失
                    raise ValueError(ErrorCode.P_211.format_message(get_func_path(target_func), _name))
                # 优先获取配置中的值
                instance_name = str(prop.get_value()) if prop is not None else qualifier.name
                # 按照实际类型和指定名称进行匹配
                if (instance := _try_resolve(None, instance_name, _value)) is None:
                    continue
                # 命中后再校验类型（real_type 可能是泛型别名）
                if isinstance(real_type, type) and not isinstance(instance, real_type):
                    from piz_core.util import get_class_path, get_func_path
                    # 类型不匹配
                    error_hint = f",\tfunc: {get_func_path(target_func)},\targs: {_name}"
                    raise TypeError(ErrorCode.P_310.format_message(
                        get_class_path(real_type), get_class_path(instance), error_hint))
            else:
                # 按照类型和参数名称进行匹配
                if (instance := _try_resolve(annotation, _name, _value)) is None:
                    continue
            resolved_dict[_name] = instance
        # 回调参数（按key进行匹配）
        return target_func(*args, **{**kwargs, **resolved_dict})
    # 标记依赖
    _wrapper.__inject = NAMESPACE
    return _wrapper

def _try_resolve(instance_type: type | None, instance_name: str, value: Any) -> Any:
    """ 尝试获取实例

    :param instance_type: 期望的实例类型。按名称命中时用于类型校验；未传名称时用于按类型精确查找
    :param instance_name: 实例名称。为 None 时按类型查找
    :param value: 函数的输入参数值
    :raises TypeError: 名称存在，但实例类型与 instance_type 不兼容
    :raises LookupError: 按类型查找时存在多个实例，无法确定
    :raises ValueError: 名称或类型未匹配到任何实例，或两者均未提供
    """
    try:
        return container.resolve(instance_type=instance_type, instance_name=instance_name)
    except (TypeError, LookupError, ValueError):
        # 若参数值未设置默认、没有传值则直接抛出异常
        if value is inspect.Parameter.empty:
            raise
        return None

def component(target_cls: type | None = None, /, *, name: str | None = None,
              hook_funcs: Sequence[Callable[[Any, str, Any], None]] | None = None) -> Callable | type:
    """ 类依赖装饰器

    - 将被装饰的类实例化并注册到容器（单例，饿汉式），类本身保持不变，仍可正常使用。
    - 用法1：@component # 默认名称为类名首字母小写
    - 用法2：@component(name="svc") # 可显式指定注册名称
    - 用法3：@component(hook_funcs=[func]) # 用于初始化钩子函数注册

    :param target_cls: 被装饰的类（@component 无参形式时由解释器自动传入）
    :param name: 注册到容器的实例名称，默认按 Spring 规则取类名首字母小写
    :param hook_funcs: 实例初始化时的钩子函数组合（输入为：实例，成员名称，实例成员）
    :raises ValueError: 实例函数无效
    """
    def _decorator(cls: type) -> type:
        from piz_core.util import decapitalize
        # 初始化函数
        def _new_instance() -> Any:
            _assemble(instance := cls(), hook_funcs)
            return instance
        # 实例化并注册（ensure幂等：同名已注册时复用已有实例，不会重复实例化）
        container.ensure(name if name else decapitalize(cls.__name__), _new_instance)
        # 返回原类，不影响继承、直接实例化等正常使用
        return cls
    # 如果target_cls不是None，说明是直接使用无参装饰器
    return _decorator(target_cls) if target_cls is not None else _decorator

def provide(target_func: Callable | None = None, /, *, name: str | None = None, eager: bool = True,
            hook_funcs: Sequence[Callable[[Any, str, Any], None]] | None = None):
    """ 方法依赖装饰器

    - 将被装饰工厂函数的返回值注册到容器（单例）。装饰后再次调用该函数，
    - 直接返回容器中的单例
    - 用法1：@provide # 默认名称为函数名，装饰时立即执行并注册
    - 用法2：@provide(name="ds") # 显式指定注册名称
    - 用法3：@provide(eager=False) # 惰性注册为首次调用时才执行工厂函数
    - 用法4：@provide(hook_funcs=[func]) # 用于初始化钩子函数注册

    :param target_func: 被装饰的工厂函数（@provide 无参形式时自动传入）
    :param name: 注册到容器的实例名称（默认为小写的func.__name__返回值）
    :param eager: 是否在装饰时立即执行工厂函数完成注册，False为调用时（默认 True）
    :param hook_funcs: 实例初始化时的钩子函数组合（输入为：实例，成员名称，实例成员）
    :raises ValueError: 实例函数无效
    """
    def _decorator(func: Callable[P, T]) -> Callable[P, T]:
        # 保留原函数的元数据装饰器
        @wraps(func)
        def _wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            # 初始化函数
            def _new_instance() -> Any:
                # 根据实例自动注入
                _assemble(instance := func(*args, **kwargs), hook_funcs)
                return instance
            # 首次调用：执行工厂函数并注册（ensure 内部对 None 返回值会抛 ValueError）
            return container.ensure(name if name else str(func.__name__).lower(), _new_instance)
        # 饿汉式：装饰时立即完成注册
        if eager:
            _wrapper()
        return _wrapper
    # 如果target_cls不是None，说明是直接使用无参装饰器
    return _decorator(target_func) if target_func is not None else _decorator

def _assemble(instance: Any, hook_funcs: Sequence[Callable[[Any, str, Any], None]] | None):
    """ 扫描实例所有标记的方法并按函数处理（沿 MRO 覆盖父类）

    :param instance: 实例
    :param hook_funcs: 实例初始化时的钩子函数组合（输入为：实例，成员名称，实例成员）
    """
    from piz_core.util import sequence_merge
    # 去重后触发hooks（附加系统预设的hook）
    trigger_hooks(
        instance, *sequence_merge([inject_hook, register_hook], hook_funcs, key_func=id))
