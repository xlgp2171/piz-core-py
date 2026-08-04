""" 验证（validate）处理工具

:version: 0.2.260802
"""
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field, is_dataclass
from types import UnionType
from typing import Any, get_origin, Union, get_args, Literal, Annotated, Mapping, TypeVar, Sequence

from piz_core.constants import ErrorCode
from piz_core.deco import validate_types


class BaseConstraint(ABC):
    """ 约束基类
    """
    @abstractmethod
    def verify(self, args_dict: dict[str, Any], name: str, *, error_hint: str = ""):
        """ 核实约束

        :param args_dict: 参数值
        :param name: 字段名称
        :param error_hint: 验证失败的附加消息
        """
        from piz_core.util import method_unavailable_exception

        raise method_unavailable_exception()

    @staticmethod
    def _require_number(args_dict: dict[str, Any], name: str, *, error_hint: str = "") -> int | float:
        """ 根据字段名称获取参数字典对应的数字值

        :param args_dict: 参数字典
        :param name: 字段名称
        :param error_hint: 验证失败的附加消息
        :raises TypeError: 参数类型不是int或float异常
        :raises ValueError: 参数未找到异常
        """
        from piz_core.constants import ErrorCode

        if name in args_dict:
            value = args_dict[name]

            if type(value) in (int, float):
                return value
            else:
                from piz_core.util.system import get_class_path
                # 类型不匹配
                raise TypeError(ErrorCode.P_310.format_message(
                    "int; float", get_class_path(value), f",\targs: {name}{error_hint}"))
        # 参数未找到
        raise ValueError(ErrorCode.P_101.format_message(name, error_hint))


@dataclass(frozen=True)
class Range(BaseConstraint):
    """ 范围约束
    """
    min_value: int | float | None = None
    """ 整形或浮点型最小限制 """
    max_value: int | float | None = None
    """ 整形或浮点型最大限制 """
    min_inclusive: bool = True
    """ 是否包含最小值 """
    max_inclusive: bool = True
    """ 是否包含最大值 """

    def verify(self, args_dict: dict[str, Any], name: str, *, error_hint: str = ""):
        """ 验证范围

        :param args_dict: 参数值
        :param name: 字段名称
        :param error_hint: 验证失败的附加消息
        :raises ValueError: 超出范围的异常；参数未找到异常
        :raises TypeError: 参数类型不是int或float异常
        """
        value = self._require_number(args_dict, name, error_hint=error_hint)
        validate_range(value, error_hint=f",\targs: {name}{error_hint}", min_value=self.min_value,
                       max_value=self.max_value, min_inclusive=self.min_inclusive, max_inclusive=self.max_inclusive)


@dataclass(frozen=True)
class NonNegative(Range):
    """ 非负数约束
    """
    min_value: int = field(default=0, init=False)
    """ 固定0值 """


@dataclass(frozen=True)
class GreaterThanArgs(BaseConstraint):
    """ 大于指定参数值的约束
    """
    args: str
    """ 参数名称 """
    min_inclusive: bool = True
    """ 是否包含最小值 """

    def verify(self, args_dict: dict[str, Any], name: str, *, error_hint: str = ""):
        """ 验证大于指定参数值

        :param args_dict: 参数值
        :param name: 字段名称
        :param error_hint: 验证失败的附加消息
        :raises ValueError: 超出范围的异常；参数未找到异常
        :raises TypeError: 参数类型不是int或float异常
        """
        value = self._require_number(args_dict, name, error_hint=error_hint)
        args_value = self._require_number(args_dict, self.args, error_hint=error_hint)
        validate_range(value, error_hint=f",\targs: {name}; {self.args}{error_hint}", min_value=args_value,
                       min_inclusive=self.min_inclusive)


@dataclass(frozen=True)
class GreaterThanValue(BaseConstraint):
    """ 大于指定数值的约束
    """
    value: int
    """ 参数名称 """
    min_inclusive: bool = True
    """ 是否包含最小值 """

    def verify(self, args_dict: dict[str, Any], name: str, *, error_hint: str = ""):
        """ 验证大于指定值

        :param args_dict: 参数值
        :param name: 字段名称
        :param error_hint: 验证失败的附加消息
        :raises ValueError: 超出范围的异常；参数未找到异常
        :raises TypeError: 参数类型不是int或float异常
        """
        value = self._require_number(args_dict, name, error_hint=error_hint)
        validate_range(value, error_hint=f",\targs: {name}{error_hint}", min_value=self.value,
                       min_inclusive=self.min_inclusive)


