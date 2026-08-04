""" 加密解密（crypto）处理工具

:version: 0.2.260706
"""
import base64
import hashlib
import sys

from piz_core.deco import validate_types


@validate_types
def to_hash(*values: bytes) -> str:
    """ 对字节流数组进行sha256编码
    """
    sha = hashlib.sha256()

    for i in values:
        sha.update(i)
    return str(sha.hexdigest())

@validate_types
def to_base64_as_string(value: str | bytes, encoding: str | None = None) -> str:
    """ 将字符串或字节流转换为标准base64字符串

    :param value: 字符串或字节流
    :param encoding: 转码格式（默认系统编码）
    """
    encoding = encoding if encoding else sys.getdefaultencoding()

    if isinstance(value, str):
        value = value.encode(encoding)
    return base64.standard_b64encode(value).decode(encoding)

@validate_types
def from_base64_as_stream(value: str) -> bytes:
    """ 将标准base64字符串转换为字节流
    """
    return base64.standard_b64decode(value)

@validate_types
def from_base64_as_string(value: str, encoding: str | None = None) -> str:
    """ 将标准base64字符串转换为字符串

    :param value: base64字符串
    :param encoding: 转码格式（默认系统编码）
    """
    return from_base64_as_stream(value).decode(
        encoding if encoding else sys.getdefaultencoding())
