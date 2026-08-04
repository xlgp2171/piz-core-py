""" 原始数据（primitive）处理工具

:version: 0.2.260718
"""
import math
import random
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Annotated, Final

from piz_core.deco import validate_types
from piz_core.util.valid import NonNegative


_TRUNCATION_SUFFIX: Final[str] = "..."
""" 内容省略 """
_TRUNCATION_LIMIT: Final[int] = 256
""" 截断长度阈值 """
_UNDERLINE: Final[str] = "_"
""" 标准下划线 """
EMPTY: Final[str] = ""
""" 空字符串 """
ZERO: Final[int] = 0
""" 整型0 """
ONE: Final[int] = 1
""" 整型1 """


def to_boolean(value: Any) -> bool:
    """ 将任意参数转换为布尔型
    """
    return value is not None and (
            equals_ignore_case("true", str(value)) or to_float(value, ZERO) == 1)

def default_string(value: Any, strip: bool = False) -> str:
    """ 将任意参数转换为""（参数为None）或字符串（object类型调用__str__方法）

    :param value: 任意参数
    :param strip: 是否截去两端
    """
    if value is None:
        return EMPTY
    s = str(value)
    return s.strip() if strip else s

@validate_types
def equals_ignore_case(value: str, another: str | None) -> bool:
    """ 在忽略大小写的情况下字符换是否匹配

    :param value: 源字符串
    :param another: 对比字符串
    """
    return another is not None and len(value) == len(another) and value.lower() == another.lower()

@validate_types
def is_blank(value: str | None) -> bool:
    """ 验证字符串是否为None或""或仅包含空白字符
    """
    return not (value and value.strip())

@validate_types
def has_text(value: str | None) -> bool:
    """ 验证字符串是否不包含空白字符
    """
    return value is not None and any(not i.isspace() for i in value)

@validate_types
def contains_whitespace(value: str) -> bool:
    """ 验证字符串是否包含空白字符
    """
    return any(i.isspace() for i in value)

@validate_types
def trim_all_whitespace(value: str) -> str:
    """ 清除字符串中所有的空白字符
    """
    return "".join([i for i in value if not i.isspace()])

@validate_types
def startswith_ignore_case(value: str | None, prefix: str | None, start: Annotated[int | None, NonNegative()] = None,
                           end: Annotated[int | None, NonNegative()] = None) -> bool:
    """ 忽略大小写的情况下验证源字符串是否以指定字符串为开头

    :param value: 源字符串
    :param prefix: 指定字符串
    :param start: 目标字符串的起始索引位置（默认None）
    :param end: 目标字符串的结束索引位置（默认None）
    """
    return value is not None and prefix is not None and len(
        value) >= len(prefix) and value.lower().startswith(prefix.lower(), start, end)

@validate_types
def endswith_ignore_case(value: str | None, suffix: str | None, start: Annotated[int | None, NonNegative()] = None,
                         end: Annotated[int | None, NonNegative()] = None) -> bool:
    """ 忽略大小写的情况下验证源字符串是否以指定字符串为结尾

    :param value: 源字符串
    :param suffix: 指定字符串
    :param start: 目标字符串的起始索引位置（默认None）
    :param end: 目标字符串的结束索引位置（默认None）
    """
    return value is not None and suffix is not None and len(
        value) >= len(suffix) and value.lower().endswith(suffix.lower(), start, end)

@validate_types
def substring_after(value: str, separator: str, last: bool = False) -> str:
    """ 提取分隔符之后的内容

    :param value: 源字符串
    :param separator: 分隔符
    :param last: 是否从最后开始查找
    """
    idx = value.rfind(separator) if last else value.find(separator)
    return value[idx + len(separator):] if idx != -1 else value

@validate_types
def capitalize(value: str) -> str:
    """ 字符串首字母大写
    """
    return _change_first_character_case(value, True)

@validate_types
def uncapitalize(value: str) -> str:
    """ 字符串首字母小写
    """
    return _change_first_character_case(value, False)

@validate_types
def decapitalize(value: str) -> str:
    """ 字符串首字母小写，若前两个字母是大写，则不变
    """
    # 前两个字母都大写则保持原样
    return value if len(value) > 1 and value[:2].isupper() else uncapitalize(value)

def _change_first_character_case(value: str, capitalized: bool) -> str:
    """ 字符串首字母变更

    :param value: 源字符串
    :param capitalized: 是否大写
    """
    if is_blank(value):
        return EMPTY
    updated = value[0].upper() if capitalized else value[0].lower()
    return updated + value[1:]

