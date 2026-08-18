""" 记录器组件

:version: 0.3.260818
"""
from __future__ import annotations

import json
import logging
import os
import sys
from enum import IntFlag
from logging.handlers import RotatingFileHandler
from typing import Callable, Final, Annotated, cast

from piz_core.const import SysTag, namespaced
from piz_core.deco import validate_types
from piz_core.setting import Settings
from piz_core.util import to_int, DATETIME_PATTERN, NonNegative, now_as_string, real_path, is_blank, make_dirs, \
    default_string

_LOG_FILE_MIN_BYTES: Final[int] = 1024 * 1024
""" 日志文件最小容量（1MB） """
_LOG_FILE_BYTES: Final[int] = 20 * _LOG_FILE_MIN_BYTES
""" 日志文件默认容量（默认20MB） """
_LOG_BACKUP_COUNT: Final[int] = 5
""" 日志默认备份数量（默认5） """
_LOG_DIRECTORY: Final[str] = "logs"
""" 日志默认目录 """
LOG_SIMPLE_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] %(message)s"
""" 日志简略格式 """
LOG_VERBOSE_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] (%(name)s#%(funcName)s:%(lineno)d) %(message)s"
""" 日志详细格式 """


class LogMode(IntFlag):
    """ 日志记录模式枚举（由于存在与计算，不能重写 _missing_ 方法）
    """
    RECORD = 1
    """ 记录 """
    PUBLISH = 2
    """ 发布 """
    IGNORE = 64
    """ 忽略 """


class LogPayload:
    """ 日志载荷工具
    """
    KEY_MODE = "mode"
    KEY_TAG = "tag"
    KEY_NAME = "name"
    KEY_MESSAGE = "message"

    def __init__(self, value: str):
        """
        :param value: 消息数据
        """
        try:
            # 若是json格式信息
            self._v: dict = json.loads(value)
        except ValueError:
            self._v = {self.KEY_MESSAGE: value}

    def set_message(self, message: str):
        self._v[self.KEY_MESSAGE] = message

    @property
    def mode(self) -> int:
        return to_int(self._v.get(self.KEY_MODE, ""), LogMode.RECORD)

    @property
    def tag(self) -> SysTag:
        return SysTag(self._v.get(self.KEY_TAG, SysTag.OUTPUT.code))

    @property
    def name(self) -> str:
        return self._v.get(self.KEY_NAME, "")

    @property
    def message(self) -> str:
        return self._v.get(self.KEY_MESSAGE, "")

    @staticmethod
    @validate_types
    def encode(tag: SysTag, message: str, name: str = "", mode: LogMode | None = None) -> str:
        """ 载荷编码

        :param tag: 系统标签
        :param message: 日志消息
        :param name: 消息名称（默认""）
        :param mode: 日志记录模式（默认记录）
        """
        if mode is None:
            mode = Settings.log_mode
        return json.dumps({
            LogPayload.KEY_MODE: mode,
            LogPayload.KEY_TAG: tag.code,
            LogPayload.KEY_NAME: name,
            LogPayload.KEY_MESSAGE: message
        })


class _LogBaseHandler(logging.Handler):
    """ 基本日志记录处理器器
    """
    def __init__(self, mode_filter: bool = True):
        super().__init__()
        self._lpd: LogPayload = cast(LogPayload, cast(object, None))
        self._mode_filter = mode_filter
        # 默认过滤器，用于解析LogPayload
        self.addFilter(self._payload_filter)

    def _payload_filter(self, record: logging.LogRecord) -> bool:
        # 若无消息则不输出
        if is_blank(s := default_string(record.msg)):
            return False
        self._lpd = LogPayload(s)
        # 若是发布模式则数据不往下传递
        record.msg = self._lpd.message if (is_record := self._lpd.mode & LogMode.RECORD == LogMode.RECORD) else ""
        # 若日志需要记录，则返回True
        return is_record if self._mode_filter else True

    def format(self, record: logging.LogRecord) -> str:
        self._lpd.set_message(message := super().format(record))
        return message

    def apply_level(self, level: int) -> "_LogBaseHandler":
        self.setLevel(level)
        return self

    @property
    def payload(self) -> LogPayload:
        return self._lpd


class _LogStreamHandler(logging.StreamHandler, _LogBaseHandler):
    """ 流式日志记录处理器器
    """
    def __init__(self):
        super().__init__()
        _LogBaseHandler.__init__(self)
        self.set_name(namespaced("stream"))

    def apply_default_format(self) -> "_LogStreamHandler":
        self.setFormatter(logging.Formatter(fmt=LOG_SIMPLE_FORMAT, datefmt=DATETIME_PATTERN))
        return self


class _LogPublishHandler(_LogBaseHandler):
    """ 发布日志处理器
    """
    def __init__(self, publish_func: Callable[[SysTag, str, str], None] | None):
        """
        :param publish_func: 发布函数（函数参数为SysTag, str, str）
        """
        super().__init__(False)
        self._func = publish_func
        self.set_name(namespaced('publish'))

    def emit(self, record: logging.LogRecord):
        if self._func is not None:
            # 结构化record
            self.format(record)
            self._publish(record)
            # 若只是发布，则后续不需要记录
            if self._lpd.mode == LogMode.PUBLISH:
                record.msg = ""

    def _publish(self, record: logging.LogRecord):
        try:
            # 与计算，是否需要发布
            if self.payload.mode & LogMode.PUBLISH == LogMode.PUBLISH:
                self._func(self.payload.tag, self.payload.name, self.payload.message)
        except RecursionError:
            # 深层递归异常直接抛出
            raise
        except Exception:
            self.handleError(record)

    def flush(self):
        pass


class _LogRotatingFileHandler(RotatingFileHandler, _LogBaseHandler):
    """ 滚动文件日志记录处理器器
    """
    def __init__(self, name: str, log_dir: str = _LOG_DIRECTORY, max_bytes: int = _LOG_FILE_BYTES,
                 backup_count: Annotated[int, NonNegative()] = _LOG_BACKUP_COUNT):
        """
        :param name: 日志文件名称
        :param log_dir: 日志文件夹
        :param max_bytes: 单个日志文件大小
        :param backup_count: 日志文件备份数量
        """
        log_dir = real_path(log_dir)
        # 若不是文件夹或者不存在则创建文件夹
        make_dirs(log_dir)
        self._path = os.path.join(log_dir, f"{name}.log")
        # 初始化
        super().__init__(filename=self._path, maxBytes=max(max_bytes, _LOG_FILE_MIN_BYTES), backupCount=backup_count,
                         encoding=sys.getdefaultencoding())
        _LogBaseHandler.__init__(self)
        self.set_name(namespaced('rotating'))

    @property
    def file_path(self) -> str:
        return self._path


_SYS_LOG_HANDLE: Final[_LogStreamHandler] = _LogStreamHandler().apply_default_format()
""" 系统默认日志处理器 """


@validate_types
def setup_logging(file_name: str = "", level: int = logging.INFO, *, log_format: str = LOG_SIMPLE_FORMAT,
                 console: bool = True, publish_func: Callable[[SysTag, str, str], None] | None = None,
                 handler_func: Callable[[list[logging.Handler]], None] | None = None, **kwargs):
    """ 配置日志系统

    :param file_name: 滚动记录文件名称（若不为""，则装配 _LogRotatingFileHandler）
    :param level: 日志级别
    :param log_format: 日志记录格式
    :param console: 是否输出到控制台（若为True，则装配 _LogStreamHandler）
    :param publish_func: 发布函数（若不为None，则装配 _LogPublishHandler）
    :param handler_func: 处理器回调函数
    :param kwargs: _LogRotatingFileHandler相关参数
    """
    # 先移除系统默认日志处理器
    logging.root.removeHandler(_SYS_LOG_HANDLE)
    # 注意顺序不可变更
    handlers: list[logging.Handler] = []
    # 发布处理器
    if publish_func is not None:
        handlers.append(_LogPublishHandler(publish_func).apply_level(level))
    # 若有名称则记录滚动日志
    if file_name:
        handlers.append(_LogRotatingFileHandler(file_name, **kwargs).apply_level(level))
    # 控制台处理器
    if console:
        handlers.append(_LogStreamHandler().apply_level(level))
    # 若没有处理器，则使用默认处理器
    if not handlers:
        handlers.append(_LogStreamHandler().apply_default_format())
    # 处理日志处理器的函数
    if handler_func is not None:
        handler_func(handlers)
    logging.basicConfig(format=log_format, datefmt=DATETIME_PATTERN, level=logging.DEBUG, handlers=handlers, force=True)
    # 输出启动内容
    print(f"{now_as_string()}[INFO]logger initialized: {'; '.join([i.get_name() for i in handlers])}")

def initialize_system_logging():
    """ 日志系统初始化
    """
    logging.root.addHandler(_SYS_LOG_HANDLE.apply_level(logging.INFO))
