""" 日期时间（datetime）处理工具

:version: 0.3.260805
"""
import calendar
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from piz_core.constants import ErrorCode
from piz_core.deco import validate_types


DATE_PATTERN = "%Y-%m-%d"
""" 标准日期格式（yyyy-MM-dd） """
TIME_PATTERN = "%H:%M:%S"
""" 标准时间格式（HH:mm:ss）"""
DATETIME_PATTERN = f"{DATE_PATTERN} {TIME_PATTERN}"
""" 标准日期时间格式（yyyy-MM-dd HH:mm:ss） """


@dataclass(frozen=True, slots=True)
class TimeTask:
    name: str
    """ 任务名称 """
    elapsed: int
    """ 耗费的毫秒数 """


class StopWatch:
    """ 简易计时器，支持任务历史记录和with语句
    """
    @validate_types
    def __init__(self, keep_history: bool = False, print_func: Callable[[int, Any], None] | None = None):
        """
        :param keep_history: 是否保留历史记录
        :param print_func: 打印回调函数
        """
        self._keep_history = keep_history
        self._print_func = print_func
        self._item: Any = None
        # 历史信息
        self._history: list[TimeTask] = []
        # 任务名称
        self._task_name: str | None = None
        # 起始毫秒数
        self._start_ms: int = -1
        # 最近一次耗费毫秒数
        self._last_ms: int = 0
        # 总共耗费的时间（累加_last_ms）
        self._total_ms: int = 0
        self._lock = threading.Lock()

    @staticmethod
    def _perf_ms() -> int:
        """ 返回计数器毫秒数
        """
        return int(round(time.perf_counter() * 1000))

    @validate_types
    def start(self, name: str = "") -> "StopWatch":
        """ 指定名称开启计时器

        :raises RuntimeError: 计时器无法重复启动
        """
        with self._lock:
            # 任务名称存在则计时器已启动
            if self.is_running():
                # 计时器无法重复启动
                raise RuntimeError(ErrorCode.S_221.format_message(self._task_name))
            self._task_name, self._start_ms = name, self._perf_ms()
        return self

    def stop(self) -> "StopWatch":
        """ 停止当前计时器

        :raises RuntimeError: 计时器未启动
        """
        with self._lock:
            self._stop_unsafe()
        # 输出回调函数
        if self._print_func:
            self._print_func(self.last_elapsed, self._item)
        return self

    def _stop_unsafe(self):
        """ 停止当前计时器

        :raises RuntimeError: 计时器未启动
        """
        # 任务名称不存在则计时器未启动
        if not self.is_running():
            # 计时器未启动
            raise RuntimeError(ErrorCode.S_222.message)
        # 当前耗费的毫秒数
        self._last_ms = self._perf_ms() - self._start_ms
        self._total_ms += self._last_ms
        # 若需要保留历史信息
        if self._keep_history:
            from piz_core.util.prim import default_string

            self._history.append(TimeTask(default_string(self._task_name), self._last_ms))
        self._task_name, self._start_ms = None, -1

    def reset(self) -> "StopWatch":
        """ 重置当前计时器（清空缓存，重置最后一次耗时和总耗时）

        :raises RuntimeError: 运行中无法重置
        """
        with self._lock:
            if self.is_running():
                try:
                    self._stop_unsafe()
                except Exception:
                    pass
            self._history.clear()
            self._last_ms, self._total_ms = 0, 0
        return self

    def accept(self, item: Any) -> "StopWatch":
        self._item = item
        return self

    def is_running(self) -> bool:
        """ 任务是否在运行
        """
        return self._task_name is not None

    @property
    def last_elapsed(self) -> int:
        """最近一次耗时（毫秒）
        """
        return self._last_ms

    @property
    def current_elapsed(self) -> int:
        """ 如果正在运行则返回当前已耗时（毫秒）否则返回-1
        """
        with self._lock:
            return -1 if not self.is_running() else self._perf_ms() - self._start_ms

    @property
    def total(self) -> int:
        """ 总耗时（毫秒）、
        """
        return self._total_ms

    @property
    def history(self) -> list[TimeTask]:
        return self._history.copy()

    def __enter__(self) -> "StopWatch":
        """ with方法进入
        """
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any):
        """ with方法退出
        """
        try:
            self.stop()
        except Exception:
            pass

