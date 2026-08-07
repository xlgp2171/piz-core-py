""" 数据操作装饰器

:version: 0.3.260807
"""
from typing import Callable

from piz_core.infra.db import SqlStatement, DbOp, SqlExecutor


def select(sql: str, /, *, many: bool | None = None, res_type: type = dict):
    """ SQL的SELECT语句装饰器

    :param sql: 操作的SQL
    :param many: 返回多条还是单条（若为None时会自动通过返回类型判断）
    :param res_type: 返回类型（若返回list，还是写数据类型，即list[X]那个X）（单个简单数据int,float,str,bool,datetime直接返回）
    """
    def _decorator(func: Callable):
        from piz_core.util import get_return_annotation, is_expected_annotation
        # 若many没有设置则自动判断（list或tuple为True）
        annotation = get_return_annotation(func)
        _many = (is_expected_annotation(annotation, list) or is_expected_annotation(
            annotation, tuple)) if many is None else many
        # 标记SQL语句操作（SQL操作使用SqlStatement）
        func.__db_statement = SqlStatement(sql=sql, op=DbOp.SELECT, many=_many, res_type=res_type, executor=SqlExecutor)
        return func
    return _decorator

def _sql_decorator(sql: str, op: DbOp):
    """ execute处理装饰器
    """
    def _decorator(func: Callable):
        # 标记SQL语句操作（SQL操作使用SqlStatement）
        func.__db_statement = SqlStatement(sql=sql, op=op, many=False, res_type=dict, executor=SqlExecutor)
        return func
    return _decorator

def insert(sql: str):
    """ SQL的INSERT语句装饰器
    """
    return _sql_decorator(sql, DbOp.INSERT)

def update(sql: str):
    """ SQL的UPDATE语句装饰器
    """
    return _sql_decorator(sql, DbOp.UPDATE)

def delete(sql: str):
    """ SQL的DELETE语句装饰器
    """
    return _sql_decorator(sql, DbOp.DELETE)
