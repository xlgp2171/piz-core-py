""" 标识组件

:version: 0.2.260726
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Annotated

from piz_core.constants import ErrorCode
from piz_core.deco import validate_types
from piz_core.settings import Settings
from piz_core.util import Range


# 2018-01-01 00:00:00
_EPOCH: Final[int] = 1_514_736_000_000
""" 基准时间戳（毫秒） """
_VERSION: Final[int] = 1
""" 生成器版本号 """
_TOP: Final[int] = 1
""" 固定占位值 """
_BW_TOP: Final[int] = 1
""" 固定位位宽 """
_BW_VERSION: Final[int] = 3
""" 版本号位宽 """
_BW_TIMESTAMP: Final[int] = 40
""" 时间戳位宽 """
_BW_SEQUENCE: Final[int] = 10
""" 顺序号位宽 """
_BW_CUSTOM: Final[int] = 6
""" 自定义/业务码位宽 """
_SEQ_MAX: Final[int] = (1 << _BW_SEQUENCE) - 1
""" 顺序号最大值 """
# 位偏移量
_OFFSET_SEQUENCE: Final[int] = _BW_CUSTOM
_OFFSET_TIMESTAMP: Final[int] = _BW_CUSTOM + _BW_SEQUENCE
_OFFSET_VERSION: Final[int] = _OFFSET_TIMESTAMP + _BW_TIMESTAMP
_OFFSET_TOP: Final[int] = _OFFSET_VERSION + _BW_VERSION
# 位运算掩码
_MASK_VERSION: Final[int] = (1 << _BW_VERSION) - 1
_MASK_TIMESTAMP: Final[int] = (1 << _BW_TIMESTAMP) - 1
_MASK_SEQUENCE: Final[int] = (1 << _BW_SEQUENCE) - 1
_MASK_CUSTOM: Final[int] = (1 << _BW_CUSTOM) - 1


@dataclass(frozen=True, slots=True)
class Identity:
    """ ID元信息

    - timestamp 存储的是**相对时间戳**（毫秒，已减去 _EPOCH），
    - 以保证位宽校验的一致性。如需绝对时间戳，使用 absolute_timestamp 属性。
    """
    version: int = _VERSION
    """ 生成器版本号 """
    timestamp: int = 0
    """ 相对时间戳（毫秒） """
    sequence: int = 0
    """ 顺序号 """
    custom: int = Settings.node_id
    """ 业务标识 """
    # __init__ 执行完后再执行
    def __post_init__(self):
        """
        :raises ValueError: 数据位宽不正确
        """
        if self.custom >> _BW_CUSTOM:
            # 位宽不正确
            raise ValueError(ErrorCode.P_431.format_message("custom", _BW_CUSTOM))
        elif self.sequence >> _BW_SEQUENCE:
            # 位宽不正确
            raise ValueError(ErrorCode.P_431.format_message("sequence", _BW_SEQUENCE))
        elif self.timestamp >> _BW_TIMESTAMP:
            # 位宽不正确
            raise ValueError(ErrorCode.P_431.format_message("timestamp", _BW_TIMESTAMP))
        elif self.version >> _BW_VERSION:
            # 位宽不正确
            raise ValueError(ErrorCode.P_431.format_message("version", _BW_VERSION))

    @property
    def real_timestamp(self) -> int:
        """ 返回绝对时间戳（毫秒，已加回 _EPOCH）
        """
        return self.timestamp + _EPOCH

    @property
    def real_datetime(self) -> datetime:
        """ 返回格式化后的日期时间
        """
        return datetime.fromtimestamp(self.real_timestamp / 1000.0)


class IdFactory:
    """ ID生成器

    - 位布局：[TOP:1][VERSION:3][TIMESTAMP:40][SEQUENCE:10][CUSTOM:6]
    """
    __slots__ = ("_lock", "_last_timestamp", "_seq", "_prefix", "_version", "_time_func")

    @validate_types
    def __init__(self, custom: Annotated[int, Range(0, (1 << _BW_CUSTOM) - 1)],
                 version: Annotated[int, Range(0, (1 << _BW_VERSION) - 1)]):
        """
        :param custom: 自定义/业务码
        :param version: 标识版本
        :raises ValueError: 位宽不正确
        """
        if custom >> _BW_CUSTOM:
            # 位宽不正确
            raise ValueError(ErrorCode.P_431.format_message("custom", _BW_CUSTOM))
        if version >> _BW_VERSION:
            # 位宽不正确
            raise ValueError(ErrorCode.P_431.format_message("version", _BW_VERSION))
        self._lock = threading.Lock()
        # 最后时间戳
        self._last_timestamp = -1
        # 顺序号
        self._seq = 0
        # 版本号
        self._version = version
        # 内部时间函数
        self._time_func = time.time_ns
        # 不变部分一次性打包：TOP + VERSION + CUSTOM，之后每次只做 2 次移位和 2 次或
        self._prefix = (_BW_TOP << _OFFSET_TOP) | (version << _OFFSET_VERSION) | custom

    def next_id(self) -> int:
        """ 生成ID
        """
        with self._lock:
            timestamp = self._time_func() // 1_000_000 - _EPOCH
            # 时钟回拨：沿用上次时间戳
            if timestamp < self._last_timestamp:
                timestamp = self._last_timestamp
            if timestamp == self._last_timestamp:
                seq = self._seq + 1
                # 本毫秒 1024 个序号耗尽
                if seq > _SEQ_MAX:
                    timestamp = self._wait_next_ms(timestamp)
                    seq = 0
            else:
                seq = 0
            self._last_timestamp, self._seq = timestamp, seq
            return self._prefix | (timestamp << _OFFSET_TIMESTAMP) | (seq << _OFFSET_SEQUENCE)

    def _wait_next_ms(self, timestamp: int) -> int:
        """ 等待到下一毫秒
        """
        # 忙等下一毫秒（通常<1ms）
        deadline = time.monotonic() + 0.1

        while timestamp <= self._last_timestamp:
            timestamp = self._time_func() // 1_000_000 - _EPOCH
            # 时钟持续不前进(>100ms)
            if time.monotonic() > deadline:
                # 逻辑时钟前进 1ms，保证可用性与唯一性
                return self._last_timestamp + 1
        return timestamp

    @validate_types
    def parse(self, packed_id: int, *, ignore_version: bool) -> Identity:
        """ 将长整型ID解析为Identity结构体

        :param packed_id: generate / pack 产生的 ID
        :param ignore_version: 是否忽略版本号不匹配校验
        :raises: ValueError: 数据位宽不正确; Top值不匹配; Version值不匹配
        """
        top = (packed_id >> _OFFSET_TOP) & 1
        # 验证top
        if top != _TOP:
            # Top值不匹配
            raise ValueError(ErrorCode.P_320.format_message(_TOP, top, ",\tfield: top"))
        version = (packed_id >> _OFFSET_VERSION) & _MASK_VERSION
        # 若不忽略version则验证version
        if not ignore_version and version != self._version:
            # Version值不匹配
            raise ValueError(ErrorCode.P_320.format_message(_BW_VERSION, version, ",\tfield: version"))
        # 按位解压
        return Identity(version=version, timestamp=(packed_id >> _OFFSET_TIMESTAMP) & _MASK_TIMESTAMP,
            sequence=(packed_id >> _OFFSET_SEQUENCE) & _MASK_SEQUENCE, custom=packed_id & _MASK_CUSTOM)


class IdBuilder:
    """ 预绑定业务码的ID构建器
    """
    def __init__(self, factory: IdFactory):
        """
        :param factory: ID生成工厂
        """
        self._factory = factory

    def next_id(self) -> int:
        """ 生成下一个ID
        """
        return self._factory.next_id()

    @property
    def factory(self):
        return self._factory


class _IdGenerator:
    """ ID生成器
    """
    def __init__(self):
        self._builder_cache: dict[int, IdBuilder] = {}
        self._lock = threading.Lock()
        self._default_builder = self.get_builder(Settings.node_id, _VERSION)

    def get_builder(self, custom: int, version: int = _VERSION) -> IdBuilder:
        """ 创建预绑定业务码的构建器

        :param custom: 自定义/业务码
        :param version: 标识版本
        :raises ValueError: 位宽不正确
        """
        # 若缓存不存在则
        if custom not in self._builder_cache:
            with self._lock:
                if custom not in self._builder_cache:
                    self._builder_cache[custom] = IdBuilder(IdFactory(custom, version))
        return self._builder_cache[custom]

    def next_id(self) -> int:
        """ 使用默认生成器生成下一个ID
        """
        return self._default_builder.next_id()

    @staticmethod
    @validate_types
    def next_uuid(simple: bool = False) -> str:
        """ 生成UUID
        """
        _id = str(uuid.uuid1())
        return _id.replace("-", "") if simple else _id

    def parse(self, packed_id: int) -> Identity:
        """ 解析ID返回结构体

        :param packed_id: generate / pack 产生的 ID
        :raises: ValueError: 数据位宽不正确; Top值不匹配; Version值不匹配
        """
        return self._default_builder.factory.parse(packed_id, ignore_version=False)


id_generator: Final[_IdGenerator] = _IdGenerator()
""" ID生成器单例 """