def current_time_nanos() -> int:
    """ 当前纳秒数（自1970年1月1日00:00:00UTC开始计算）
    """
    return time.time_ns()

def current_time_millis() -> int:
    """ 当前毫秒数（自1970年1月1日00:00:00UTC开始计算）
    """
    return int(round(time.time() * 1000))

@validate_types
def to_datetime(value: str, pattern: str = DATETIME_PATTERN, *patterns: str) -> datetime:
    """ 将指定格式的日期时间字符串转换为日期时间类型

    :param value: 日期时间字符串
    :param pattern: 日期时间格式
    :param patterns: 日期时间格式组
    """
    try:
        return datetime.strptime(value, pattern)
    except ValueError:
        for i in patterns:
            try:
                return to_datetime(value, i)
            except ValueError:
                pass
        raise

@validate_types
def format_datetime(value: datetime, pattern: str = DATETIME_PATTERN) -> str:
    """ 将日期时间对象转换为指定格式的日期时间字符串

    :param value: 日期时间对象
    :param pattern: 日期时间格式
    """
    return value.strftime(pattern)

@validate_types
def format_timestamp(value: int | float, pattern: str = DATETIME_PATTERN) -> str:
    """ 将时间戳转换为指定格式的日期时间字符串

    :param value: 时间戳（毫秒）
    :param pattern: 日期时间格式
    """
    return format_datetime(datetime.fromtimestamp(value / 1_000.0), pattern)

@validate_types
def now_as_string(pattern = DATETIME_PATTERN) -> str:
    """ 将当前日期时间转换为指定格式的日期时间字符串

    :param pattern: 日期时间格式
    """
    return format_datetime(datetime.now(), pattern)

@validate_types
def add_seconds(value: datetime | None = None, amount: int = 1):
    """ 给指定日期增加/减少秒数

    :param value: 基准日期时间
    :param amount: 增加的秒数（负数表示减少）
    """
    return (value if value else datetime.now()) + timedelta(seconds=amount)

@validate_types
def add_minutes(value: datetime | None = None, amount: int = 1):
    """ 给指定日期增加/减少分钟数

    :param value: 基准日期时间
    :param amount: 增加的分钟数（负数表示减少）
    """
    return (value if value else datetime.now()) + timedelta(minutes=amount)

@validate_types
def add_hours(value: datetime | None = None, amount: int = 1):
    """ 给指定日期增加/减少小时数

    :param value: 基准日期时间
    :param amount: 增加的小时数（负数表示减少）
    """
    return (value if value else datetime.now()) + timedelta(hours=amount)


@validate_types
def add_days(value: datetime | None = None, amount: int = 1) -> datetime:
    """ 给指定日期增加/减少天数

    :param value: 基准日期时间
    :param amount: 增加的天数（负数表示减少）
    """
    return (value if value else datetime.now()) + timedelta(days=amount)


@validate_types
def add_months(value: datetime | None = None, amount: int = 1) -> datetime:
    """ 给指定日期增加/减少月数

    :param value: 基准日期时间
    :param amount: 增加的天数（负数表示减少）
    """
    if not value:
        value = datetime.now()
    # 计算目标年月
    total_months = value.year * 12 + (value.month - 1) + amount
    year = total_months // 12
    month = total_months % 12 + 1
    # 获取目标月的最后一天，防止日期溢出（如 1月31日 + 1月）
    last_day = calendar.monthrange(year, month)[1]
    day = min(value.day, last_day)
    return value.replace(year=year, month=month, day=day)

@validate_types
def add_years(value: datetime | None = None, amount: int = 1) -> datetime:
    """ 给指定日期增加/减少年数

    :param value: 基准日期时间
    :param amount: 增加的年数（负数表示减少）
    """
    if not value:
        value = datetime.now()
    target_year = value.year + amount
    try:
        return value.replace(year=target_year)
    except ValueError:
        # 原日期是闰年2月29日，目标年份非闰年，回退到该月最后一天
        _, last_day = calendar.monthrange(target_year, value.month)
        return value.replace(year=target_year, day=last_day)
