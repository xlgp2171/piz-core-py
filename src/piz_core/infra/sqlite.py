""" Sqlite3组件

:version: 0.3.260814
"""
from __future__ import annotations

import contextvars
import logging
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from piz_core.const import CORE_TAG, ErrorCode, namespaced, SysTag
from piz_core.deco import validate_types
from piz_core.infra.logger import LogPayload
from piz_core.infra.db import SqlDatabase
from piz_core.infra.ident import id_generator
from piz_core.util import real_path, make_dirs, StopWatch, truncate, LazyMessage


logger = logging.getLogger(__name__)


class SqliteDatabase(SqlDatabase):
    """ sqlite组件实现（读写分离）
    """
    @validate_types
    def __init__(self, path: str, timeout: float = 15.0, *, init_ddl: str | None = None):
        """
        :param path: 数据库创建地址
        :param timeout: 等待数据库锁释放的秒数
        :param init_ddl: 可选，建库时执行的初始化脚本（建表等）
        """
        self._path = real_path(path)
        self._timeout = timeout
        # 每个实例独立的事务上下文：多库并存时互不干扰（类似ThreadLocal）
        self._ctx_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(namespaced(
            f"infra_{id(self)}"), default=None)
        # 构建写连接
        # isolation_level=None：关闭Python层隐式事务（每条语句独立自动提交）
        # check_same_thread=False：跨线程使用安全
        self._write_conn = sqlite3.connect(f"file:{self._path}?mode=rwc", timeout=self._timeout,
                                           isolation_level=None, check_same_thread=False, uri=True)
        self._write_conn.row_factory = self._dict_factory
        # 开启WAL（Write-Ahead Logging）会多生成两个文件，读写不互斥
        # WAL文件xxx.db-wal：预写日志文件，新修改先写在这里，还没合并到主库
        # WAL文件xxx.db-shm：共享内存索引文件，帮助快速定位 WAL 中的内容，支持并发读
        self._write_conn.execute("PRAGMA journal_mode=WAL")
        # WAL模式下等待关键数据写入磁盘，但不强制完整fsync
        self._write_conn.execute("PRAGMA synchronous=NORMAL")
        # 构建读连接（事务自动提交，读模式，连接共享）
        # ro模式需要先构建写连接
        self._read_conn = sqlite3.connect(f"file:{self._path}?mode=ro", timeout=self._timeout,
                                           check_same_thread=False, uri=True, autocommit=True)
        self._read_conn.row_factory = self._dict_factory
        # 开启后，该连接只能执行SELECT，任何INSERT/UPDATE/DELETE/CREATE都会立即报错（防御性操作，通常mode=ro已经足够）
        self._read_conn.execute("PRAGMA query_only=ON")
        logger.info(LogPayload.encode(
                SysTag.SYSTEM, f"{CORE_TAG}Database initialized,\tsource: sqlite3,\tpath: {self._path}"))
        # 初始化DDL
        if init_ddl:
            # 执行多条SQL（用;分隔）
            self.execute_script(init_ddl)

    @staticmethod
    def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
        """ 把每行转为{列名:值}

        - join情况下的同名列前面会被后面覆盖（可使用别名规避）
        """
        return {column[0]: row[n] for n, column in enumerate(cursor.description)}

    @contextmanager
    def transaction(self) -> Iterator["SqliteDatabase"]:
        """ 事务处理

        - 可使用with db.transaction()语句开启事务
        - 块内所有读写走同一事务连接；正常结束COMMIT，抛异常ROLLBACK
        - 嵌套事务调用时使用SAVEPOINT可独立回滚
        - 写事务本质是串行的
        - 事务期间SELECT走写连接
        """
        nested = self._ctx_var.get()
        # 若存在嵌套事务，采用SAVEPOINT
        if nested is not None:
            tag = f"{namespaced(str(id_generator.next_id()))}"
            nested.execute(f"SAVEPOINT {tag}")
            logger.debug(LazyMessage(lambda: LogPayload.encode(
                SysTag.SYSTEM, f"{CORE_TAG}Transaction begin,\t\n\tsavepoint: {tag}")))
            try:
                yield self
                nested.execute(f"RELEASE SAVEPOINT {tag}")
                logger.debug(LazyMessage(lambda: LogPayload.encode(
                    SysTag.SYSTEM, f"{CORE_TAG}Transaction committed,\t\n\tsavepoint: {tag}")))
            except BaseException as e:
                nested.execute(f"ROLLBACK TO SAVEPOINT {tag}")
                logger.debug(LazyMessage(
                    lambda: LogPayload.encode(SysTag.SYSTEM,
                        f"{CORE_TAG}Transaction rollback,\t\n\tsavepoint: {tag}")), exc_info=True)
                raise
        else:
            # 把事务连接挂到当前上下文（线程/协程隔离）
            token = self._ctx_var.set(conn := self._write_conn)
            # 立即申请写锁
            conn.execute("BEGIN IMMEDIATE")
            logger.debug(LazyMessage(lambda: LogPayload.encode(
                SysTag.SYSTEM, f"{CORE_TAG}Transaction begin immediate")))
            try:
                yield self
                conn.execute("COMMIT")
                logger.debug(LazyMessage(lambda: LogPayload.encode(
                    SysTag.SYSTEM,f"{CORE_TAG}Transaction committed")))
            except BaseException as e:
                conn.execute("ROLLBACK")
                logger.debug(LazyMessage(lambda: LogPayload.encode(
                    SysTag.SYSTEM, f"{CORE_TAG}Transaction rollback")), exc_info=True)
                raise
            finally:
                # 始终清理上下文
                self._ctx_var.reset(token)

    @property
    def _reader(self) -> sqlite3.Connection:
        """ 获取读连接，事务内必须走事务连接（否则读不到自己未提交的写入），否则用读连接
        """
        return self._ctx_var.get() or self._read_conn

    @property
    def _writer(self) -> sqlite3.Connection:
        """ 获取写连接，事务内用事务连接，否则用写连接（自动提交）
        """
        return self._ctx_var.get() or self._write_conn

    @validate_types
    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        """ 执行写语句，返回受影响行数

        :param sql: 执行的SQL（INSERT/UPDATE/DELETE/DDL）
        :param params: 附加参数
        """
        with StopWatch(print_func=lambda elapsed, item: logger.debug(LazyMessage(
                lambda: LogPayload.encode(
                    SysTag.SYSTEM, f"{CORE_TAG}Sql executed,\t\n\telapsed: {elapsed}ms,\t"
                                   f"\n\tsql: {sql},\t\n\tparams: {repr(params)},\t\n\trows: {item}")))) as sw:
            sw.accept(count := self._writer.execute(sql, params).rowcount)
        return count

    @validate_types
    def execute_many(self, sql: str, params: list) -> int:
        """ 批量写入，返回受影响行数

        :param sql: 执行的SQL（INSERT/UPDATE/DELETE/DDL）
        :param params: 附加参数
        """
        with StopWatch(print_func=lambda elapsed, item: logger.debug(LazyMessage(
                lambda: LogPayload.encode(
                SysTag.SYSTEM, f"{CORE_TAG}Sql executed,\t\n\telapsed: {elapsed}ms,\t\n\tsql: {sql},\t"
                               f"\n\tparams: {repr(params)},\t\n\trows: {item}")))) as sw:
            sw.accept(count := self._writer.executemany(sql, params).rowcount)
        return count

    @validate_types
    def execute_script(self, script: str):
        """ 执行多语句脚本（sqlite3会先隐式COMMIT，勿在transaction内使用）
        """
        with StopWatch(print_func=lambda elapsed, _: logger.debug(LazyMessage(
                lambda: LogPayload.encode(SysTag.SYSTEM,
                    f"{CORE_TAG}Script executed,\t\n\telapsed: {elapsed}ms,\t\n\tscript: {repr(script)}")))):
            self._writer.executescript(script)

    @validate_types
    def query_one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        """ 查询单行，有结果返回dict否则返回None

        :param sql: 执行的SQL（SELECT）
        :param params: 附加参数
        """
        with StopWatch(print_func=lambda elapsed, item: logger.debug(LazyMessage(
                lambda: LogPayload.encode(
                    SysTag.SYSTEM, f"{CORE_TAG}Sql executed,\t\n\telapsed: {elapsed}ms,\t\n\tsql: {sql},\t"
                                   f"\n\tparams: {repr(params)},\t\n\tresult: {truncate(str(item))}")))) as sw:
            sw.accept(result := self._reader.execute(sql, params).fetchone())
        return result

    @validate_types
    def query_many(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        """ 查询多行，返回list[dict]否则返回空列表

        :param sql: 执行的SQL（SELECT）
        :param params: 附加参数
        """
        with StopWatch(print_func=lambda elapsed, item: logger.debug(LazyMessage(
                lambda: LogPayload.encode(
                    SysTag.SYSTEM, f"{CORE_TAG}sql executed,\t\n\telapsed: {elapsed}ms,\t\n\tsql: {sql},\t"
                                   f"\n\tparams: {repr(params)},\t\n\tresult: {truncate(str(item))}")))) as sw:
            sw.accept(result := self._reader.execute(sql, params).fetchall())
        return result

    @validate_types
    def query_value(self, sql: str, params: tuple | dict = (), default: Any = None) -> Any:
        """ 查询单个值（如 COUNT(*)）否则返回default

        :param sql: 执行的SQL（SELECT）
        :param params: 附加参数
        :param default: 默认值（没有数据的情况下）
        """
        row = self.query_one(sql, params)
        return default if row is None else next(iter(row.values()))

    @validate_types
    def backup(self, backup_path: str, pages: int = 1000, name: str = "main"):
        """ 在线备份数据库

        :param backup_path: 备份地址
        :param pages: 每次备份指定页后释放锁（释放时间为backup的sleep参数）
        :param name: 数据库名称（sqlite可附加数据库）
        """
        # 创建备份路径文件夹
        make_dirs(_path := real_path(backup_path), parent=True)
        dst = sqlite3.connect(_path, timeout=self._timeout, isolation_level=None)

        with StopWatch(print_func=lambda elapsed, _: logger.info(LogPayload.encode(
                SysTag.SYSTEM, f"{CORE_TAG}Database Backup,\telapsed: {elapsed}ms,\tpath: {_path}"))):
            try:
                with dst:
                    self._writer.backup(dst, pages=pages)
            except sqlite3.Error as e:
                raise RuntimeError(ErrorCode.D_810.format_message(backup_path)) from e
            finally:
                dst.close()

    def close(self):
        """ 关闭数据库
        """
        self._write_conn.close()
        self._read_conn.close()
        logger.info(LogPayload.encode(
            SysTag.SYSTEM, f"{CORE_TAG}Database closed,\tsource: sqlite3,\tpath: {self._path}"))

    def __enter__(self) -> "SqliteDatabase":
        return self

    def __exit__(self, *exc):
        self.close()
