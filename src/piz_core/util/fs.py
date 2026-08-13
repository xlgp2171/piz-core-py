""" 文件系统（filesystem）处理工具

:version: 0.3.260813
"""
import os
import sys
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Generator

from piz_core.deco import validate_types
from piz_core.util.prim import default_string


@validate_types
def get_resource_as_stream(value: str | Path, mode = 'r', encoding: str | None = None, **kwargs):
    """ 打开文件并返回文件流对象

    :param value: 文件路径
    :param mode: 文件打开模式，默认为 'r'
    :param encoding: 文件编码格式，默认使用系统编码
    :param kwargs: 传递给 open 函数的额外参数
    """
    _encoding = None if 'b' in mode else (encoding or sys.getdefaultencoding())
    return open(value, mode=mode, encoding=_encoding, **kwargs)

@validate_types
def read_bytes(value: str | Path) -> bytes:
    """ 读取文件内容并返回字节流

    :param value: 文件路径
    """
    with get_resource_as_stream(value, mode='rb') as rf:
        return rf.read()

@validate_types
def read_text(value: str | Path, encoding: str | None = None, errors: str | None = None) -> str:
    """ 读取文件内容并返回字符串

    :param value: 文件路径
    :param encoding: 文件编码格式，默认使用系统编码
    :param errors: 同open的errors参数
    """
    return Path(value).read_text(encoding=encoding or sys.getdefaultencoding(), errors=errors)

@validate_types
def read_lines(value: str | Path, strip: bool = True, encoding: str | None = None, **kwargs) -> Generator:
    """ 逐行读取文件内容，返回生成器

    :param value: 文件路径
    :param strip: 是否去除每行首尾的空白字符，默认为 True
    :param encoding: 文件编码格式，默认使用系统编码
    :param kwargs: 传递给 get_resource_as_stream 的额外参数
    """
    with get_resource_as_stream(value, mode='r', encoding=encoding or sys.getdefaultencoding(), **kwargs) as rf:
        for i in rf.readlines():
            yield default_string(i, strip)

@validate_types
def path_exists(value: str | Path) -> bool:
    """ 检查指定路径是否存在
    """
    return os.path.exists(value)

@validate_types
def path_stat(value: str | Path) -> os.stat_result:
    """ 获取指定路径的状态
    """
    return Path(value).stat()

@validate_types
def is_file(value: str | Path) -> bool:
    """ 检查指定路径是否为文件
    """
    return os.path.isfile(value)

@validate_types
def is_directory(value: str | Path) -> bool:
    """检查指定路径是否为目录
    """
    return os.path.isdir(value)

@validate_types
def make_dirs(value: str | Path, parent: bool = False):
    """ 安全的创建文件夹

    :param value: 文件夹路径或文件路径
    :param parent: 是否操作的是上级文件夹
    """
    if parent:
        value = Path(value).parent
    # 若文件夹不存在或者路径存在但不是文件夹则创建文件夹
    if not path_exists(value) or not is_directory(value):
        os.makedirs(value, exist_ok=True)

@validate_types
def delete_path(value: str | Path, deep: bool = True, on_exc_func: Callable | None = None):
    """删除指定路径（文件或目录）

    :param value: 待删除的文件或目录路径
    :param deep: 若为 True 且目标为目录，则递归删除目录及其内容；若为 False，仅删除文件
    :param on_exc_func: 删除过程中发生异常时的回调函数，默认为空操作
    """
    if on_exc_func is None:
        def on_exc_func(*args):
            pass
    # 若为文件夹直接删除（要注意只读文件的情况）
    if is_directory(value):
        if deep:
            shutil.rmtree(value, onexc=on_exc_func)
    else:
        try:
            os.remove(value)
        except (PermissionError, FileNotFoundError) as err:
            if on_exc_func is not None:
                on_exc_func(os.remove, value, err)

@validate_types
def write_file(value: str | Path, data: str | bytes, mode = "w", replace = True, **kwargs):
    """ 将内容写入文件，返回内容长度

    :param value: 目标文件路径
    :param data: 待写入的字符串或字节流内容
    :param mode: 文件打开模式，默认为 "w"
    :param replace: 若文件已存在是否先删除后写入，默认为 True
    :param kwargs: 传递给 get_resource_as_stream 的额外参数
    """
    if replace and is_file(value):
        # 若存在文件则先删除
        delete_path(value, False)
    # 写入文件内容
    with get_resource_as_stream(value, mode, **kwargs) as wf:
        wf.write(data)
    return len(data)

@validate_types
def write_temporary_file(value: str | bytes , prefix: str = "",
                 process_func: Callable[[str, str | bytes], None] | None = None) -> str:
    """ 将内容写入临时文件

    :param value: 待写入的字符串或字节流内容
    :param prefix: 临时文件名前缀
    :param process_func: 文件写入后的处理回调函数，接收文件路径和内容作为参数；若提供此函数，临时文件将在处理完成后自动删除
    :return: 临时文件的绝对路径
    """
    _encoding = None if 'b' in (_mode := "wb" if isinstance(value, bytes) else "w") else sys.getdefaultencoding()

    with tempfile.NamedTemporaryFile(mode=_mode, encoding=_encoding,
                                     prefix=prefix, suffix=".tmp", delete=process_func is not None) as temp:
        temp.write(value)

        if process_func:
            process_func(temp.name, value)
    return temp.name

@validate_types
def list_paths(value: str | Path) -> list[str]:
    """ 列出指定目录下的所有子路径，若路径不是目录则返回自身（若输入为目录则返回该目录下所有子项的完整路径，否则返回包含自身的单元素列表）
    """
    if is_directory(value) and (path_list := os.listdir(value)):
        return [os.path.join(value, i) for i in path_list]
    return []

@validate_types
def walk_paths(value: str | Path, path_filter: Callable[[str, bool], bool] | None = None) -> list[str]:
    """递归遍历目录，返回符合条件的文件或目录路径列表

    :param value: 待遍历的根目录路径
    :param path_filter: 路径过滤函数，接收路径和是否为目录两个参数，返回 True 表示保留该路径；默认为过滤掉目录仅保留文件
    """
    if path_filter is None:
        def path_filter(path: str, is_dir: bool) -> bool:
            # 默认结果中不包含文件夹
            return True if path and not is_dir else False

    def _each(path_list, root_path, dir_list, file_list):
        # 文件夹过滤
        path_list.extend(path for i in dir_list if path_filter(path := str(os.path.join(root_path, i)), True))
        # 文件过滤
        path_list.extend(path for i in file_list if path_filter(path := str(os.path.join(root_path, i)), False))

    _path_list: list[str] = []

    for root, dirs, files in os.walk(value):
        _each(_path_list, root, dirs, files)

    return _path_list

@validate_types
def real_path(value: str | Path | None = None, *paths: str | Path, parent: bool = False) -> str:
    """获取基于源文件真实绝对路径（可选获取目录或附加路径片段）

    :param value: 参考文件路径
    :param paths: 相对于基准路径的后续路径片段
    :param parent: 是否获取参考文件路径的目录（默认False）
    """
    path = (Path(value) if value else Path.cwd()).resolve()
    # 是否获取目标地址目录
    if parent:
        path = path.parent
    # 是否拼接字符串
    return (path.joinpath(*paths) if paths else path).as_posix()
