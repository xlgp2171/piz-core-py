""" Web连接组件

:version: 0.2.260727
"""
from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from http.client import HTTPMessage
from typing import Any, Final, Annotated
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from piz_core.constants import ErrorCode
from piz_core.deco import validate_types
from piz_core.util import NonNegative


_HTTP_TIMEOUT: Final[float] = 30.0
""" HTTP超时时间（秒） """
_JSON_CONTENT_TYPE: Final[str] = "application/json;charset=utf-8"
""" JSON的Content-Type """


@dataclass(frozen=True, slots=True)
class Response:
    """ HTTP响应结构体
    """
    status_code: int
    """ HTTP状态码 """
    reason: str
    """ 状态描述 """
    headers: HTTPMessage
    """ 响应头 """
    text: str
    """ 响应体（utf-8解码） """
    content: bytes
    """ 响应体（字节） """
    url: str
    """ 最终请求地址 """

    @property
    def ok(self) -> bool:
        """ 2xx返回True
        """
        return 200 <= self.status_code < 300

    @property
    def json(self) -> Any:
        """ 返回JSON结构体
        """
        return json.loads(self.text)


class _HttpClient:
    """ 轻量级HTTP客户端

    - 不支持上传文件
    - 不支持302跳转
    """
    def __init__(self):
        # 默认的连接headers（每个连接都会附加）
        self._default_headers: dict[str, str] = {}
        # 默认的HTTP超时时间
        self.default_timeout: float = _HTTP_TIMEOUT
        # 默认的context
        self._default_context: ssl.SSLContext | None = None

    @staticmethod
    def _new_context() -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def _ssl_context(self, verify: bool | str) -> ssl.SSLContext | None:
        if isinstance(verify, str):
            # verify 为证书路径（str）
            return ssl.create_default_context(cafile=verify)
        # 尝试跳过证书验证
        elif not verify:
            if self._default_context is None:
                self._default_context = self._new_context()
            return self._default_context
        # 使用系统默认 CA
        return None

    @staticmethod
    def _prepare_body(data: str | bytes | dict | None, json_data: Any, headers: dict[str, str]
                      ) -> tuple[bytes | None, dict[str, str]]:
        """ 预处理消息体

        :param data: 请求消息体
        :param json_data: json消息体
        :param headers: 请求头
        """
        if json_data is not None:
            # 若有json_data则返回序列化的json数据和json请求类型头
            return (json.dumps(json_data, ensure_ascii=False).encode("utf-8"),
                    {**headers, "Content-Type": _JSON_CONTENT_TYPE})
        elif data is None:
            # 若data也为None直接返回请求头
            return None, headers
        elif isinstance(data, dict):
            # 若未设置请求头则默认设置表单类型头
            if any(i.lower() == "content-type" for i in headers):
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            return urlencode(data, doseq=True).encode("utf-8"), headers
        elif isinstance(data, str):
            return data.encode("utf-8"), headers
        return data, headers

    @validate_types
    def request(self, method: str, url: str, *, params: dict[str, Any] | list[tuple[str, Any]] | None = None,
                data: str | bytes | dict | None = None, headers: dict[str, str] | None = None,
                timeout: Annotated[float, NonNegative()] | None = None,
                verify: bool | str = True, json_data: Any = None) -> Response:
        """ 按条件请求地址

        :param method: 请求方法（GET,POST,PUT,DELETE,PATCH,OPTION）
        :param url: 请求地址
        :param params: 请求参数
        :param data: 请求消息体
        :param headers: 请求头
        :param timeout: 总体超时（若不输入，则采用默认超时）
        :param verify: 是否验证证书（bool类型）或输入证书地址（str类型）
        :param json_data: 请求JSON消息体
        :raises ConnectionError: HTTP连接异常
        """
        # 拼接查询参数
        if params:
            sep = '&' if '?' in url else '?'
            url = f"{url.rstrip('?&')}{sep}{urlencode(params, doseq=True)}"
        # 合并Header
        _headers: dict[str, str] = {**self.default_headers, **(headers or {})}
        body, _headers = self._prepare_body(data, json_data, _headers)
        # 构建请求体
        _request = Request(url, data=body, headers=_headers, method=method.upper())
        try:
            # 用于区分https和http
            ctx = self._ssl_context(verify) if url.lower().startswith("https") else None
            # 打开连接执行请求
            with urlopen(_request, timeout=timeout if timeout is not None else self.default_timeout,
                         context=ctx) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                text = (content := resp.read()).decode(charset, errors="replace")
                # 返回响应结构体
                return Response(status_code=resp.status, reason=resp.reason, headers=resp.headers, text=text,
                                content=content, url=resp.geturl())
        except HTTPError as e:
            # 4xx或5xx不抛异常，正常返回Response结构体
            charset = e.headers.get_content_charset() or "utf-8" if e.headers else "utf-8"
            text = (content := e.read()).decode(charset, errors="replace")
            return Response(status_code=e.code, reason=e.reason, headers=e.headers or HTTPMessage(),
                            text=text, content=content, url=e.url)
        except URLError as e:
            # HTTP连接异常
            raise ConnectionError(ErrorCode.N_110.format_message(e.reason)) from e

    @validate_types
    def get(self, url: str, *, params: dict[str, Any] | list[tuple[str, Any]] | None = None, **kwargs) -> Response:
        """ GET请求并返回响应结构体

        :param url: 请求地址
        :param params: 请求参数
        :param kwargs: 附加参数
        :raises ConnectionError: HTTP连接异常
        """
        return self.request("GET", url, params=params, **kwargs)

    @validate_types
    def post(self, url: str, *, params: dict[str, Any] | list[tuple[str, Any]] | None = None,
             data: str | bytes | dict | None = None, json_data: Any = None, **kwargs) -> Response:
        """ POST请求并返回响应结构体

        :param url: 请求地址
        :param params: 请求参数
        :param data: 请求消息体
        :param json_data: 请求JSON消息体
        :param kwargs: 附加参数
        :raises ConnectionError: HTTP连接异常
        """
        return self.request("POST", url, params=params, data=data, json_data=json_data, **kwargs)

    @property
    def default_headers(self) -> dict[str, str]:
        return self._default_headers

http_client = _HttpClient()
""" HTTP客户端单例 """
