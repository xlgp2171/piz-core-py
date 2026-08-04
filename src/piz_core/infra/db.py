""" Sqlite3组件

:version: 0.3.260802
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar, Protocol, Generic, ContextManager, Self

from piz_core.constants import CORE_TAG, ErrorCode
from piz_core.infra.ioc import Injected
from piz_core.util import bind_arguments, map_row, build_sql_and_params, method_unavailable_exception, LazyMessage, \
    get_func_name, get_class_path


# 捕获任意参数签名
P = ParamSpec("P")
# 捕获返回值类型
T = TypeVar("T")
D = TypeVar("D", bound="Database")
S = TypeVar("S", bound="Statement")
logger = logging.getLogger(__name__)


class DbOp(Enum):
    """ 数据库操作枚举
    """
    SELECT = auto()
    INSERT = auto()
    UPDATE = auto()
    DELETE = auto()

    def __str__(self):
        return self.name


@dataclass(frozen=True, slots=True)
class Statement(ABC):
    """ 数据库操作基类
    """
    op: DbOp
    """ 操作的方式 """
    many: bool
    """ 操作多条还是单条 """
    res_type: Any
    """ 返回类型 """


@dataclass(frozen=True, slots=True)
class SqlStatement(Statement):
    """ SQL语句处理
    """
    sql: str
    """ 操作的SQL """


# 数据库操作基类
class Database(Protocol):
    # 事务
    def transaction(self) -> ContextManager[Self]: ...


class SqlDatabase(Database):
    """ SQL数据库操作
    """
    # 执行写语句，返回受影响行数
    def execute(self, sql: str, params: tuple | dict = ()) -> int: ...
    # 批量写入，返回受影响行数
    def execute_many(self, sql: str, params: list) -> int: ...
    # 查询单行，有结果返回dict否则返回None
    def query_one(self, sql: str, params: tuple | dict = ()) -> dict | None: ...
    # 查询单行，有结果返回基本类型否则返回default（默认None）
    def query_value(self, sql: str, params: tuple | dict = (), default: Any = None) -> Any: ...
    # 查询多行，返回list[dict]否则返回空列表
    def query_many(self, sql: str, params: tuple | dict = ()) -> list[dict]: ...


class Executor(Generic[D, S], ABC):
    """ 数据处理基类
    """
    def __init__(self, db: D, stmt: S):
        """
        :param db: 继承Database的数据库操作类
        :param stmt: 继承Statement的语句结构体
        """
        self._db: D = db
        self._stmt: S = stmt

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> Any:
        raise method_unavailable_exception()


class _SqlExecutor(Executor[SqlDatabase, SqlStatement]):
    """ SQL处理器
    """
    def execute(self, arguments: dict[str, Any]) -> Any:
        """ 根据参数字典执行DB接口

        :raises TypeError: 类型不支持; 没有匹配的操作枚举; 查询操作不支持类型
        :raises ValueError: 批量值长度不一致; 字段值获取异常; 参数值为空集合; 行数据为空; 不支持集合嵌套
        """
        # 构建sql和参数
        sql, params = build_sql_and_params(self._stmt.sql, arguments)
        logger.debug(LazyMessage(lambda: f"{CORE_TAG}Execute statement,\t\n\top: {self._stmt.op},\t"
                                         f"\n\tmany: {self._stmt.many},\t\n\tsql: {sql},\t\n\tparams: {repr(params)}"))
        # 匹配操作类型执行DB接口
        match self._stmt.op:
            case DbOp.SELECT:
                # select只支持tuple传参
                if not isinstance(params, tuple):
                    # 查询操作不支持类型
                    raise TypeError(ErrorCode.P_310.format_message(
                        get_class_path(tuple), get_class_path(params), f",\top: {DbOp.SELECT},\t"
                                                                f"class: {_SqlExecutor.__qualname__}"))
                # 根据返回数据量设置映射数据
                if self._stmt.many:
                    # 集合数据查询
                    result = self._db.query_many(sql, params)
                    return [map_row(i, self._stmt.res_type) for i in result]
                else:
                    # 单个数据查询返回简单数据
                    if self._stmt.res_type in (int, float, str, bool, datetime):
                        return self._db.query_value(sql, params)
                    # 单个数据查询返回结构体
                    result = self._db.query_one(sql, params)
                    return map_row(result, self._stmt.res_type)
            case DbOp.INSERT | DbOp.UPDATE | DbOp.DELETE:
                # 通过参数判断是集合处理还是单个处理并返回影响行数
                return self._db.execute_many(
                    sql, params) if isinstance(params, list) else self._db.execute(sql, params)
            case _:
                # 没有匹配的操作枚举
                raise TypeError(ErrorCode.P_321.format_message(
                    self._stmt.op, get_class_path(DbOp), f",\tclass: {get_class_path(_SqlExecutor)}"))


class MapperMeta(type):
    """ 数据映射元数据
    """
    def __new__(mcs, name, bases, ns, **kwargs):
        """
        :param name: 创建的类名
        :param bases: 创建的父类集合
        :param ns: 类的属性命名空间（k: 属性, v: 属性成员）
        """
        cls = super().__new__(mcs, name, bases, ns, **kwargs)
        # 语句注册表（继承父类）
        # 若参数为双下划线会触发名称改写为_MapperMeta__statements
        cls._statements = {k: v for base in reversed(cls.__mro__[1:]) for k, v in getattr(
            base, "_statements", {}).items()}
        # 遍历所有成员
        for member_name, member in ns.items():
            # 若有标记
            if stmt := getattr(member, "__db_statement", None):
                if isinstance(stmt, Statement):
                    # 缓存语句处理，方便直接获取
                    cls._statements[member_name] = stmt
                    setattr(cls, member_name, mcs._build_executor(member, stmt))
                    logger.debug(LazyMessage(lambda: f"{CORE_TAG}Build executor,\t\n\tclass: {cls.__module__}."
                                                     f"{cls.__qualname__},\t\n\tfunc: {get_func_name(member)}"))
                else:
                    logger.warning(f"{CORE_TAG}Statement invalid,"
                                   f"\tclass: {name},\tattr: {member_name},\tmember: {type(member)}")
        return cls

    @classmethod
    def _build_executor(cls, func: Callable, stmt: Statement):
        """ 为数据库方法生成执行器，替换掉类中对应函数

        :param func: 目标函数
        :param stmt: 注解语句
        """
        @wraps(func)
        def _executor(self, *args: P.args, **kwargs: P.kwargs) -> Any:
            """ 实际执行的数据操作方法

            :param self: 当前操作Mapper
            :param args: 函数参数
            :param kwargs: 函数参数
            :raises TypeError: 类型不支持; 没有匹配的操作枚举; 查询操作不支持类型
            :raises ValueError: 批量值长度不一致; 字段值获取异常; 参数值为空集合; 行数据为空; 不支持集合嵌套
            """
            # 获取参数字典
            arguments, _ = bind_arguments(func, *[self, *args], **kwargs)
            arguments.pop("self", None)
            # 若stmt是SqlStatement
            if isinstance(stmt, SqlStatement):
                # sql的执行器必须配sql的数据库
                if not isinstance(self._impl, SqlDatabase):
                    # 类型不匹配
                    raise TypeError(ErrorCode.S_231.format_message("SqlDatabase", get_class_path(self._impl)))
                # 执行操作
                return _SqlExecutor(self._impl, stmt).execute(arguments)
            else:
                # 没有匹配的类型
                raise TypeError(ErrorCode.P_310.format_message(
                    get_class_path(SqlStatement), get_class_path(stmt), f",\tclass: {get_class_path(self)}"))
        return _executor

class BaseMapper(Generic[D], metaclass=MapperMeta):
    """ 数据映射基类
    """
    _impl: Injected[D]
    """ 数据操作实现接口 """

    # noinspection PyTypeChecker
    def __init_subclass__(cls, *, impl_type: type[D] | None = None, impl_name: str = "", **kwargs):
        """
        :param impl_type: 实现类型
        :param impl_name: 实现名称
        :param kwargs: 附加参数
        """
        # 初始化父类
        super().__init_subclass__(**kwargs)
        # 构建描述符
        (injected := Injected(instance_type=impl_type, instance_name=impl_name)).__set_name__(cls, "_impl")
        # 忽略IDE警告
        cls._impl = injected

    def transaction(self) -> ContextManager[D]:
        """ 事务方法（通过with包裹使用）
        """
        return self._impl.transaction()