@dataclass(frozen=True)
class LessThanArgs(BaseConstraint):
    """ 小于指定参数值的约束
    """
    args: str
    """ 参数名称 """
    max_inclusive: bool = True
    """ 是否包含最大值 """

    def verify(self, args_dict: dict[str, Any], name: str, *, error_hint: str = ""):
        """ 验证小于指定参数值

        :param args_dict: 参数值
        :param name: 字段名称
        :param error_hint: 验证失败的附加消息
        :raises ValueError: 超出范围的异常；参数未找到异常
        :raises TypeError: 参数类型不是int或float异常
        """
        value = self._require_number(args_dict, name, error_hint=error_hint)
        args_value = self._require_number(args_dict, self.args)
        validate_range(value, error_hint=f"args: {name}; {self.args}{error_hint}", max_value=args_value,
                       max_inclusive=self.max_inclusive)


@dataclass(frozen=True)
class LessThanValue(BaseConstraint):
    """ 小于指定数值的约束
    """
    value: int
    """ 参数名称 """
    max_inclusive: bool = True
    """ 是否包含最大值 """

    def verify(self, args_dict: dict[str, Any], name: str, *, error_hint: str = ""):
        """ 验证小于指定值

        :param args_dict: 参数值
        :param name: 字段名称
        :param error_hint: 验证失败的附加消息
        :raises ValueError: 超出范围的异常；参数未找到异常
        :raises TypeError: 参数类型不是int或float异常
        """
        value = self._require_number(args_dict, name, error_hint=error_hint)
        validate_range(value, error_hint=f",\targs: {name}{error_hint}", max_value=self.value,
                       max_inclusive=self.max_inclusive)

@validate_types
def validate_range(value: int | float, *, error_hint: str = "", min_value: int | float | None = None,
                   max_value: Annotated[int | float | None, GreaterThanArgs('min_value')] = None,
                   min_inclusive: bool = True, max_inclusive: bool = True):
    """ 验证整型和浮点型的范围

    :param value: 整型和浮点型值
    :param error_hint: 验证失败的附加消息
    :param min_value: 整形或浮点型最小限制
    :param max_value: 整形或浮点型最大限制
    :param min_inclusive: 是否包括最小值
    :param max_inclusive: 是否包括最大值
    :raises ValueError: 超出范围的异常
    """
    # >= 或 > 判断
    if min_value is not None and not (value >= min_value if min_inclusive else value > min_value):
        if min_inclusive:
            # value<min_value异常
            raise ValueError(ErrorCode.P_411.format_message(value, min_value, error_hint))
        else:
            # value<=min_value异常
            raise ValueError(ErrorCode.P_412.format_message(value, min_value, error_hint))
    # <= 或 < 判断
    if max_value is not None and not (value <= max_value if max_inclusive else value < max_value):
        if max_inclusive:
            # value>max_value异常
            raise ValueError(ErrorCode.P_421.format_message(value, max_value, error_hint))
        else:
            # value>=max_value异常
            raise ValueError(ErrorCode.P_422.format_message(value, max_value, error_hint))

def _check_type(value: object, expected: type, *, strict: bool) -> bool:
    """ 判断参数和类型是否匹配

    :param value: 判断参数
    :param expected: 期望类型
    :param strict: 是否更严格的匹配（泛型等）
    """
    # 基础类型验证（int, str, bool 等）
    if isinstance(expected, type):
        return False if expected is int and isinstance(value, bool) else (
            True if expected is Any else isinstance(value, expected))
    elif isinstance(expected, TypeVar):
        # TypeVar运行期无法校验，直接放行
        return True
    else:
        # 若满足复合类型 Union / UnionType
        if (origin := get_origin(expected)) is Union or origin is UnionType:
            # 任意值匹配类型即可通过
            return any(_check_type(value, i, strict=strict) for i in get_args(expected))
        # 若是无复合类型或参数
        if not (args := get_args(expected)):
            try:
                # 判断是否是类继承
                return isinstance(value, expected)
            except TypeError:
                pass
        # 若是注解类型
        elif origin is Annotated:
            return _check_type(value, args[0], strict=strict)
        # 若值是某些具体的字面常量（level = Literal["debug", "info"]）
        elif origin is Literal:
            return value in args
        # 若是type[T]这种形式（非严格模式）
        elif origin is type and not strict:
            # T是TypeVar时无法进一步校验，只要求是个类
            return _check_type(value, type, strict=strict)
        # 若需复杂类型严格判断（如判断list中每个元素等）
        elif isinstance(strict, bool) and strict:
            # 严格检查只检查指定类型，其他泛型只检查origin
            if origin in (list, set, dict, tuple, Callable, type):
                return _check_type_strictly(value, origin, args)
            if origin is not None and isinstance(origin, type):
                return isinstance(value, origin)
    # 普通验证若无法验证则默认通过
    return True