@validate_types
def camel_to_underline(value: str) -> str:
    """ 将驼峰命名转下划线命名（AbCd -> ab_cd）
    """
    if is_blank(value):
        return EMPTY
    s = ""

    for n, i in enumerate(default_string(value, strip=True)):
        if i.isupper() and n > 0:
            s += _UNDERLINE
        s += i.lower()
    return s

@validate_types
def underline_to_camel(value: str) -> str:
    """ 将下划线命名转驼峰命名（ab_cd -> AbCd）
    """
    if is_blank(value):
        return EMPTY
    s, upper = "", True

    for n, i in enumerate(default_string(value, strip=True).lower()):
        if upper:
            s += i.upper()
            upper = False
        elif i == _UNDERLINE:
            upper = True
        else:
            s += i
    return s

@validate_types
def regex_extract(value: str, pattern: str | re.Pattern, group: Annotated[int, NonNegative()] = ONE) -> str | None:
    """ 提取正则表达式匹配的字符串

    :param value: 源字符串
    :param pattern: 正则表达式
    :param group: 提取索引
    """
    if is_blank(value):
        return None
    return m.group(group) if (m := re.search(pattern, value)) and group <= m.re.groups else None

@validate_types
def regex_extract_all(value: str, pattern: str | re.Pattern) -> list[str] | list[tuple]:
    """ 提取正则表达式所有匹配的分组内容

    :param value: 源字符串
    :param pattern: 正则表达式
    :raises TypeError: value 不是 str 或 pattern 不是 str/re.Pattern 时抛出
    :raises re.error: pattern 为无效正则表达式时抛出
    """
    if is_blank(value):
        return []
    return re.findall(pattern, value)

@validate_types
def truncate(value: str, threshold: Annotated[int, NonNegative()] = _TRUNCATION_LIMIT) -> str:
    """ 按长度进行截断（若字符串大于阈值则截断否则直接返回）

    :param value: 目标字符串
    :param threshold: 长度阈值（默认256）
    """
    return value[0:threshold] + _TRUNCATION_SUFFIX if len(value) > threshold else value

def default_int(value: Any) -> int:
    """ 将任意参数转换为整型0（参数为None或非整型）或对应整型
    """
    return ZERO if value is None else to_int(value, ZERO)

def default_float(value: Any) -> float:
    """ 将任意参数转换为浮点型0.0（参数为None或非浮点型）或对应浮点型
    """
    return 0.0 if value is None else to_float(value, 0.0)

@validate_types
def to_int(value: Any, default: int = ZERO) -> int:
    """ 将任意参数转换为整型，若转换失败则使用默认值

    :param value: 源数据
    :param default: 处理失败后的默认值
    """
    return int(to_float(value, default))

@validate_types
def to_float(value: Any, default: float | int = 0.0) -> float:
    """ 将任意参数转换为浮点型，若转换失败则使用默认值

    :param value: 源数据
    :param default: 处理失败后的默认值
    """
    try:
        return float(str(value))
    except ValueError:
        return default * 1.0

@validate_types
def randrange_step(start: float | int, stop: float | int, step: float | int, ndigits: Annotated[
    int, NonNegative()] = ZERO) -> float:
    """ 在 [start,stop) 范围内按step步长随机取值，返回保留ndigits位的结果

    :param start: 起始值（数据不能小于1e-12）
    :param stop: 结束值（数据不能小于1e-12）
    :param step: 数据间隔
    :param ndigits: 保留小数
    """
    if step == 0:
        return round(start, ndigits) * 1.0
    count = max(ZERO, math.ceil((stop - start) / step - 1e-12))
    idx = random.randrange(count) if count > 0 else ZERO
    return round(start + step * idx * 1.0, ndigits) * 1.0

@validate_types
def round_standard(value: int | float, ndigits: Annotated[int, NonNegative()]) -> float:
    """ 按标准四舍五入处理数据

    :param value: 源数据（整型或浮点型）
    :param ndigits: 保留小数位数
    """
    return float(_quantize(value, ndigits))

@validate_types
def to_plain_string(value: int | float, ndigits: Annotated[int, NonNegative()]) -> str:
    """ 转换为浮点型的字符串

    :param value: 源数据（浮点型）
    :param ndigits: 保留小数位数
    """
    # format(..., 'f')相当于禁用科学计数法
    return format(_quantize(value, ndigits), 'f')


def _quantize(value: float, ndigits: Annotated[int, NonNegative()] = ZERO) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(10) ** -ndigits, rounding=ROUND_HALF_UP)