def _check_type_strictly(value: Any, origin: Any | None, args: tuple[Any, ...]) -> bool:
    """ 判断参数和复合类型是否匹配

    - 支持严格检查的类型只限于list, set, dict, tuple, Callable, type

    :param value: 判断参数
    :param origin: 复合类型
    :param args: 复合类型附加参数
    """
    # 若是类型的泛型
    if origin is type:
        # 严格模式且T是具体类时需严格验证
        return False if not isinstance(value, type) else (isinstance(args[0], TypeVar) or (
                isinstance(args[0], type) and issubclass(value, args[0])))
    # 若是集合带泛型
    elif (origin is list and isinstance(value, list)) or (
            origin is set and isinstance(value, set)):
        # 所有参数都判断
        return all(_check_type(i, args[0], strict=True) for i in value)
    # 若是字典带泛型
    elif (origin is dict or (isinstance(origin, type) and issubclass(origin, Mapping))) and isinstance(value, Mapping):
        # 所有参数都判断
        return all(
            _check_type(k, args[0], strict=True) and _check_type(v, args[1], strict=True) for k, v in value.items())
    # 若是 tuple[T1, T2] 或 tuple[T1, ...]
    elif origin is tuple and isinstance(value, tuple):
        # 若为 tuple[T1, ...] 模式
        if len(args) == 2 and args[1] is Ellipsis:
            # 所有参数都判断
            return all(_check_type(item, args[0], strict=True) for item in value)
        # 若为 tuple[T1, T2] 模式
        elif len(value) == len(args):
            return all(_check_type(v, t, strict=True) for v, t in zip(value, args))
    # 若是 Callable（这里是原类型collections.abc.Callable），由于无法判断内部参数所以直接通过
    elif origin is Callable and isinstance(value, Callable):
        return True
    # 严格验证若无法验证则默认不通过
    return False

def validate_type(value: Any, expected: Any, *, error_hint: str = "", strict: bool = False):
    """ 验证参数和期望类型是否匹配

    验证不通过直接抛出异常

    :param value: 参数对象
    :param expected: 期望类型（type或types.UnionType或_UnionGenericAlias或GenericAlias或_LiteralGenericAlias或_SpecialForm）
    :param error_hint: 验证失败的附加消息
    :param strict: 是否判断复杂类型（默认False）（非严格模式不会判断泛型）
    :raises TypeError: 类型不匹配异常
    """
    # 若有异常则抛出
    if not _check_type(value, expected, strict=strict):
        from piz_core.util.reflect import get_class_path
        # 期望类型名称
        expected_name = get_class_path(expected) if isinstance(expected, type) else str(expected)
        # 类型不匹配
        raise TypeError(ErrorCode.P_310.format_message(expected_name, get_class_path(value), str(error_hint)))

def validate_constraint(value: str, annotation: Any, arguments: dict[str, Any], *, error_hint: str = ""):
    """ 验证参数对应的值是否符合约束

    :param value: 参数名称
    :param annotation: 约束类型（只识别Annotated类型）
    :param arguments: 参数集合
    :param error_hint: 验证失败的附加消息
    :raises ValueError: 超出范围的异常；参数未找到异常
    :raises TypeError: 参数类型不是约束类型异常
    """
    if hasattr(annotation, '__metadata__'):
        for metadata in annotation.__metadata__:
            if isinstance(metadata, BaseConstraint):
                metadata.verify(arguments, value, error_hint=str(error_hint))

@validate_types
def is_expected_annotation(annotation: Any, expected: type) -> bool:
    """ 是否为期望类型

    :param annotation: 注解
    :param expected: 期望类型
    """
    # 没写类型注解
    if annotation is inspect.Signature.empty:
        return False
    # 传入的是None值
    if annotation is None:
        annotation = type(None)
    # 注解本身就是list或其子类
    if isinstance(annotation, type):
        return _safe_is_subclass(annotation, expected)
    # 如存在泛型
    if (origin := get_origin(annotation)) is not None:
        # 解包（Optional或者X|None）再验证
        if origin in (Union, UnionType):
            args = get_args(annotation)
            # 获取除了None之外的另外的类型
            return any(is_expected_annotation(i, expected) for i in args)
        elif origin is Annotated:
            return is_expected_annotation(get_args(annotation)[0], expected)
        return isinstance(origin, type) and _safe_is_subclass(origin, expected)
    return False

def _safe_is_subclass(cls: type, expected_type: type) -> bool:
    # 当expected是没加@runtime_checkable的Protocol时的异常处理
    try:
        return issubclass(cls, expected_type)
    except TypeError:
        return False

def is_param_object(value: Any) -> bool:
    """ 是否是参数实体对象（dataclass 实例或带 __dict__ 的普通对象）
    """
    # 排除其它
    if value is None or isinstance(value, (str, bytes, bytearray, Mapping, Sequence)) or isinstance(value, type):
        return False
    return is_dataclass(value) or hasattr(value, "__dict__")