import base64
import hashlib
import inspect
import os
import pickle
import re
import shutil
import sys
import threading
import time
import traceback
import types
import unittest
from datetime import datetime
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import piz_core.util.coll as collection
import piz_core.util.crypto as crypto
import piz_core.util.db as database
import piz_core.util.dt as temporal
import piz_core.util.fs as filesystem
import piz_core.util.ident as identity
import piz_core.util.prim as primitive
import piz_core.util.reflect as reflect
import piz_core.util.ser as serialization
import piz_core.util.system as system

from _support import Sample, DICT_DATA_A, DICT_DATA_B, _sample_func, User, Address, PlainObj, Item, MyDict, \
    KwargsClass, FilteredClass, ReadOnlyProp, BadKwargsInit, NeedRequired, BadFilteredInit, NoMatchParams, \
    NotCallable, CallableObj, SimpleDC, WithDefault, WithInitVar, EmptyDC, print_event, MyHooks, db_service, \
    _str_annotated_func, _with_args_only, make_func


# util/coll工具测试
class TestCollection(unittest.TestCase):
    def test_split_to_set(self):
        self.assertEqual(collection.split_to_set("a , b,c", ","), {"a ", " b", "c"})
        self.assertEqual(collection.split_to_set("a , b,c", ",", lambda x: x.strip()),
                         {"a", "b", "c"})

    def test_shuffle(self):
        # 测试列表输入
        original_list = [1, 2, 3, 4, 5]
        shuffled = collection.shuffle(original_list)
        self.assertIsInstance(shuffled, list)
        self.assertEqual(len(shuffled), len(original_list))
        self.assertEqual(set(shuffled), set(original_list))
        # 测试集合输入
        original_set = {10, 20, 30}
        shuffled = collection.shuffle(original_set)
        self.assertIsInstance(shuffled, list)
        self.assertEqual(len(shuffled), len(original_set))
        self.assertEqual(set(shuffled), original_set)
        # 测试空列表
        self.assertEqual(collection.shuffle([]), [])
        # 测试空集合
        self.assertEqual(collection.shuffle(set()), [])

    def test_extract_value(self):
        addr = Address(city="Beijing", street="Chaoyang")
        user = User(name="Alice", age=30, address=addr)
        # name 直接存在于 value 中
        with self.subTest("name 直接匹配"):
            self.assertEqual(collection.extract_value({"id": 42, "name": "test"}, "id"), 42)
            self.assertEqual(collection.extract_value({"a": [1, 2]}, "a"), [1, 2])
        # name 包含点号，root 存在于 value 中，deep_get 成功（多级 dict）
        with self.subTest("点号路径 - dict 多级成功"):
            self.assertEqual(collection.extract_value({"data": {"user": {"name": "Bob"}}},
                                                      "data.user.name"),"Bob")
        # name 包含点号，root 存在于 value 中，deep_get 失败（中间键不存在）
        with self.subTest("点号路径 - dict 中间键缺失抛 KeyError"):
            with self.assertRaises(KeyError):
                collection.extract_value({"data": {"user": {}}}, "data.user.name")
        # name 包含点号，root 不存在于 value 中，后续进入其他分支判断
        with self.subTest("点号路径 - root 不存在且非单参数对象"):
            with self.assertRaises(ValueError) as ctx:
                collection.extract_value({"other": 123, "extra": 456}, "data.user.name")
            self.assertIn("data.user.name", str(ctx.exception))
        # value 长度为1且唯一值是 param_object（dataclass），deep_get 成功
        with self.subTest("单参数 dataclass - 成功"):
            self.assertEqual(collection.extract_value({"user": user}, "name"), "Alice")
            self.assertEqual(collection.extract_value({"user": user}, "age"), 30)
            self.assertEqual(collection.extract_value({"user": user}, "address.city"), "Beijing")
        # value 长度为1且唯一值是 param_object，deep_get 失败（属性不存在）
        with self.subTest("单参数 dataclass - 属性不存在抛 AttributeError"):
            with self.assertRaises(AttributeError):
                collection.extract_value({"user": user}, "nonexistent")
        # value 长度为1但唯一值不是 param_object，name 含点号且 root 匹配到基础类型
        # deep_get 会在非 Mapping 对象上 getattr，对 int 会抛 AttributeError
        with self.subTest("单参数非对象 - 点号路径 root 匹配 int 抛 AttributeError"):
            with self.assertRaises(AttributeError):
                collection.extract_value({"plain": 123}, "plain.x")
        # 若 root 匹配到 dict 但深层 key 不存在，则抛 KeyError
        with self.subTest("单参数非对象 - 点号路径 root 匹配 dict 但深层缺失抛 KeyError"):
            with self.assertRaises(KeyError):
                collection.extract_value({"plain": {"a": 1}}, "plain.x")
        # 若 name 不含点号且不在 value 中，则抛 ValueError
        with self.subTest("单参数非对象 - 无点号不匹配抛 ValueError"):
            with self.assertRaises(ValueError):
                collection.extract_value({"plain": 123}, "missing")
        # value 长度大于1，name 不存在
        with self.subTest("多参数且 name 不存在"):
            with self.assertRaises(ValueError) as ctx:
                collection.extract_value({"a": 1, "b": 2}, "c")
            self.assertIn("c", str(ctx.exception))
        # value 为空，name 不存在
        with self.subTest("空字典"):
            with self.assertRaises(ValueError):
                collection.extract_value({}, "x")
        # error_hint 被包含在异常消息中
        with self.subTest("error_hint 附加消息"):
            with self.assertRaises(ValueError) as ctx:
                collection.extract_value({"a": 1}, "b", error_hint="custom hint")
            msg = str(ctx.exception)
            self.assertIn("b", msg)
            self.assertIn("custom hint", msg)

    def test_deep_get(self):
        # value 为 None
        with self.subTest("value 为 None"):
            self.assertIsNone(collection.deep_get(None, "a"))
            self.assertEqual(collection.deep_get(None, "a", default="fallback"), "fallback")
        # keys 为空
        with self.subTest("keys 为空"):
            self.assertIsNone(collection.deep_get({"a": 1}))
            self.assertEqual(collection.deep_get({"a": 1}, default="empty_keys"), "empty_keys")
        # value 为 Mapping，key 存在
        with self.subTest("Mapping key 存在"):
            self.assertEqual(collection.deep_get({"a": 1, "b": 2}, "a"), 1)
            self.assertEqual(collection.deep_get({"nested": {"x": 10}}, "nested"), {"x": 10})
        # value 为 Mapping，key 不存在，ignore_errors=False
        with self.subTest("Mapping key 不存在且 ignore_errors=False"):
            with self.assertRaises(KeyError):
                collection.deep_get({"a": 1}, "z")
        # value 为 Mapping，key 不存在，ignore_errors=True
        with self.subTest("Mapping key 不存在且 ignore_errors=True"):
            self.assertIsNone(collection.deep_get({"a": 1}, "z", ignore_errors=True))
            self.assertEqual(collection.deep_get(
                {"a": 1}, "z", default="def", ignore_errors=True), "def")
        # value 为对象，key 作为属性存在
        with self.subTest("对象属性存在"):
            obj = PlainObj()
            self.assertEqual(collection.deep_get(obj, "x"), 100)
        # value 为对象，key 作为属性不存在，ignore_errors=False
        with self.subTest("对象属性不存在且 ignore_errors=False"):
            obj = PlainObj()
            with self.assertRaises(AttributeError):
                collection.deep_get(obj, "y")
        # value 为对象，key 作为属性不存在，ignore_errors=True
        with self.subTest("对象属性不存在且 ignore_errors=True"):
            obj = PlainObj()
            self.assertIsNone(collection.deep_get(obj, "y", ignore_errors=True))
            self.assertEqual(collection.deep_get(obj, "y", default=999, ignore_errors=True), 999)
        # 9. 多级 keys，全部存在（dict + 对象混合）
        with self.subTest("多级 keys 全部存在"):
            addr = Address(city="Shanghai", street="Nanjing")
            user = User(name="Tom", age=25, address=addr)
            data = {"user": user}
            self.assertEqual(collection.deep_get(data, "user", "address", "city"), "Shanghai")
        # 多级 keys，中间某级不存在，ignore_errors=False
        with self.subTest("多级 keys 中间缺失且 ignore_errors=False"):
            with self.assertRaises(KeyError):
                collection.deep_get({"a": {"b": 1}}, "a", "z", "c")
        # 多级 keys，中间某级不存在，ignore_errors=True
        with self.subTest("多级 keys 中间缺失且 ignore_errors=True"):
            self.assertEqual(collection.deep_get({"a": {"b": 1}}, "a", "z", "c", default="miss",
                                                 ignore_errors=True),"miss")
        # default 自定义值验证
        # 注意：default 仅在 value 为 None、keys 为空、或 ignore_errors=True 时生效
        with self.subTest("default 自定义值 - ignore_errors=True"):
            self.assertEqual(collection.deep_get({}, "k", default=[], ignore_errors=True), [])
            self.assertEqual(collection.deep_get(
                {}, "k", default={"a": 1}, ignore_errors=True), {"a": 1})
            self.assertEqual(collection.deep_get(None, "k", default=0), 0)

    def test_get_nested(self):
        # 正常多级嵌套
        self.assertEqual(collection.get_nested(
            DICT_DATA_A, "level1", "level2", "key", expected=str, default="default"), "value")
        self.assertEqual(collection.get_nested(
            DICT_DATA_A, "level1", "num", expected=int, default=0), 42)
        # 键不存在，返回默认值
        self.assertEqual(collection.get_nested(
            DICT_DATA_A, "level1", "x", expected=str, default="default"), "default")
        self.assertEqual(collection.get_nested(
            DICT_DATA_A, "nonexistent", expected=str, default="default"), "default")
        # 类型不匹配，返回默认值
        self.assertEqual(collection.get_nested(
            DICT_DATA_A, "level1", "num", expected=str, default="default"), "default")
        self.assertEqual(collection.get_nested(
            DICT_DATA_A, "level1", "level2", "key", expected=int, default=0), 0)
        # value 为 None
        self.assertEqual(collection.get_nested(
            None, "level1", expected=str, default="default"), "default")
        # keys 为空
        self.assertEqual(collection.get_nested(DICT_DATA_A, expected=str, default="default"), "default")
        # 单级键
        self.assertEqual(collection.get_nested(
            {"key": "val"}, "key", expected=str, default="default"), "val")

    def test_get_nested_as_dict(self):
        # 正常多级嵌套
        self.assertEqual(collection.get_nested_as_dict(
            DICT_DATA_A, "level1", "level2"), {"level3": {"key": "val"}, "key": "value"})
        self.assertEqual(collection.get_nested_as_dict(
            DICT_DATA_A, "level1", "level2", "level3"), {"key": "val"})
        # 单级键
        self.assertEqual(collection.get_nested_as_dict(
            DICT_DATA_A, "level1"), {'level2': {'key': 'value', 'level3': {'key': 'val'}}, 'num': 42})
        # value 为 None
        self.assertEqual(collection.get_nested_as_dict(None, "a"), {})
        # keys 为空
        self.assertEqual(collection.get_nested_as_dict(DICT_DATA_A), {})
        # 中间键不存在
        self.assertEqual(collection.get_nested_as_dict(DICT_DATA_A, "level1", "nonexistent"), {})
        # 中间键对应的值不是字典
        self.assertEqual(collection.get_nested_as_dict(DICT_DATA_A, "level1", "num"), {})
        # 顶层键不存在
        self.assertEqual(collection.get_nested_as_dict(DICT_DATA_A, "nonexistent"), {})

    def test_get_as_dict(self):
        # 正常获取字典
        self.assertEqual(collection.get_as_dict(DICT_DATA_B, "dict_key"), {"inner": "value"})
        # key 不存在
        self.assertEqual(collection.get_as_dict(DICT_DATA_B, "missing"), {})
        # 值不是字典
        self.assertEqual(collection.get_as_dict(DICT_DATA_B, "list_key"), {})
        self.assertEqual(collection.get_as_dict(DICT_DATA_B, "str_key"), {})
        # 空字典
        self.assertEqual(collection.get_as_dict({}, "any"), {})

    def test_dict_deep_merge(self):
        # override 中的 key 不在 value 中
        with self.subTest("override 新增 key"):
            result = collection.dict_deep_merge({"a": 1}, {"b": 2})
            self.assertEqual(result, {"a": 1, "b": 2})
        # 两者都是 Mapping → 递归合并
        with self.subTest("Mapping 递归合并"):
            result = collection.dict_deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3, "z": 4}})
            self.assertEqual(result, {"a": {"x": 1, "y": 3, "z": 4}})
        # 两者都是 Sequence（非 str/bytes）→ override 替换为 list
        with self.subTest("Sequence 替换为 list"):
            result = collection.dict_deep_merge({"a": [1, 2, 3]},{"a": (4, 5)})
            self.assertEqual(result, {"a": [4, 5]})
            self.assertIsInstance(result["a"], list)
        # 一个是 Mapping 一个是 Sequence → 直接替换
        with self.subTest("Mapping vs Sequence 直接替换"):
            result = collection.dict_deep_merge({"a": {"x": 1}},{"a": [1, 2]})
            self.assertEqual(result, {"a": [1, 2]})
            result2 = collection.dict_deep_merge({"a": [1, 2]},{"a": {"x": 1}})
            self.assertEqual(result2, {"a": {"x": 1}})
        # 都是基本类型 → 直接替换
        with self.subTest("基本类型直接替换"):
            result = collection.dict_deep_merge({"a": 1, "b": "old"},{"a": 2, "b": "new"})
            self.assertEqual(result, {"a": 2, "b": "new"})
        # str 被排除在 Sequence 外 → 直接替换
        with self.subTest("str 直接替换（非 Sequence 合并）"):
            result = collection.dict_deep_merge({"a": "hello"},{"a": "world"})
            self.assertEqual(result, {"a": "world"})
        # 空 value，非空 override
        with self.subTest("空 value"):
            result = collection.dict_deep_merge({}, {"a": 1})
            self.assertEqual(result, {"a": 1})
        # 空 override
        with self.subTest("空 override"):
            result = collection.dict_deep_merge({"a": 1, "b": 2}, {})
            self.assertEqual(result, {"a": 1, "b": 2})
        # 嵌套 Mapping 的深层合并（三层）
        with self.subTest("深层嵌套合并"):
            result = collection.dict_deep_merge(
                {"level1": {"level2": {"a": 1,"b": 2}}},{"level1": {"level2": {"b": 20,"c": 30}}})
            self.assertEqual(result,{"level1": {"level2": {"a": 1,"b": 20, "c": 30}}})
        # Sequence 替换验证：tuple 覆盖 list，结果应为 list
        with self.subTest("tuple 覆盖 list"):
            result = collection.dict_deep_merge({"items": [1, 2]},{"items": (3, 4, 5)})
            self.assertEqual(result["items"], [3, 4, 5])
        # bytes 被排除在 Sequence 外 → 直接替换
        with self.subTest("bytes 直接替换"):
            result = collection.dict_deep_merge({"data": b"old"},{"data": b"new"})
            self.assertEqual(result, {"data": b"new"})

    def test_sequence_merge(self):
        with self.subTest(msg="两个序列都为 None"):
            self.assertEqual(collection.sequence_merge(None, None), [])
        with self.subTest(msg="左侧为 None"):
            self.assertEqual(collection.sequence_merge(None, [1, 2, 3]), [1, 2, 3])
        with self.subTest(msg="右侧为 None"):
            self.assertEqual(collection.sequence_merge([1, 2, 3], None), [1, 2, 3])
        with self.subTest(msg="不去重，直接拼接"):
            self.assertEqual(collection.sequence_merge([1, 2, 2], [2, 3, 3]), [1, 2, 2, 2, 3, 3])
        with self.subTest(msg="按值去重（简单类型）"):
            self.assertEqual(
                collection.sequence_merge([1, 2, 2], [2, 3, 3], key_func=lambda x: x), [1, 2, 3])
        with self.subTest(msg="按对象身份去重（复杂类型）"):
            # 值相同，不同对象
            a, b = [1], [1]
            # 和 a 同一对象
            c = a
            self.assertEqual(collection.sequence_merge([a, b], [c, b], key_func=id), [a, b])
        with self.subTest(msg="顺序优先级：以第一次出现为主"):
            self.assertEqual(
                collection.sequence_merge([3, 1, 2], [1, 3, 4], key_func=lambda x: x), [3, 1, 2, 4])
        with self.subTest(msg="空序列合并"):
            self.assertEqual(collection.sequence_merge([], [1, 2], key_func=lambda x: x), [1, 2])
            self.assertEqual(collection.sequence_merge([1, 2], [], key_func=lambda x: x), [1, 2])
        with self.subTest(msg="tuple 作为输入"):
            self.assertEqual(
                collection.sequence_merge((1, 2), (2, 3), key_func=lambda x: x), [1, 2, 3])
        with self.subTest(msg="字符串按值去重"):
            self.assertEqual(collection.sequence_merge(["a", "b"], ["b", "c"],
                                                       key_func=lambda x: x), ["a", "b", "c"])


# util/crypto工具测试
class TestCrypto(unittest.TestCase):
    def test_to_hash(self):
        # 单个 bytes 参数
        result = crypto.to_hash(b"hello")
        self.assertEqual(result, hashlib.sha256(b"hello").hexdigest())
        self.assertIsInstance(result, str)
        # 多个 bytes 参数（连续 update）
        sha = hashlib.sha256()
        sha.update(b"hello")
        sha.update(b" ")
        sha.update(b"world")
        self.assertEqual(crypto.to_hash(b"hello", b" ", b"world"), sha.hexdigest())
        # 空 bytes 参数
        self.assertEqual(crypto.to_hash(b""), hashlib.sha256(b"").hexdigest())
        # 多个空 bytes 参数
        sha = hashlib.sha256()
        sha.update(b"")
        sha.update(b"")
        self.assertEqual(crypto.to_hash(b"", b""), sha.hexdigest())

    def test_to_base64_as_string(self):
        # value 为 str，encoding 为 None（默认系统编码）
        value_str = "hello world"
        result = crypto.to_base64_as_string(value_str)
        self.assertEqual(result, base64.standard_b64encode(
            value_str.encode(sys.getdefaultencoding())).decode(sys.getdefaultencoding()))
        self.assertIsInstance(result, str)
        # value 为 str，encoding 指定为 utf-8
        expected = base64.standard_b64encode(value_str.encode("utf-8")).decode("utf-8")
        self.assertEqual(crypto.to_base64_as_string(value_str, "utf-8"), expected)
        # value 为 bytes，encoding 为 None
        value_bytes = b"hello world"
        self.assertEqual(crypto.to_base64_as_string(value_bytes),
                         base64.standard_b64encode(value_bytes).decode(sys.getdefaultencoding()))
        # value 为 bytes，encoding 指定为 utf-8
        self.assertEqual(crypto.to_base64_as_string(value_bytes, "utf-8"),
                         base64.standard_b64encode(value_bytes).decode("utf-8"))
        # 空字符串
        self.assertEqual(crypto.to_base64_as_string(""),
                         base64.standard_b64encode(b"").decode(sys.getdefaultencoding()))

    def test_from_base64_as_stream(self):
        # 正常 base64 字符串
        original = b"hello world"
        result = crypto.from_base64_as_stream(base64.standard_b64encode(original).decode("ascii"))
        self.assertEqual(result, original)
        self.assertIsInstance(result, bytes)
        # 空字符串
        self.assertEqual(crypto.from_base64_as_stream(""), b"")
        # 包含不可打印字符的 bytes
        original = b"\x00\x01\x02\xff\xfe"
        self.assertEqual(crypto.from_base64_as_stream(base64.standard_b64encode(original).decode("ascii")), original)

    def test_from_base64_as_string(self):
        # value 为正常 base64 字符串，encoding 为 None（默认系统编码）
        original = "hello world"
        result = crypto.from_base64_as_string(
            base64.standard_b64encode(original.encode(sys.getdefaultencoding())).decode(sys.getdefaultencoding()))
        self.assertEqual(result, original)
        self.assertIsInstance(result, str)
        # value 为正常 base64 字符串，encoding 指定为 utf-8
        original = "你好世界"
        self.assertEqual(crypto.from_base64_as_string(
            base64.standard_b64encode(original.encode("utf-8")).decode("utf-8"), "utf-8"), original)
        # 空字符串
        self.assertEqual(crypto.from_base64_as_string(""), "")
        # 与 to_base64_as_string 的 round-trip 测试
        original = "round-trip test 123 !@#"
        self.assertEqual(crypto.from_base64_as_string(
            crypto.to_base64_as_string(original, "utf-8"), "utf-8"), original)


# util/db工具测试
class TestDatabase(unittest.TestCase):
    def test_build_params(self):
        # 多参数字典，返回 tuple，按 names 顺序提取
        self.assertEqual(database.build_params({"a": 1, "b": "hello"},["a", "b"]),(1, "hello"))
        # names 顺序与字典键顺序无关
        self.assertEqual(database.build_params({"a": 1, "b": "hello"},["b", "a"]),("hello", 1))
        # 单参数且值为 list，批量提取（deep_get 按点号路径）
        users = [{"id": 1, "name": "Alice"},{"id": 2, "name": "Bob"}]
        self.assertEqual(
            database.build_params({"users": users}, ["id", "name"]),[(1, "Alice"), (2, "Bob")])
        # 单参数且值为 tuple，同样走批量逻辑
        self.assertEqual(
            database.build_params({"items": ({"x": 10}, {"x": 20})}, ["x"]),[(10,), (20,)]
        )
        # 单参数但值为标量，不走批量，走 extract_value（点号路径）
        self.assertEqual(
            database.build_params({"data": {"nested": {"val": 99}}},["data.nested.val"]),(99,))
        # 空 names 返回空 tuple
        self.assertEqual(database.build_params({"a": 1}, []), ())
        # 空 arguments 且非批量，extract_value 会抛 ValueError
        with self.assertRaises(ValueError):
            database.build_params({}, ["a"])
        # 批量模式下，元素缺少字段会抛 KeyError（deep_get 触发）
        with self.assertRaises(KeyError):
            database.build_params({"users": [{"id": 1}]}, ["id", "name"])

    def test_build_sql_and_params(self):
        # 无占位符，原样返回，params 为空 tuple
        sql, params = database.build_sql_and_params("SELECT 1", {})
        self.assertEqual(sql, "SELECT 1")
        self.assertEqual(params, ())
        # 单个标量占位符
        sql, params = database.build_sql_and_params("SELECT * FROM t WHERE id = #{id}", {"id": 42})
        self.assertEqual(sql, "SELECT * FROM t WHERE id = ?")
        self.assertEqual(params, (42,))
        # 多个标量占位符
        sql, params = database.build_sql_and_params("INSERT INTO t VALUES(#{a}, #{b})",{"a": 1, "b": "x"})
        self.assertEqual(sql, "INSERT INTO t VALUES(?, ?)")
        self.assertEqual(params, (1, "x"))
        # 占位符对应 list 值（IN 语句展开）
        sql, params = database.build_sql_and_params(
            "SELECT * FROM t WHERE id IN(#{ids})", {"ids": [1, 2, 3]})
        self.assertEqual(sql, "SELECT * FROM t WHERE id IN(?,?,?)")
        self.assertEqual(params, (1, 2, 3))
        # 占位符对应 tuple 值（IN 语句展开）
        sql, params = database.build_sql_and_params(
            "SELECT * FROM t WHERE id IN(#{ids})", {"ids": (4, 5)})
        self.assertEqual(sql, "SELECT * FROM t WHERE id IN(?,?)")
        self.assertEqual(params, (4, 5))
        # 混合标量和集合占位符
        sql, params = database.build_sql_and_params(
            "SELECT * FROM t WHERE a = #{a} AND b IN(#{b})", {"a": 1, "b": [2, 3]})
        self.assertEqual(sql, "SELECT * FROM t WHERE a = ? AND b IN(?,?)")
        self.assertEqual(params, (1, 2, 3))
        # 空 list 值抛 ValueError（参数值为空集合）
        with self.assertRaises(ValueError) as ctx:
            database.build_sql_and_params("SELECT * FROM t WHERE id IN(#{ids})", {"ids": []})
        self.assertIn("ids", str(ctx.exception))
        # list 值元素为 row 数据（嵌套集合）抛 ValueError
        # 注意：必须提供两个参数避免进入批量模式，否则整体绑定不会触发 P_333
        with self.assertRaises(ValueError) as ctx:
            database.build_sql_and_params(
                "SELECT * FROM t WHERE id IN(#{items})",{"items": [{"x": 1}], "other": 1})
        self.assertIn("items", str(ctx.exception))
        # 占位符名称不存在抛 ValueError（来自 extract_value）
        with self.assertRaises(ValueError):
            database.build_sql_and_params("SELECT * FROM t WHERE id = #{missing}", {"id": 1})
        # error_hint 附加到异常消息
        with self.assertRaises(ValueError) as ctx:
            database.build_sql_and_params(
                "SELECT * FROM t WHERE id = #{missing}", {"id": 1}, error_hint="[user query]")
        self.assertIn("missing", str(ctx.exception))
        # list of tuple 整体绑定
        sql, params = database.build_sql_and_params(
            "INSERT INTO t VALUES(#{values})",{"values": [(1, "a"), (2, "b")]})
        self.assertEqual(sql, "INSERT INTO t VALUES(?,?)")
        self.assertEqual(params, [(1, "a"), (2, "b")])
        # list of dict 整体绑定
        sql, params = database.build_sql_and_params(
            "INSERT INTO t VALUES(#{rows})",{"rows": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]})
        self.assertEqual(sql, "INSERT INTO t VALUES(?,?)")
        # dict.values() 顺序取决于键顺序，这里用单元素或固定顺序
        self.assertEqual(params[0], (1, "a"))
        self.assertEqual(params[1], (2, "b"))
        # list of dataclass 整体绑定
        sql, params = database.build_sql_and_params(
            "INSERT INTO t VALUES(#{users})",{"users": [User("A", 10), User("B", 25)]})
        self.assertEqual(sql, "INSERT INTO t VALUES(?,?,?)")
        self.assertEqual(params, [("A", 10, None), ("B", 25, None)])
        # 空行数据抛 ValueError（行数据为空）
        with self.assertRaises(ValueError):
            database.build_sql_and_params("INSERT INTO t VALUES(#{rows})", {"rows": [()]})
        # 批量数据每行长度不一致抛 ValueError
        with self.assertRaises(ValueError) as ctx:
            database.build_sql_and_params("INSERT INTO t VALUES(#{rows})",{"rows": [(1, 2), (1, 2, 3)]})
        self.assertIn("Row length mismatch", str(ctx.exception))
        # list of dict 逐字段提取
        sql, params = database.build_sql_and_params("INSERT INTO t VALUES(#{uid}, #{name})",
                                                    {"users": [{"uid": 1, "name": "A"}, {"uid": 2, "name": "B"}]})
        self.assertEqual(sql, "INSERT INTO t VALUES(?, ?)")
        self.assertEqual(params, [(1, "A"), (2, "B")])
        # list of object 逐字段提取（deep_get 获取属性）
        sql, params = database.build_sql_and_params(
            "INSERT INTO t VALUES(#{x}, #{y})",{"items": [Item(10, 20), Item(30, 40)]})
        self.assertEqual(sql, "INSERT INTO t VALUES(?, ?)")
        self.assertEqual(params, [(10, 20), (30, 40)])
        # 逐元素提取时字段缺失抛 ValueError（字段值获取异常）
        with self.assertRaises(ValueError):
            database.build_sql_and_params("INSERT INTO t VALUES(#{uid}, #{name})",{"users": [{"uid": 1}]})
        # 批量判定：单参数但值为空列表，不走批量，走单条（extract_value 会返回空 list）
        # 空列表作为标量值，在单条模式下会被视为 IN 的空集合，抛 ValueError
        with self.assertRaises(ValueError):
            database.build_sql_and_params("SELECT * FROM t WHERE id IN(#{ids})", {"ids": []})
        # 批量判定：单参数但首元素不是 row 数据，不走批量
        # 例如值为 [1, 2, 3]，不是 row 数据，走单条 IN 展开
        sql, params = database.build_sql_and_params(
            "SELECT * FROM t WHERE id IN(#{ids})", {"ids": [1, 2, 3]})
        self.assertEqual(sql, "SELECT * FROM t WHERE id IN(?,?,?)")
        self.assertEqual(params, (1, 2, 3))

    def test_map_row(self):
        # value 为 None，直接返回 None
        self.assertIsNone(database.map_row(None, dict))
        self.assertIsNone(database.map_row(None, str, strict=True))
        # res_type 为 None，返回原 value
        self.assertEqual(database.map_row({"a": 1}, None), {"a": 1})
        # res_type 是 dict 子类，返回原 value
        self.assertEqual(database.map_row({"a": 1}, dict), {"a": 1})
        self.assertEqual(database.map_row({"a": 1}, MyDict), {"a": 1})
        # res_type 有 **kwargs，直接传入整个 dict
        obj = database.map_row({"name": "Alice", "age": 30}, KwargsClass)
        self.assertIsInstance(obj, KwargsClass)
        self.assertEqual(obj.name, "Alice")
        self.assertEqual(obj.age, 30)
        # res_type 有匹配参数，按签名过滤传参
        obj = database.map_row({"name": "Bob", "age": 25, "extra": "ignored"}, FilteredClass)
        self.assertIsInstance(obj, FilteredClass)
        self.assertEqual(obj.name, "Bob")
        self.assertEqual(obj.age, 25)
        self.assertFalse(hasattr(obj, "extra"))
        obj = database.map_row({"name": "Charlie", "age": 35}, User)
        self.assertIsInstance(obj, User)
        self.assertEqual(obj.name, "Charlie")
        self.assertEqual(obj.age, 35)
        # strict=True + 有 **kwargs 但 __init__ 内部抛异常 → 被 catch 后重新抛 TypeError(P_105)
        with self.assertRaises(TypeError) as ctx:
            database.map_row({"trigger": "bad"}, BadKwargsInit, strict=True)
        self.assertIn("argument missing", str(ctx.exception))
        self.assertIn("BadKwargsInit", str(ctx.exception))
        # strict=True + 过滤参数后构造抛异常（如必填参数缺失）→ 被 catch 后重新抛 TypeError(P_105)
        with self.assertRaises(TypeError) as ctx:
            database.map_row({"other": 1}, NeedRequired, strict=True)
        self.assertIn("argument missing", str(ctx.exception))
        self.assertIn("NeedRequired", str(ctx.exception))
        # strict=True + 过滤参数后 __init__ 内部抛 ValueError → 被 catch 后重新抛 TypeError(P_105)
        with self.assertRaises(TypeError) as ctx:
            database.map_row({"name": "bad"}, BadFilteredInit, strict=True)
        self.assertIn("argument missing", str(ctx.exception))
        # strict=True + 完全没有匹配参数（kwargs 为空）→ 主动 raise TypeError，被 catch 后重新抛 TypeError(P_105)
        with self.assertRaises(TypeError) as ctx:
            database.map_row({"x": 1, "y": 2}, NoMatchParams, strict=True)
        self.assertIn("argument missing", str(ctx.exception))
        self.assertIn("NoMatchParams", str(ctx.exception))
        # strict=False（默认）+ 无匹配参数 → 回退 setattr
        obj = database.map_row({"x": 1, "y": 2}, NoMatchParams, strict=False)
        self.assertIsInstance(obj, NoMatchParams)
        self.assertEqual(obj.x, 1)
        self.assertEqual(obj.y, 2)
        # strict=False + 过滤参数后构造失败 → 回退 setattr
        obj = database.map_row({"name": "bad"}, BadFilteredInit, strict=False)
        self.assertIsInstance(obj, BadFilteredInit)
        self.assertEqual(obj.name, "bad")  # setattr 成功设置
        # strict=False + 有 **kwargs 但构造失败 → 回退 setattr
        obj = database.map_row({"trigger": "bad"}, BadKwargsInit, strict=False)
        self.assertIsInstance(obj, BadKwargsInit)
        self.assertEqual(obj.trigger, "bad")
        # setattr 失败时跳过（如 property 无 setter）
        obj = database.map_row({"x": 999, "y": 888}, ReadOnlyProp, strict=False)
        self.assertIsInstance(obj, ReadOnlyProp)
        self.assertEqual(obj.y, 888)
        # x 是只读 property，setattr 会失败并被跳过，保持类属性默认值
        self.assertEqual(obj.x, 0)
        # 空 dict 映射
        obj = database.map_row({}, KwargsClass)
        self.assertIsInstance(obj, KwargsClass)
        # strict 默认值测试（应为 False）
        obj = database.map_row({"x": 1}, NoMatchParams)
        self.assertIsInstance(obj, NoMatchParams)
        self.assertEqual(obj.x, 1)

# util/dt工具测试
class TestDatatime(unittest.TestCase):
    def test_current_time_millis(self):
        result = temporal.current_time_millis()
        self.assertIsInstance(result, int)
        # 验证结果在合理范围内（当前时间前后5秒内）
        expected = int(round(time.time() * 1000))
        self.assertAlmostEqual(result, expected, delta=1000)

    def test_to_datetime(self):
        # 测试 value 参数（默认 pattern）
        self.assertEqual(temporal.to_datetime("2024-01-15 10:30:45"),
                         datetime(2024, 1, 15, 10, 30, 45))
        # 测试 value 和 pattern 参数（自定义格式）
        self.assertEqual(temporal.to_datetime("15/01/2024 10:30", "%d/%m/%Y %H:%M"),
                         datetime(2024, 1, 15, 10, 30))
        self.assertEqual(temporal.to_datetime("15/01/2024 10:30:21",
                                               temporal.DATETIME_PATTERN, "%d/%m/%Y %H:%M:%S"),
                         datetime(2024, 1, 15, 10, 30, 21))

    def test_format_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 45)
        # 测试 date 参数（默认 pattern）
        self.assertEqual(temporal.format_datetime(dt), "2024-01-15 10:30:45")
        # 测试 date 和 pattern 参数（自定义格式）
        self.assertEqual(temporal.format_datetime(dt, "%Y年%m月%d日 %H:%M"), "2024年01月15日 10:30")

    def test_format_timestamp(self):
        tp = datetime(2024, 1, 15, 10, 30, 45).timestamp() * 1000.0
        # 测试 date 参数（默认 pattern）
        self.assertEqual(temporal.format_timestamp(tp), "2024-01-15 10:30:45")
        # 测试 date 和 pattern 参数（自定义格式）
        self.assertEqual(temporal.format_timestamp(tp, "%Y年%m月%d日 %H:%M"), "2024年01月15日 10:30")

    def test_now_as_string(self):
        with patch('piz_core.util.dt.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 10, 23, 4)
            self.assertEqual(temporal.now_as_string(), "2024-01-15 10:23:04")
            self.assertEqual(temporal.now_as_string("%Y年%m月%d日"), "2024年01月15日")

    def test_add_seconds(self):
        dt = datetime(2024, 1, 15, 10, 0, 0)
        # 测试 value 参数（指定值）和正数 amount
        self.assertEqual(temporal.add_seconds(dt, 30),
                         datetime(2024, 1, 15, 10, 0, 30))
        # 测试负数 amount
        self.assertEqual(temporal.add_seconds(dt, -45),
                          datetime(2024, 1, 15, 9, 59, 15))
        # 测试 value 为 None（默认当前时间）和 amount 参数
        with patch('piz_core.util.dt.datetime') as mock_dt:
            mock_dt.now.return_value = dt
            self.assertEqual(temporal.add_seconds(None, 10),
                             datetime(2024, 1, 15, 10, 0, 10))

    def test_add_minutes(self):
        dt = datetime(2024, 1, 15, 10, 0, 0)
        # 测试 value 参数和正数 amount
        self.assertEqual(temporal.add_minutes(dt, 5),
                         datetime(2024, 1, 15, 10, 5, 0))
        # 测试负数 amount
        self.assertEqual(temporal.add_minutes(dt, -10),
                         datetime(2024, 1, 15, 9, 50, 0))
        # 测试 value 为 None
        with patch('piz_core.util.dt.datetime') as mock_dt:
            mock_dt.now.return_value = dt
            self.assertEqual(temporal.add_minutes(None, 3),
                             datetime(2024, 1, 15, 10, 3, 0))

    def test_add_hours(self):
        dt = datetime(2024, 1, 15, 10, 0, 0)
        # 测试 value 参数和正数 amount
        self.assertEqual(temporal.add_hours(dt, 3),
                         datetime(2024, 1, 15, 13, 0, 0))
        # 测试负数 amount
        self.assertEqual(temporal.add_hours(dt, -5),
                         datetime(2024, 1, 15, 5, 0, 0))
        # 测试 value 为 None
        with patch('piz_core.util.dt.datetime') as mock_dt:
            mock_dt.now.return_value = dt
            self.assertEqual(temporal.add_hours(None, 2),
                             datetime(2024, 1, 15, 12, 0, 0))

    def test_add_days(self):
        dt = datetime(2024, 1, 15, 10, 0, 0)
        # 测试 value 参数和正数 amount
        self.assertEqual(temporal.add_days(dt, 5),
                         datetime(2024, 1, 20, 10, 0, 0))
        # 测试负数 amount
        self.assertEqual(temporal.add_days(dt, -10),
                         datetime(2024, 1, 5, 10, 0, 0))
        # 测试 value 为 None
        with patch('piz_core.util.dt.datetime') as mock_dt:
            mock_dt.now.return_value = dt
            self.assertEqual(temporal.add_days(None, 1),
                             datetime(2024, 1, 16, 10, 0, 0))

    def test_add_months(self):
        dt = datetime(2024, 1, 15, 10, 0, 0)
        # 测试 value 参数和正数 amount
        self.assertEqual(temporal.add_months(dt, 2),
                         datetime(2024, 3, 15, 10, 0, 0))
        # 测试负数 amount（跨年度）
        self.assertEqual(temporal.add_months(dt, -3),
                         datetime(2023, 10, 15, 10, 0, 0))
        # 测试月末日期溢出（1月31日 + 1月 → 2月29日，2024是闰年）
        dt_end = datetime(2024, 1, 31, 10, 0, 0)
        self.assertEqual(temporal.add_months(dt_end, 1),
                         datetime(2024, 2, 29, 10, 0, 0))
        # 测试月末日期溢出到非闰年（2024年1月31日 + 13月 → 2025年2月28日）
        self.assertEqual(temporal.add_months(dt_end, 13),
                         datetime(2025, 2, 28, 10, 0, 0))
        # 测试 value 为 None
        with patch('piz_core.util.dt.datetime') as mock_dt:
            mock_dt.now.return_value = dt
            self.assertEqual(temporal.add_months(None, 1),
                             datetime(2024, 2, 15, 10, 0, 0))

    def test_add_years(self):
        dt = datetime(2024, 6, 15, 10, 0, 0)
        # 测试 value 参数和正数 amount
        self.assertEqual(temporal.add_years(dt, 2),
                         datetime(2026, 6, 15, 10, 0, 0))
        # 测试负数 amount
        self.assertEqual(temporal.add_years(dt, -1),
                         datetime(2023, 6, 15, 10, 0, 0))
        # 测试闰年2月29日加到非闰年
        leap_day = datetime(2024, 2, 29, 10, 0, 0)
        self.assertEqual(temporal.add_years(leap_day, 1),
                         datetime(2025, 2, 28, 10, 0, 0))
        # 测试闰年2月29日加到另一个闰年
        self.assertEqual(temporal.add_years(leap_day, 4),
                         datetime(2028, 2, 29, 10, 0, 0))
        # 测试 value 为 None
        with patch('piz_core.util.dt.datetime') as mock_dt:
            mock_dt.now.return_value = dt
            self.assertEqual(temporal.add_years(None, 1),
                             datetime(2025, 6, 15, 10, 0, 0))

    def test_stopwatch(self):
        # 测试默认参数初始化后的内部状态
        with self.subTest("init_default"):
            sw = temporal.StopWatch()
            self.assertFalse(sw._keep_history)
            self.assertIsNone(sw._print_func)
            self.assertIsNone(sw._item)
            self.assertEqual(sw._history, [])
            self.assertIsNone(sw._task_name)
            self.assertEqual(sw._start_ms, -1)
            self.assertEqual(sw._last_ms, 0)
            self.assertEqual(sw._total_ms, 0)
            self.assertIsInstance(sw._lock, type(threading.Lock()))
        # 测试自定义 keep_history 和 print_func 参数初始化
        with self.subTest("init_custom"):
            captured = []

            def pf(task, item):
                captured.append((task.elapsed, item))
            sw = temporal.StopWatch(keep_history=True, print_func=pf)
            self.assertTrue(sw._keep_history)
            self.assertIs(sw._print_func, pf)
        # 测试 start 方法默认名称（空字符串）启动计时器
        with self.subTest("start_default_name"):
            sw = temporal.StopWatch()
            ret = sw.start()
            self.assertIs(ret, sw)
            self.assertTrue(sw.is_running())
            self.assertEqual(sw._task_name, "")
            sw.stop()
        # 测试 start 方法指定名称启动计时器
        with self.subTest("start_with_name"):
            sw = temporal.StopWatch()
            ret = sw.start("task1")
            self.assertIs(ret, sw)
            self.assertEqual(sw._task_name, "task1")
            self.assertTrue(sw.is_running())
            sw.stop()
        # 测试 start 方法在计时器已运行时重复启动抛出 RuntimeError
        with self.subTest("start_duplicate_raises"):
            sw = temporal.StopWatch()
            sw.start("task2")

            with self.assertRaises(RuntimeError):
                sw.start("task3")
            sw.stop()
        # 测试 stop 方法正常停止并记录耗时
        with self.subTest("stop_normal"):
            sw = temporal.StopWatch()
            sw.start()
            time.sleep(0.01)
            ret = sw.stop()
            self.assertIs(ret, sw)
            self.assertFalse(sw.is_running())
            self.assertGreaterEqual(sw.last_task.elapsed, 10)
            self.assertEqual(sw.total, sw.last_task.elapsed)
        # 测试 stop 方法在计时器未启动时抛出 RuntimeError
        with self.subTest("stop_not_running_raises"):
            sw = temporal.StopWatch()

            with self.assertRaises(RuntimeError):
                sw.stop()
        # 测试 stop 方法触发 print_func 回调并传入耗时和 item
        with self.subTest("stop_print_func_callback"):
            captured = []

            def pf(task, item):
                captured.append((task.elapsed, item))
            sw = temporal.StopWatch(print_func=pf)
            sw.start()
            time.sleep(0.01)
            sw.stop()
            self.assertEqual(len(captured), 1)
            self.assertGreaterEqual(captured[0][0], 10)
            self.assertIsNone(captured[0][1])
        # 测试 reset 方法在空闲状态下清空历史记录和耗时统计
        with self.subTest("reset_idle"):
            sw = temporal.StopWatch(keep_history=True)
            sw.start("t1")
            time.sleep(0.01)
            sw.stop()
            self.assertGreater(sw.total, 0)
            self.assertEqual(len(sw.history), 1)
            ret = sw.reset()
            self.assertIs(ret, sw)
            self.assertEqual(sw.last_task.elapsed, -1)
            self.assertEqual(sw.total, 0)
            self.assertEqual(sw.history, [])
            self.assertFalse(sw.is_running())
        # 测试 reset 方法在计时器运行中强制停止并清空数据
        with self.subTest("reset_while_running"):
            sw = temporal.StopWatch()
            sw.start("t2")
            time.sleep(0.01)
            sw.reset()
            self.assertFalse(sw.is_running())
            self.assertEqual(sw.total, 0)
        # 测试 accept 方法链式调用设置 item
        with self.subTest("accept_chain"):
            sw = temporal.StopWatch()
            ret = sw.accept("my_item")
            self.assertIs(ret, sw)
            self.assertEqual(sw._item, "my_item")
        # 测试 accept 设置的 item 在 stop 时通过 print_func 回调传出
        with self.subTest("accept_passed_to_print_func"):
            captured = []

            def pf(task, item):
                captured.append(item)
            sw = temporal.StopWatch(print_func=pf)
            sw.accept({"key": "value"})
            sw.start()
            time.sleep(0.01)
            sw.stop()
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0], {"key": "value"})
        # 测试 is_running 在初始、启动后、停止后的状态变化
        with self.subTest("is_running_state"):
            sw = temporal.StopWatch()
            self.assertFalse(sw.is_running())
            sw.start()
            self.assertTrue(sw.is_running())
            sw.stop()
            self.assertFalse(sw.is_running())
        # 测试 last_elapsed 属性记录最近一次 stop 的耗时
        with self.subTest("last_elapsed"):
            sw = temporal.StopWatch()
            self.assertEqual(sw.last_task.elapsed, -1)
            sw.start()
            time.sleep(0.02)
            sw.stop()
            first = sw.last_task.elapsed
            self.assertGreaterEqual(first, 20)
            sw.start()
            time.sleep(0.01)
            sw.stop()
            second = sw.last_task.elapsed
            self.assertGreaterEqual(second, 10)
            self.assertLess(second, first + 10)
        # 测试 current_elapsed 属性返回运行中的当前已耗时，未运行返回 -1
        with self.subTest("current_elapsed"):
            sw = temporal.StopWatch()
            self.assertEqual(sw.current_elapsed, -1)
            sw.start()
            time.sleep(0.02)
            elapsed = sw.current_elapsed
            self.assertGreaterEqual(elapsed, 20)
            sw.stop()
        # 测试 total 属性累加多次 stop 的耗时
        with self.subTest("total"):
            sw = temporal.StopWatch()
            self.assertEqual(sw.total, 0)
            sw.start()
            time.sleep(0.01)
            sw.stop()
            first_total = sw.total
            self.assertGreaterEqual(first_total, 10)
            sw.start()
            time.sleep(0.01)
            sw.stop()
            self.assertGreaterEqual(sw.total, first_total + 10)
            self.assertEqual(sw.total, first_total + sw.last_task.elapsed)
        # 测试默认 keep_history=False 时 stop 后不保留历史记录
        with self.subTest("history_default_no_keep"):
            sw = temporal.StopWatch()
            sw.start("t1")
            time.sleep(0.01)
            sw.stop()
            self.assertEqual(sw.history, [])
        # 测试 keep_history=True 时保留历史记录，且 history 返回的是内部副本
        with self.subTest("history_keep_and_copy"):
            sw = temporal.StopWatch(keep_history=True)
            sw.start("t1")
            time.sleep(0.01)
            sw.stop()
            sw.start("t2")
            time.sleep(0.01)
            sw.stop()
            hist = sw.history
            self.assertEqual(len(hist), 2)
            # 验证返回的是副本，修改外部列表不影响内部
            hist.clear()
            self.assertEqual(len(sw.history), 2)
            # 验证记录内容
            self.assertEqual(sw.history[0].name, "t1")
            self.assertGreaterEqual(sw.history[0].elapsed, 10)
            self.assertEqual(sw.history[1].name, "t2")
            self.assertGreaterEqual(sw.history[1].elapsed, 10)
        # 测试 __enter__ 方法进入 with 时启动计时并返回 self
        with self.subTest("enter"):
            sw = temporal.StopWatch()
            ret = sw.__enter__()
            self.assertIs(ret, sw)
            self.assertTrue(sw.is_running())
            sw.stop()
        # 测试 __exit__ 方法正常退出 with 时停止计时
        with self.subTest("exit_normal"):
            sw = temporal.StopWatch()

            with sw:
                self.assertTrue(sw.is_running())
            self.assertFalse(sw.is_running())
            self.assertGreaterEqual(sw.last_task.elapsed, 0)
        # 测试 __exit__ 方法在 with 块抛出异常时仍能停止计时
        with self.subTest("exit_exception_still_stops"):
            sw = temporal.StopWatch()

            with self.assertRaises(ValueError):
                with sw:
                    self.assertTrue(sw.is_running())
                    raise ValueError("test error")
            self.assertFalse(sw.is_running())
            self.assertGreaterEqual(sw.last_task.elapsed, 0)
        # 测试 __exit__ 方法不抑制异常，异常会继续向上传播
        with self.subTest("exit_does_not_suppress_exception"):
            with self.assertRaises(RuntimeError):
                with temporal.StopWatch():
                    raise RuntimeError("propagate")

# util/fs工具测试
class TestFilesystemUtils(unittest.TestCase):
    def setUp(self):
        # 创建临时测试目录
        path = os.path.dirname(__file__)
        self.temp_dir = os.path.join(str(path), "test_dir")

        if not os.path.exists(self.temp_dir):
            os.mkdir(self.temp_dir)
        self.temp_file = os.path.join(self.temp_dir, "test.txt")

        with open(self.temp_file, "w", encoding="utf-8") as f:
            f.write("hello world")

    def tearDown(self):
        # 清理临时测试目录
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_resource_as_stream(self):
        # 测试默认参数（mode='r', encoding=None）
        with filesystem.get_resource_as_stream(self.temp_file) as f:
            self.assertEqual(f.read(), "hello world")
        # 测试指定 mode='rb'
        with filesystem.get_resource_as_stream(self.temp_file, mode='rb') as f:
            self.assertEqual(f.read(), b"hello world")
        # 测试指定 encoding
        with filesystem.get_resource_as_stream(self.temp_file, encoding="utf-8") as f:
            self.assertEqual(f.read(), "hello world")
        # 测试 kwargs 传递（如 errors 参数）
        with filesystem.get_resource_as_stream(self.temp_file, errors="strict") as f:
            self.assertEqual(f.read(), "hello world")

    def test_read_bytes(self):
        # 测试读取文件为字节流
        result = filesystem.read_bytes(self.temp_file)
        self.assertEqual(result, b"hello world")
        self.assertIsInstance(result, bytes)

    def test_read_lines(self):
        # 准备多行文件
        multi_line_file = os.path.join(self.temp_dir, "multi.txt")

        with open(multi_line_file, "w", encoding="utf-8") as f:
            f.write("  line1  \n")
            f.write("line2\n")
            f.write("  line3")
        # 测试默认 strip=True
        lines = list(filesystem.read_lines(multi_line_file))
        self.assertEqual(lines, ["line1", "line2", "line3"])
        # 测试 strip=False
        lines = list(filesystem.read_lines(multi_line_file, strip=False))
        self.assertEqual(lines, ["  line1  \n", "line2\n", "  line3"])
        # 测试 kwargs 传递（如 encoding）
        lines = list(filesystem.read_lines(multi_line_file, encoding="utf-8"))
        self.assertEqual(lines, ["line1", "line2", "line3"])

    def test_path_exists(self):
        # 测试存在的文件路径
        self.assertTrue(filesystem.path_exists(self.temp_file))
        # 测试存在的目录路径
        self.assertTrue(filesystem.path_exists(self.temp_dir))
        # 测试不存在的路径
        nonexistent = os.path.join(self.temp_dir, "nonexistent.txt")
        self.assertFalse(filesystem.path_exists(nonexistent))

    def test_path_stat(self):
        # value 为存在的文件路径（str）：应返回 stat_result，且大小正确
        stat = filesystem.path_stat(self.temp_file)
        self.assertIsInstance(stat, os.stat_result)
        self.assertEqual(stat.st_size, len("hello world"))
        # value 为存在的目录路径（str）：应返回 stat_result，且为目录类型
        stat_dir = filesystem.path_stat(self.temp_dir)
        self.assertIsInstance(stat_dir, os.stat_result)
        # st_mode 中 S_IFDIR 标志位（0o40000）用于判断是否为目录
        self.assertTrue(stat_dir.st_mode & 0o40000)
        # value 为不存在的路径（str）：应抛 FileNotFoundError
        nonexistent = os.path.join(self.temp_dir, "nonexistent.txt")

        with self.assertRaises(FileNotFoundError):
            filesystem.path_stat(nonexistent)
        # value 为空字符串（str）：Path("") 指向当前目录 "."，stat 调用成功
        stat_empty = filesystem.path_stat("")
        self.assertIsInstance(stat_empty, os.stat_result)
        self.assertTrue(stat_empty.st_mode & 0o40000)
        # value 为 None：Path(None) 会抛 TypeError
        with self.assertRaises(TypeError):
            filesystem.path_stat(None)
        # value 为 Path 对象（存在的文件）：应正常工作
        path_obj = Path(self.temp_file)
        stat_from_path = filesystem.path_stat(path_obj)
        self.assertIsInstance(stat_from_path, os.stat_result)
        self.assertEqual(stat_from_path.st_size, len("hello world"))
        # value 为 Path 对象（存在的目录）：应正常工作
        dir_obj = Path(self.temp_dir)
        stat_dir_from_path = filesystem.path_stat(dir_obj)
        self.assertIsInstance(stat_dir_from_path, os.stat_result)
        self.assertTrue(stat_dir_from_path.st_mode & 0o40000)

    def test_is_file(self):
        # 测试文件路径
        self.assertTrue(filesystem.is_file(self.temp_file))
        # 测试目录路径（应为 False）
        self.assertFalse(filesystem.is_file(self.temp_dir))
        # 测试不存在的路径
        nonexistent = os.path.join(self.temp_dir, "nonexistent.txt")
        self.assertFalse(filesystem.is_file(nonexistent))

    def test_is_directory(self):
        # 测试目录路径
        self.assertTrue(filesystem.is_directory(self.temp_dir))
        # 测试文件路径（应为 False）
        self.assertFalse(filesystem.is_directory(self.temp_file))
        # 测试不存在的路径
        nonexistent = os.path.join(self.temp_dir, "nonexistent")
        self.assertFalse(filesystem.is_directory(nonexistent))

    def test_make_dirs(self):
        # value 为不存在的目录路径（str），parent=False（默认）：应创建目录
        new_dir = os.path.join(self.temp_dir, "new_folder")
        self.assertFalse(os.path.exists(new_dir))
        filesystem.make_dirs(new_dir)
        self.assertTrue(os.path.isdir(new_dir))
        # value 为不存在的目录路径（Path 对象），parent=False：应创建目录
        new_dir_path = Path(self.temp_dir) / "new_folder_path"
        self.assertFalse(new_dir_path.exists())
        filesystem.make_dirs(new_dir_path)
        self.assertTrue(new_dir_path.is_dir())
        # value 为已存在的目录路径，parent=False：不应抛异常，目录仍存在
        filesystem.make_dirs(new_dir)
        self.assertTrue(os.path.isdir(new_dir))
        # value 为文件路径，parent=False：路径存在但不是目录， os.makedirs 对已存在的文件会抛 FileExistsError
        with self.assertRaises(FileExistsError):
            filesystem.make_dirs(self.temp_file)
        # value 为目录路径，parent=True：应创建 value 的上级目录（value 本身作为子目录不应被创建）
        child_dir = os.path.join(self.temp_dir, "parent_test", "child")
        filesystem.make_dirs(child_dir, parent=True)
        self.assertTrue(os.path.isdir(os.path.join(self.temp_dir, "parent_test")))
        self.assertFalse(os.path.exists(child_dir))
        # value 为文件路径，parent=True：应创建文件所在的目录
        file_path = os.path.join(self.temp_dir, "file_dir", "file.txt")
        filesystem.make_dirs(file_path, parent=True)
        self.assertTrue(os.path.isdir(os.path.join(self.temp_dir, "file_dir")))
        self.assertFalse(os.path.exists(file_path))
        # value 为空字符串，parent=True：Path("").parent 为 Path("."), 当前目录已存在，调用成功
        filesystem.make_dirs("", parent=True)
        self.assertTrue(os.path.isdir("."))
        # value 为 None，parent=False：Path(None) 会抛 TypeError
        with self.assertRaises(TypeError):
            filesystem.make_dirs(None)
        # value 为 None，parent=True：Path(None).parent 同样会抛 TypeError
        with self.assertRaises(TypeError):
            filesystem.make_dirs(None, parent=True)

    def test_delete_path(self):
        # 删除文件（deep 默认为 True，不影响文件删除）
        temp_file = os.path.join(self.temp_dir, "delete_file.txt")

        with open(temp_file, "w") as f:
            f.write("delete")
        filesystem.delete_path(temp_file)
        self.assertFalse(os.path.exists(temp_file))
        # 删除文件，deep=False（文件仍应被删除）
        temp_file2 = os.path.join(self.temp_dir, "delete_file2.txt")

        with open(temp_file2, "w") as f:
            f.write("delete")
        filesystem.delete_path(temp_file2, deep=False)
        self.assertFalse(os.path.exists(temp_file2))
        # 递归删除目录（deep=True）
        nested_dir = os.path.join(self.temp_dir, "nested")
        os.makedirs(os.path.join(nested_dir, "sub"))

        with open(os.path.join(nested_dir, "sub", "file.txt"), "w") as f:
            f.write("content")
        filesystem.delete_path(nested_dir, deep=True)
        self.assertFalse(os.path.exists(nested_dir))
        # deep=False 时不删除目录
        keep_dir = os.path.join(self.temp_dir, "keep_dir")
        os.makedirs(keep_dir)
        filesystem.delete_path(keep_dir, deep=False)
        self.assertTrue(os.path.exists(keep_dir))
        # 删除不存在的文件，触发 FileNotFoundError，on_exc_func 被调用
        exc_calls = []

        def capture_exc(func, path, err):
            exc_calls.append((func, path, type(err).__name__))
        nonexistent_file = os.path.join(self.temp_dir, "noexist.txt")
        filesystem.delete_path(nonexistent_file, on_exc_func=capture_exc)
        self.assertEqual(len(exc_calls), 1)
        self.assertEqual(exc_calls[0][0], os.remove)
        self.assertEqual(exc_calls[0][2], "FileNotFoundError")
        # 删除不存在的目录且 deep=True，shutil.rmtree 触发异常，onexc 被调用
        exc_calls_rmtree = []

        def capture_rmtree_exc(func, path, exc_info):
            exc_calls_rmtree.append((func.__name__, path, exc_info))
        nonexistent_dir = os.path.join(self.temp_dir, "noexist_dir")
        filesystem.delete_path(nonexistent_dir, deep=True, on_exc_func=capture_rmtree_exc)
        self.assertGreaterEqual(len(exc_calls_rmtree), 1)
        # on_exc_func=None 时默认空操作，不抛异常
        filesystem.delete_path(os.path.join(self.temp_dir, "noexist2.txt"), on_exc_func=None)
        # 删除只读文件（若系统支持），触发 PermissionError
        readonly_file = os.path.join(self.temp_dir, "readonly.txt")

        with open(readonly_file, "w") as f:
            f.write("readonly")
        os.chmod(readonly_file, 0o444)
        exc_perm = []

        def capture_perm(func, path, err):
            exc_perm.append(type(err).__name__)
        filesystem.delete_path(readonly_file, on_exc_func=capture_perm)
        os.chmod(readonly_file, 0o644)  # 恢复权限以便清理

    def test_write_file(self):
        # 测试基本写入（data 为字符串）
        target = os.path.join(self.temp_dir, "write_test.txt")
        length = filesystem.write_file(target, "test content")
        self.assertEqual(length, len("test content"))

        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "test content")
        # 测试写入 bytes 数据
        target_bin = os.path.join(self.temp_dir, "write_test.bin")
        filesystem.write_file(target_bin, b"binary data", mode="wb")

        with open(target_bin, "rb") as f:
            self.assertEqual(f.read(), b"binary data")
        # 测试 replace=False
        existing = os.path.join(self.temp_dir, "existing.txt")

        with open(existing, "w") as f:
            f.write("old")
        filesystem.write_file(existing, "new", replace=False)

        with open(existing, "r") as f:
            self.assertEqual(f.read(), "new")
        # 测试 replace=True（先删除再写入）
        filesystem.write_file(existing, "replaced", replace=True)

        with open(existing, "r") as f:
            self.assertEqual(f.read(), "replaced")
        # 测试 kwargs 传递
        filesystem.write_file(target, "encoded", encoding="utf-8")

        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "encoded")

    def test_write_temporary_file(self):
        # 测试写入字符串，无 prefix、无 process_func，delete=False，文件保留
        path = filesystem.write_temporary_file("temp content")
        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.isfile(path))

        with open(path, "r", encoding=sys.getdefaultencoding()) as f:
            self.assertEqual(f.read(), "temp content")
        os.remove(path)
        # 测试写入 bytes，无 prefix、无 process_func，delete=False，文件保留
        path_bin = filesystem.write_temporary_file(b"temp bytes")
        self.assertTrue(os.path.exists(path_bin))
        self.assertTrue(os.path.isfile(path_bin))

        with open(path_bin, "rb") as f:
            self.assertEqual(f.read(), b"temp bytes")
        os.remove(path_bin)
        # 测试 prefix 参数
        path_prefix = filesystem.write_temporary_file("content", prefix="my_prefix_")
        self.assertTrue(os.path.basename(path_prefix).startswith("my_prefix_"))
        self.assertTrue(os.path.exists(path_prefix))

        with open(path_prefix, "r", encoding=sys.getdefaultencoding()) as f:
            self.assertEqual(f.read(), "content")
        os.remove(path_prefix)
        # 测试 process_func 参数（delete=True，回调在 with 内执行）
        # 注意：NamedTemporaryFile 在 with 内仍持有文件句柄，Windows 上外部无法再次 open
        # 因此 process_func 中只验证路径存在和 content 参数正确，不重新 open 文件
        processed = [False]
        captured_path = [None]
        captured_content = [None]

        def process(arg_path, content):
            processed[0] = True
            captured_path[0] = arg_path
            captured_content[0] = content
            # 验证文件路径存在（文件对象仍由 NamedTemporaryFile 持有）
            self.assertTrue(os.path.exists(arg_path))
            # 不重新 open 文件，避免 Windows 文件占用冲突
        path_proc = filesystem.write_temporary_file("processed content", process_func=process)
        self.assertTrue(processed[0])
        self.assertEqual(path_proc, captured_path[0])
        self.assertEqual(captured_content[0], "processed content")
        # with 结束后文件已被删除
        self.assertFalse(os.path.exists(path_proc))
        # 测试 process_func + bytes
        processed_bin = [False]

        def process_bin(arg_path, content):
            processed_bin[0] = True
            self.assertTrue(os.path.exists(arg_path))
            self.assertEqual(content, b"binary data")
            # 同样不重新 open 文件
        path_proc_bin = filesystem.write_temporary_file(b"binary data", process_func=process_bin)
        self.assertTrue(processed_bin[0])
        self.assertFalse(os.path.exists(path_proc_bin))

    def test_list_paths(self):
        # 测试目录（包含多个文件）
        sub_dir = os.path.join(self.temp_dir, "sub")
        os.makedirs(sub_dir)
        file1 = os.path.join(self.temp_dir, "a.txt")
        file2 = os.path.join(self.temp_dir, "b.txt")
        open(file1, "w").close()
        open(file2, "w").close()
        result = filesystem.list_paths(self.temp_dir)
        # sub, a.txt, b.txt
        self.assertIn(file1, result)
        self.assertIn(file2, result)
        self.assertIn(sub_dir, result)
        # 测试空目录
        empty_dir = os.path.join(self.temp_dir, "empty")
        os.makedirs(empty_dir)
        self.assertEqual(filesystem.list_paths(empty_dir), [])
        # 测试非目录路径（文件）
        self.assertEqual(filesystem.list_paths(file1), [])

    def test_walk_paths(self):
        # 构建目录结构
        root = os.path.join(self.temp_dir, "walk_root")
        os.makedirs(os.path.join(root, "dir1", "dir2"))

        with open(os.path.join(root, "file1.txt"), "w") as f:
            f.write("1")
        with open(os.path.join(root, "dir1", "file2.txt"), "w") as f:
            f.write("2")
        with open(os.path.join(root, "dir1", "dir2", "file3.txt"), "w") as f:
            f.write("3")
        # 测试默认 path_filter（只返回文件）
        files = filesystem.walk_paths(root)
        self.assertEqual(len(files), 3)
        self.assertTrue(all(os.path.isfile(p) for p in files))
        # 测试自定义 path_filter（只返回 .txt 文件）
        def txt_only(path, is_dir):
            return not is_dir and path.endswith(".txt")
        txt_files = filesystem.walk_paths(root, path_filter=txt_only)
        self.assertEqual(len(txt_files), 3)
        # 测试自定义 path_filter（包含目录）
        def include_dirs(path, is_dir):
            return True
        all_paths = filesystem.walk_paths(root, path_filter=include_dirs)
        self.assertGreater(len(all_paths), 3)  # 包含目录
        # 测试 path_filter 过滤特定目录
        def exclude_dir2(path, is_dir):
            if is_dir:
                return "dir2" not in path
            return True
        filtered = filesystem.walk_paths(root, path_filter=exclude_dir2)
        # file1.txt 和 file2.txt
        self.assertIn(os.path.join(root, "file1.txt"), filtered)
        self.assertIn(os.path.join(root, "dir1", "file2.txt"), filtered)

    def test_real_path(self):
        # value 为具体路径，parent=False（默认），无 paths
        self.assertTrue(filesystem.real_path("/tmp/test/file.txt").endswith("/tmp/test/file.txt"))
        # value 为具体路径，parent=True，无 paths
        self.assertTrue(filesystem.real_path("/tmp/test/file.txt", parent=True).endswith("/tmp/test"))
        # value 为具体路径，parent=False，有 paths
        self.assertTrue(
            filesystem.real_path("/tmp/test", "a", "b.txt", parent=False).endswith("/tmp/test/a/b.txt"))
        # value 为具体路径，parent=True，有 paths
        self.assertTrue(filesystem.real_path("/tmp/test/file.txt", "subdir", "file.txt", parent=True)
                         .endswith("/tmp/test/subdir/file.txt"))
        # value 为 None，parent=False（默认），无 paths
        result = filesystem.real_path(None)
        self.assertTrue(os.path.isabs(result))
        # value 为 None，parent=True，无 paths
        result = filesystem.real_path(None, parent=True)
        self.assertTrue(os.path.isabs(result))
        # value 为 None，parent=False，有 paths
        result = filesystem.real_path(None, "extra", "path", parent=False)
        self.assertTrue(os.path.isabs(result))
        self.assertTrue("extra" in result)
        self.assertTrue(result.endswith("path"))
        # value 为 None，parent=True，有 paths
        result = filesystem.real_path(None, "extra", "path", parent=True)
        self.assertTrue(os.path.isabs(result))
        self.assertTrue("extra" in result)
        self.assertTrue(result.endswith("path"))
        # value 为空字符串
        result = filesystem.real_path("")
        self.assertTrue(os.path.isabs(result))


# util/prim工具测试
class TestPrimitive(unittest.TestCase):
    def test_default_string(self):
        # value=None
        self.assertEqual(primitive.default_string(None), "")
        # value为普通字符串
        self.assertEqual(primitive.default_string("hello"), "hello")
        # value为数字
        self.assertEqual(primitive.default_string(123), "123")
        # value为对象
        self.assertEqual(primitive.default_string([1, 2]), "[1, 2]")
        self.assertEqual(primitive.default_string(Sample("")), "0")
        # strip=False
        self.assertEqual(primitive.default_string("  hello  "), "  hello  ")
        # strip=True
        self.assertEqual(primitive.default_string("  hello  ", strip=True), "hello")
        # value=None, strip=True
        self.assertEqual(primitive.default_string(None, strip=True), "")

    def test_equals_ignore_case(self):
        # 完全匹配
        self.assertTrue(primitive.equals_ignore_case("abc", "abc"))
        # 大小写不同
        self.assertTrue(primitive.equals_ignore_case("Abc", "aBC"))
        # another=None
        self.assertFalse(primitive.equals_ignore_case("abc", None))
        # 长度不同
        self.assertFalse(primitive.equals_ignore_case("abc", "ab"))
        # 内容不同，长度相同
        self.assertFalse(primitive.equals_ignore_case("abc", "abd"))
        # 空字符串
        self.assertTrue(primitive.equals_ignore_case("", ""))

    def test_is_blank(self):
        # None
        self.assertTrue(primitive.is_blank(None))
        # 空字符串
        self.assertTrue(primitive.is_blank(""))
        # 仅空白字符
        self.assertTrue(primitive.is_blank("   "))
        self.assertTrue(primitive.is_blank("\t\n"))
        # 非空白
        self.assertFalse(primitive.is_blank("a"))
        self.assertFalse(primitive.is_blank("  a  "))

    def test_has_text(self):
        # None
        self.assertFalse(primitive.has_text(None))
        # 空字符串
        self.assertFalse(primitive.has_text(""))
        # 仅空白字符
        self.assertFalse(primitive.has_text("   "))
        self.assertFalse(primitive.has_text("\t\n"))
        # 包含非空白字符
        self.assertTrue(primitive.has_text("a"))
        self.assertTrue(primitive.has_text("  a  "))
        self.assertTrue(primitive.has_text("a b"))

    def test_contains_whitespace(self):
        # 无空白
        self.assertFalse(primitive.contains_whitespace(""))
        self.assertFalse(primitive.contains_whitespace("abc"))
        # 包含空白
        self.assertTrue(primitive.contains_whitespace(" "))
        self.assertTrue(primitive.contains_whitespace("a b"))
        self.assertTrue(primitive.contains_whitespace("\t"))
        self.assertTrue(primitive.contains_whitespace("a\tb"))

    def test_trim_all_whitespace(self):
        # 正常
        self.assertEqual(primitive.trim_all_whitespace("a b c"), "abc")
        # 各种空白字符
        self.assertEqual(primitive.trim_all_whitespace("a\tb\nc"), "abc")
        # 无空白
        self.assertEqual(primitive.trim_all_whitespace("abc"), "abc")
        # 空字符串
        self.assertEqual(primitive.trim_all_whitespace(""), "")
        # 全空白
        self.assertEqual(primitive.trim_all_whitespace("   "), "")

    def test_startswith_ignore_case(self):
        # 正常匹配
        self.assertTrue(primitive.startswith_ignore_case("HelloWorld", "hello"))
        # value=None
        self.assertFalse(primitive.startswith_ignore_case(None, "hello"))
        # prefix=None
        self.assertFalse(primitive.startswith_ignore_case("HelloWorld", None))
        # 不匹配
        self.assertFalse(primitive.startswith_ignore_case("HelloWorld", "world"))
        # value长度小于prefix
        self.assertFalse(primitive.startswith_ignore_case("Hi", "hello"))
        # start参数
        self.assertTrue(primitive.startswith_ignore_case("HelloWorld", "world", start=5))
        self.assertFalse(primitive.startswith_ignore_case("HelloWorld", "hello", start=5))
        # end参数
        self.assertTrue(primitive.startswith_ignore_case("HelloWorld", "hello", end=5))
        self.assertFalse(primitive.startswith_ignore_case("HelloWorld", "world", end=5))
        # start和end同时指定
        self.assertTrue(primitive.startswith_ignore_case("HelloWorld", "lo", start=3, end=5))
        self.assertFalse(primitive.startswith_ignore_case("HelloWorld", "hello", start=3, end=5))

    def test_endswith_ignore_case(self):
        # 正常匹配
        self.assertTrue(primitive.endswith_ignore_case("HelloWorld", "world"))
        # value=None
        self.assertFalse(primitive.endswith_ignore_case(None, "world"))
        # suffix=None
        self.assertFalse(primitive.endswith_ignore_case("HelloWorld", None))
        # 不匹配
        self.assertFalse(primitive.endswith_ignore_case("HelloWorld", "hello"))
        # value长度小于suffix
        self.assertFalse(primitive.endswith_ignore_case("Hi", "world"))
        # start参数
        self.assertTrue(primitive.endswith_ignore_case("HelloWorld", "lo", start=3, end=5))
        # end参数
        self.assertTrue(primitive.endswith_ignore_case("HelloWorld", "world", end=10))
        self.assertFalse(primitive.endswith_ignore_case("HelloWorld", "world", end=5))
        # start和end同时指定
        self.assertTrue(primitive.endswith_ignore_case("HelloWorld", "loW", start=3, end=6))
        self.assertFalse(primitive.endswith_ignore_case("HelloWorld", "world", start=3, end=5))

    def test_substring_after(self):
        # 正常查找（first）
        self.assertEqual(primitive.substring_after("abc:def", ":"), "def")
        # last=True
        self.assertEqual(primitive.substring_after("abc:def:ghi", ":", last=True), "ghi")
        # separator不存在
        self.assertEqual(primitive.substring_after("abcdef", ":"), "abcdef")
        # separator为空字符串
        self.assertEqual(primitive.substring_after("abc", ""), "abc")
        # 多个分隔符，last=False
        self.assertEqual(primitive.substring_after("abc:def:ghi", ":"), "def:ghi")
        # value为空字符串
        self.assertEqual(primitive.substring_after("", ":"), "")

    def test_capitalize(self):
        # 正常
        self.assertEqual(primitive.capitalize("hello"), "Hello")
        # 首字母已大写
        self.assertEqual(primitive.capitalize("Hello"), "Hello")
        # 空字符串
        self.assertEqual(primitive.capitalize(""), "")
        # 仅空白
        self.assertEqual(primitive.capitalize("   "), "")
        # 单字符
        self.assertEqual(primitive.capitalize("h"), "H")
        # 首字母后还有其他大写
        self.assertEqual(primitive.capitalize("hELLO"), "HELLO")

    def test_uncapitalize(self):
        # 正常
        self.assertEqual(primitive.uncapitalize("Hello"), "hello")
        # 首字母已小写
        self.assertEqual(primitive.uncapitalize("hello"), "hello")
        # 空字符串
        self.assertEqual(primitive.uncapitalize(""), "")
        # 仅空白
        self.assertEqual(primitive.uncapitalize("   "), "")
        # 单字符
        self.assertEqual(primitive.uncapitalize("H"), "h")
        # 首字母后还有其他大写
        self.assertEqual(primitive.uncapitalize("HELLO"), "hELLO")

    def test_decapitalize(self):
        # 正常
        self.assertEqual(primitive.decapitalize("Hello"), "hello")
        # 首字母已小写
        self.assertEqual(primitive.decapitalize("hello"), "hello")
        # 单字符
        self.assertEqual(primitive.decapitalize("H"), "h")
        # 首字母后还有其他大写
        self.assertEqual(primitive.decapitalize("HELLO"), "HELLO")

    def test_camel_to_underline(self):
        # 正常驼峰
        self.assertEqual(primitive.camel_to_underline("CamelCase"), "camel_case")
        # 首字母小写
        self.assertEqual(primitive.camel_to_underline("camelCase"), "camel_case")
        # 连续大写
        self.assertEqual(primitive.camel_to_underline("HTTPRequest"), "h_t_t_p_request")
        # 空字符串
        self.assertEqual(primitive.camel_to_underline(""), "")
        # 仅空白
        self.assertEqual(primitive.camel_to_underline("   "), "")
        # 无大写
        self.assertEqual(primitive.camel_to_underline("lowercase"), "lowercase")
        # 单字符
        self.assertEqual(primitive.camel_to_underline("A"), "a")
        # 全大写
        self.assertEqual(primitive.camel_to_underline("ABC"), "a_b_c")

    def test_underline_to_camel(self):
        # 正常
        self.assertEqual(primitive.underline_to_camel("camel_case"), "CamelCase")
        # 多个下划线
        self.assertEqual(primitive.underline_to_camel("a__b"), "A_b")
        # 首字符下划线
        self.assertEqual(primitive.underline_to_camel("_abc"), "_abc")
        # 空字符串
        self.assertEqual(primitive.underline_to_camel(""), "")
        # 仅空白
        self.assertEqual(primitive.underline_to_camel("   "), "")
        # 无下划线
        self.assertEqual(primitive.underline_to_camel("lowercase"), "Lowercase")
        # 单字符
        self.assertEqual(primitive.underline_to_camel("a"), "A")
        # 连续下划线在中间
        self.assertEqual(primitive.underline_to_camel("a_b_c"), "ABC")

    def test_regex_extract(self):
        # pattern为空
        self.assertIsNone(primitive.regex_extract("abc", ""))
        # value为空
        self.assertIsNone(primitive.regex_extract("", "a"))
        # 正常匹配，默认group=1
        self.assertEqual(primitive.regex_extract("name=John", r"name=(\w+)"), "John")
        # group=0，返回完整匹配
        self.assertEqual(primitive.regex_extract("name=John", r"name=(\w+)", group=0), "name=John")
        # pattern无分组，默认group=1 -> None
        self.assertIsNone(primitive.regex_extract("abc123", r"\d+"))
        # pattern无分组，group=0 -> 返回完整匹配
        self.assertEqual(primitive.regex_extract("abc123", r"\d+", group=0), "123")
        # group超出范围
        self.assertIsNone(primitive.regex_extract("name=John", r"name=(\w+)", group=2))
        # 无匹配
        self.assertIsNone(primitive.regex_extract("abc", r"\d+"))
        # 多分组
        self.assertEqual(primitive.regex_extract("a=1,b=2", r"a=(\d+),b=(\d+)", group=2), "2")

    def test_regex_extract_all(self):
        # === value 参数类型异常（@validate_types 严格拦截） ===
        # value 为 None（不是 str）
        with self.assertRaises(TypeError):
            primitive.regex_extract_all(None, r"\d+")
        # value 为 int（不是 str）
        with self.assertRaises(TypeError):
            primitive.regex_extract_all(123, r"\d+")
        # value 为 list（不是 str）
        with self.assertRaises(TypeError):
            primitive.regex_extract_all(["a"], r"\d+")
        # pattern 为 None（不是 str 也不是 re.Pattern）
        with self.assertRaises(TypeError):
            primitive.regex_extract_all("abc", None)
        # pattern 为 int
        with self.assertRaises(TypeError):
            primitive.regex_extract_all("abc", 123)
        # pattern 为 list
        with self.assertRaises(TypeError):
            primitive.regex_extract_all("abc", ["a"])
        # value 为空字符串
        self.assertEqual(primitive.regex_extract_all("", r"\d+"), [])
        # value 为仅空格
        self.assertEqual(primitive.regex_extract_all("   ", r"\d+"), [])
        # value 为仅制表符和换行符
        self.assertEqual(primitive.regex_extract_all("\t\n", r"\d+"), [])
        # 无匹配
        self.assertEqual(primitive.regex_extract_all("abc", r"\d+"), [])
        # 多个匹配（无捕获分组，返回完整匹配列表）
        self.assertEqual(primitive.regex_extract_all("a1b2c3", r"\d+"), ["1", "2", "3"])
        # 多个匹配（有1个捕获分组，返回分组内容列表）
        self.assertEqual(primitive.regex_extract_all("a1b2a3", r"a(\d)"), ["1", "3"])
        # 多个匹配（有多个捕获分组，返回元组列表）
        self.assertEqual(primitive.regex_extract_all(
            "a12b34c56", r"(\d)(\d)"), [("1", "2"), ("3", "4"), ("5", "6")])
        # 有多个匹配
        self.assertEqual(primitive.regex_extract_all("a1b2c3", re.compile(r"\d+")), ["1", "2", "3"])
        # 无匹配
        self.assertEqual(primitive.regex_extract_all("abc", re.compile(r"\d+")), [])
        # 重叠匹配（re.findall 按非重叠方式匹配）
        self.assertEqual(primitive.regex_extract_all("aaaa", r"aa"), ["aa", "aa"])
        # value 包含特殊字符，pattern 匹配特殊字符
        self.assertEqual(primitive.regex_extract_all("a.b.c", r"\."), [".", "."])
        # 为无效正则表达式，re.findall 抛出 re.error ===
        with self.assertRaises(re.error):
            primitive.regex_extract_all("abc", r"[")

    def test_truncate(self):
        # 字符串长度小于threshold
        self.assertEqual(primitive.truncate("hello", 10), "hello")
        # 字符串长度大于threshold
        self.assertEqual(primitive.truncate("hello world", 5), "hello...")
        # 空字符串
        self.assertEqual(primitive.truncate("", 5), "")
        # 长度刚好等于threshold
        self.assertEqual(primitive.truncate("hello", 5), "hello")
        # 自定义threshold
        self.assertEqual(primitive.truncate("abcdef", 3), "abc...")
        # threshold=0
        self.assertEqual(primitive.truncate("hello", 0), "...")
        self.assertEqual(primitive.truncate("", 0), "")

    def test_default_int(self):
        self.assertEqual(primitive.default_int(None), 0)
        self.assertEqual(primitive.default_int(42), 42)
        self.assertEqual(primitive.default_int(3.14), 3)
        self.assertEqual(primitive.default_int("100"), 100)
        self.assertEqual(primitive.default_int("abc"), 0)
        self.assertEqual(primitive.default_int(Sample("")), 0)

    def test_default_float(self):
        self.assertEqual(primitive.default_float(None), 0.0)
        self.assertEqual(primitive.default_float(42), 42.0)
        self.assertEqual(primitive.default_float(3.14), 3.14)
        self.assertEqual(primitive.default_float("2.5"), 2.5)
        self.assertEqual(primitive.default_float("abc"), 0.0)

    def test_to_int(self):
        self.assertEqual(primitive.to_int(10), 10)
        self.assertEqual(primitive.to_int("10"), 10)
        self.assertEqual(primitive.to_int(10.9), 10)
        self.assertEqual(primitive.to_int("abc"), 0)
        self.assertEqual(primitive.to_int("abc", 999), 999)
        self.assertEqual(primitive.to_int(None), 0)
        self.assertEqual(primitive.to_int(None, 5), 5)

    def test_to_float(self):
        self.assertEqual(primitive.to_float(10), 10.0)
        self.assertEqual(primitive.to_float("10"), 10.0)
        self.assertEqual(primitive.to_float("3.14"), 3.14)
        self.assertEqual(primitive.to_float("abc"), 0.0)
        self.assertEqual(primitive.to_float("abc", 1.5), 1.5)
        self.assertEqual(primitive.to_float("abc", 2), 2.0)
        self.assertEqual(primitive.to_float(None), 0.0)

    def test_randrange_step(self):
        # step 为 0 时直接返回 start
        self.assertEqual(primitive.randrange_step(1.0, 10.0, 0, 2), 1.0)
        # 验证返回值在预期范围内
        for _ in range(100):
            result = primitive.randrange_step(0, 10, 2)
            self.assertIn(result, [0.0, 2.0, 4.0, 6.0, 8.0])
            self.assertIsInstance(result, float)
        # 验证保留小数位数
        for _ in range(100):
            result = primitive.randrange_step(0.0, 1.0, 0.1, 1)
            self.assertTrue(0.0 <= result < 1.0)
            self.assertEqual(len(str(result).split(".")[-1]), 1)
        # 边界：start 等于 stop
        self.assertEqual(primitive.randrange_step(5, 5, 1), 5.0)
        # 负数范围
        result = primitive.randrange_step(-10, 0, 2)
        self.assertIn(result, [-10.0, -8.0, -6.0, -4.0, -2.0])
        # start > stop, step > 0：count 为 0，直接返回 start
        self.assertEqual(primitive.randrange_step(10.0, 5.0, 2.0, 1), 10.0)
        self.assertEqual(primitive.randrange_step(100, 0, 5, 0), 100.0)
        # start > stop, step < 0：步长为负，区间反向，验证返回值在预期范围内
        for _ in range(100):
            result = primitive.randrange_step(10, 0, -2)
            self.assertIn(result, [10.0, 8.0, 6.0, 4.0, 2.0])
        # start > stop, step < 0 且带小数位
        for _ in range(100):
            result = primitive.randrange_step(5.0, 0.0, -1.0, 1)
            self.assertTrue(0.0 < result <= 5.0)
            self.assertEqual(round(result, 1), result)

    def test_round_standard(self):
        self.assertEqual(primitive.round_standard(2.5, 0), 3.0)
        self.assertEqual(primitive.round_standard(2.4, 0), 2.0)
        self.assertEqual(primitive.round_standard(3.14159, 2), 3.14)
        self.assertEqual(primitive.round_standard(3.14159, 3), 3.142)
        self.assertEqual(primitive.round_standard(2.675, 2), 2.68)
        self.assertEqual(primitive.round_standard(-2.5, 0), -3.0)
        self.assertEqual(primitive.round_standard(5, 0), 5.0)
        self.assertEqual(primitive.round_standard(5, 2), 5.0)

    def test_to_plain_string(self):
        self.assertEqual(primitive.to_plain_string(1.23, 2), "1.23")
        self.assertEqual(primitive.to_plain_string(1.0, 0), "1")
        self.assertEqual(primitive.to_plain_string(1000000.0, 0), "1000000")
        self.assertEqual(primitive.to_plain_string(0.00001, 5), "0.00001")
        self.assertEqual(primitive.to_plain_string(2.5, 0), "3")
        self.assertEqual(primitive.to_plain_string(2.675, 2), "2.68")
        self.assertEqual(primitive.to_plain_string(42, 2), "42.00")

    def test_to_boolean(self):
        # None
        self.assertFalse(primitive.to_boolean(None))
        # 布尔值
        self.assertTrue(primitive.to_boolean(True))
        self.assertFalse(primitive.to_boolean(False))
        # 字符串 - true 各种大小写
        self.assertTrue(primitive.to_boolean("true"))
        self.assertTrue(primitive.to_boolean("True"))
        self.assertTrue(primitive.to_boolean("TRUE"))
        self.assertTrue(primitive.to_boolean("TrUe"))
        # 字符串 - false 各种大小写
        self.assertFalse(primitive.to_boolean("false"))
        self.assertFalse(primitive.to_boolean("False"))
        self.assertFalse(primitive.to_boolean("FALSE"))
        # 字符串 - 可转为整数 1
        self.assertTrue(primitive.to_boolean("1"))
        self.assertFalse(primitive.to_boolean("0"))
        self.assertFalse(primitive.to_boolean("2"))
        self.assertFalse(primitive.to_boolean("-1"))
        # 字符串 - 其他
        self.assertFalse(primitive.to_boolean("yes"))
        self.assertFalse(primitive.to_boolean("no"))
        self.assertFalse(primitive.to_boolean(""))
        self.assertFalse(primitive.to_boolean("abc"))
        # 整数
        self.assertTrue(primitive.to_boolean(1))
        self.assertFalse(primitive.to_boolean(0))
        self.assertFalse(primitive.to_boolean(2))
        self.assertFalse(primitive.to_boolean(-1))
        # 浮点数
        self.assertTrue(primitive.to_boolean(1.0))
        self.assertFalse(primitive.to_boolean(0.0))
        self.assertFalse(primitive.to_boolean(1.5))
        # 其他类型
        self.assertFalse(primitive.to_boolean([]))
        self.assertFalse(primitive.to_boolean({}))
        self.assertFalse(primitive.to_boolean(object()))


# util/ident工具测试
class TestIdentity(unittest.TestCase):
    def test_next_uuid(self):
        # 默认 next_uuid 应返回标准 36 字符带横线 UUID
        u = identity.next_uuid()
        self.assertIsInstance(u, str)
        self.assertEqual(len(u), 36)
        self.assertIn('-', u)
        # simple=True 时应返回 32 字符无横线 UUID
        u = identity.next_uuid(simple=True)
        self.assertIsInstance(u, str)
        self.assertEqual(len(u), 32)
        self.assertNotIn('-', u)
        # 批量生成的 UUID 应唯一
        uuids = [identity.next_uuid() for _ in range(100)]
        self.assertEqual(len(set(uuids)), len(uuids))

    def test_next_func_id(self):
        # 普通函数应返回稳定的 id，多次调用结果一致
        self.assertIsInstance(id1 := identity.func_identity(print_event), int)
        self.assertEqual(id1, identity.func_identity(print_event))
        # bound method 应返回稳定标识，不受 getattr 新对象影响
        # 同一实例的同一方法，不同方式获取，id 应相同
        id1 = identity.func_identity((hooks := MyHooks()).on_start)
        self.assertEqual(id1, identity.func_identity(hooks.on_start))
        self.assertEqual(id1, identity.func_identity(getattr(hooks, "on_start")))
        # 不同实例的同名方法应返回不同标识
        a, b = MyHooks(), MyHooks()
        self.assertNotEqual(identity.func_identity(a.on_start), identity.func_identity(b.on_start))
        # 同一实例的不同方法应返回不同标识
        self.assertNotEqual(identity.func_identity(hooks.on_start), identity.func_identity(hooks.on_stop))
        # lambda 每次创建新对象，id 应不同
        a, b = lambda x: x, lambda x: x
        self.assertNotEqual(identity.func_identity(a), identity.func_identity(b))

# util/reflect工具测试
class TestReflect(unittest.TestCase):
    def test_get_func_path(self):
        """覆盖 get_func_path 全部参数分支与异常/兜底路径"""
        mod = _sample_func.__module__
        # func=None -> 返回 "unknown"
        self.assertEqual(reflect.get_func_path(None), "unknown")
        # 普通函数 -> module.func_name
        self.assertEqual(reflect.get_func_path(_sample_func), f"{mod}._sample_func")
        # lambda -> 包含模块名，以 "<lambda>" 结尾
        # 注：若 lambda 定义在方法内部，qualname 会包含 <locals> 前缀
        path = reflect.get_func_path(lambda x: x)
        self.assertTrue(path.endswith("<lambda>"), f"Expected suffix '<lambda>', got {path}")
        # 类方法（未绑定）-> module.Class.method
        self.assertEqual(reflect.get_func_path(Sample.reset), f"{mod}.Sample.reset")
        # 静态方法 -> module.Class.method
        self.assertEqual(reflect.get_func_path(Sample.static_method), f"{mod}.Sample.static_method")
        # 实例方法（绑定后）-> 只有 __name__，返回 module.method
        # 注意：若希望返回 module.Class.method，需在实现中通过 func.__func__.__qualname__ 提取
        self.assertEqual(reflect.get_func_path(Sample("").reset), f"{mod}.Sample.reset")
        # 类对象本身 -> module.Class（类对象有 __qualname__，走首分支）
        self.assertEqual(reflect.get_func_path(Sample), f"{mod}.Sample")
        # 可调用对象实例 -> module.Class.__call__
        self.assertEqual(reflect.get_func_path(CallableObj()), f"{mod}.CallableObj.__call__")
        # 不可调用对象 -> 最终兜底 <unresolvable:...>
        result = reflect.get_func_path(NotCallable())
        self.assertTrue(result.startswith("<unresolvable:"), f"Unexpected result: {result}")

    def test_method_kind(self):
        # @classmethod 描述符 -> (True, True)
        self.assertEqual(reflect.method_kind(Sample.invoke), (True, True))
        # @staticmethod 描述符 -> (False, True)
        self.assertEqual(reflect.method_kind(Sample.static_method), (False, True))
        # 模块级函数 -> (False, False)
        def module_func():
            pass
        self.assertEqual(reflect.method_kind(module_func), (False, False))
        # 实例方法（绑定后）-> (True, True)
        self.assertEqual(reflect.method_kind(Sample("").reset), (True, True))
        # 实例方法（未绑定，从类上取，此时为 function）-> (False, True)
        self.assertEqual(reflect.method_kind(Sample.reset), (False, True))
        # 局部函数 -> (False, False)
        def local_func():
            pass
        self.assertEqual(reflect.method_kind(local_func), (False, False))
        # 局部类中的方法 -> 剥掉 <locals> 后仍含 '.'，判定为定义在类中 -> (False, True)
        def outer():
            class LocalClass:
                def local_method(self):
                    pass
            return LocalClass.local_method
        self.assertEqual(reflect.method_kind(outer()), (False, True))

    def test_bind_arguments(self):
        def func(a: int, b: str = "default", c: float = 1.0):
            pass
        # 正常绑定，partial=False，全部参数传入
        args_dict, sig = reflect.bind_arguments(func, 1, b="test")
        self.assertEqual(args_dict, {"a": 1, "b": "test", "c": 1.0})
        self.assertIsInstance(sig, inspect.Signature)
        # 只传必填位置参数，有默认值的参数自动填充
        args_dict2, _ = reflect.bind_arguments(func, 10)
        self.assertEqual(args_dict2, {"a": 10, "b": "default", "c": 1.0})
        # partial=True，宽松绑定，未传参数用默认值占位
        args_dict3, _ = reflect.bind_arguments(func, 1, partial=True)
        self.assertEqual(args_dict3, {"a": 1, "b": "default", "c": 1.0})
        # partial=True，完全不传，必填参数占位置为 Parameter.empty
        args_dict4, _ = reflect.bind_arguments(func, partial=True)
        self.assertEqual(args_dict4, {"a": inspect.Parameter.empty, "b": "default", "c": 1.0})
        # eval_str=True：字符串注解被解析为真实类型对象
        def str_ann(x: "int") -> "str":
            pass
        args_dict5, sig5 = reflect.bind_arguments(str_ann, 1, eval_str=True)
        self.assertEqual(args_dict5, {"x": 1})
        self.assertEqual(sig5.return_annotation, str)
        # eval_str=False：字符串注解保持原字符串，不解析
        args_dict6, sig6 = reflect.bind_arguments(str_ann, 1, eval_str=False)
        self.assertEqual(sig6.return_annotation, "str")
        # 异常：partial=False 时缺少必填参数 -> TypeError
        with self.assertRaises(TypeError):
            reflect.bind_arguments(func)
        # 异常：传入签名中不存在的关键字参数 -> TypeError
        with self.assertRaises(TypeError):
            reflect.bind_arguments(func, 1, d="extra")

    def test_iter_arguments(self):
        # 返回的是生成器/迭代器
        with self.subTest("返回的是生成器/迭代器"):
            self.assertIsInstance(reflect.iter_arguments(_sample_func, 1, 2), Iterator)
        # 默认开关：只产出有注解的普通参数，*args/**kwargs/无注解参数均跳过
        with self.subTest("默认开关：只产出有注解的普通参数"):
            bound = {"a": 1, "b": 2, "args": (3.0,), "c": "hello", "kwargs": {"d": True}}
            self.assertEqual([("a", int, 1, bound), ("c", str, "hello", bound)], list(
                reflect.iter_arguments(_sample_func, 1, 2, 3.0, c="hello", d=True)))
        # 未显式传入的参数以默认值产出
        with self.subTest("未显式传入的参数以默认值产出"):
            bound = {"a": 1, "b": 2, "args": (), "c": "default", "kwargs": {}}
            self.assertEqual([("a", int, 1, bound), ("c", str, "default", bound)], list(
                reflect.iter_arguments(_sample_func, 1, 2)))
        # include_variadic=True：*args 整体产出为 tuple，**kwargs 整体产出为 dict
        with self.subTest("include_variadic=True：变长参数整体产出"):
            bound = {"a": 1, "b": 2, "args": (2.5, 3.5), "c": "default", "kwargs": {"d": True}}
            result = list(reflect.iter_arguments(_sample_func, 1, 2, 2.5, 3.5, d=True, include_variadic=True))
            self.assertEqual([("a", int, 1, bound), ("args", float, (2.5, 3.5), bound),
                              ("c", str, "default", bound), ("kwargs", bool, {"d": True}, bound)], result)
        # include_variadic=True：变长参数为空时仍整体产出（空 tuple / 空 dict）
        with self.subTest("include_variadic=True：变长参数为空时仍整体产出"):
            bound = {"a": 1, "b": 2, "args": (), "c": "default", "kwargs": {}}
            result = list(reflect.iter_arguments(_sample_func, 1, 2, include_variadic=True))
            self.assertIn(("args", float, (), bound), result)
            self.assertIn(("kwargs", bool, {}, bound), result)
        # include_unannotated=True：无注解参数产出，注解位为 inspect.Parameter.empty
        with self.subTest("include_unannotated=True：无注解参数产出"):
            bound = {"a": 1, "b": 2, "args": (), "c": "default", "kwargs": {}}
            result = list(reflect.iter_arguments(_sample_func, 1, 2, include_unannotated=True))
            self.assertEqual([("a", int, 1, bound), ("b", inspect.Parameter.empty, 2, bound),
                              ("c", str, "default", bound)], result)
            self.assertIs(inspect.Parameter.empty, result[1][1])
        # 第 4 个元素为完整的已绑定参数集（含被跳过的参数），且各产出项共享同一对象
        with self.subTest("第4个元素为完整已绑定参数集"):
            result = list(reflect.iter_arguments(_sample_func, 1, 2))
            bound = result[0][3]
            self.assertIsInstance(bound, dict)
            # 键的顺序与签名参数声明顺序一致
            self.assertEqual(["a", "b", "args", "c", "kwargs"], list(bound))
            self.assertEqual({"a": 1, "b": 2, "args": (), "c": "default", "kwargs": {}}, bound)
            self.assertTrue(all(item[3] is bound for item in result))
        # self/cls 始终跳过（通过未绑定方法触发跳过逻辑）
        with self.subTest("self/cls 始终跳过"):
            instance = Sample("")
            self.assertEqual([("count", int, 1, {"self": instance, "count": 1})],
                             list(reflect.iter_arguments(Sample.reset, instance, 1)))
            self.assertEqual([("count", int, 1, {"cls": Sample, "count": 1})],
                             list(reflect.iter_arguments(Sample.invoke.__func__, Sample, 1)))
        # 开关与目标函数实参隔离，开关不会泄漏进 **kwargs
        with self.subTest("开关不泄漏进目标函数的 **kwargs"):
            result = list(reflect.iter_arguments(_sample_func, 1, 2, d=True, include_variadic=True))
            self.assertEqual({"d": True}, result[0][3]["kwargs"])
        # target_func 仅限位置：目标函数有同名参数也能正常传递
        with self.subTest("目标函数存在 target_func 同名参数时正常传递"):
            def clash(target_func: str):
                ...
            bound = {"target_func": "hello"}
            self.assertEqual([("target_func", str, "hello", bound)], list(
                reflect.iter_arguments(clash, target_func="hello")))
        # eval_str 开关：关闭时注解为字符串，开启时解析为真实类型
        with self.subTest("eval_str 开关控制字符串注解解析"):
            def str_ann(x: "int"):
                ...
            self.assertEqual("int", next(reflect.iter_arguments(str_ann, 1, eval_str=False))[1])
            self.assertIs(int, next(reflect.iter_arguments(str_ann, 1, eval_str=True))[1])
        # 实参与签名不匹配抛 TypeError（生成器需迭代后才触发）
        with self.subTest("实参与签名不匹配抛 TypeError"):
            with self.assertRaises(TypeError):
                list(reflect.iter_arguments(_sample_func))  # 缺必填参数 a、b
        # eval_str=True 且注解中的名字无法解析时抛 NameError
        with self.subTest("eval_str=True 名字无法解析抛 NameError"):
            def bad_ann(x: "UndefinedName"):
                ...
            with self.assertRaises(NameError):
                list(reflect.iter_arguments(bad_ann, 1, eval_str=True))

    def test_get_parameters(self):
        with self.subTest("函数_混合签名"):
            params = reflect.get_parameters(_sample_func)
            self.assertEqual(list(params.keys()), ["a", "b", "args", "c", "kwargs"])
            self.assertEqual(params["a"].annotation, int)
            self.assertEqual(params["b"].annotation, inspect.Parameter.empty)
            self.assertEqual(params["args"].annotation, float)
            self.assertEqual(params["args"].kind, inspect.Parameter.VAR_POSITIONAL)
            self.assertEqual(params["c"].annotation, str)
            self.assertEqual(params["c"].default, "default")
            self.assertEqual(params["c"].kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertEqual(params["kwargs"].annotation, bool)
            self.assertEqual(params["kwargs"].kind, inspect.Parameter.VAR_KEYWORD)

        with self.subTest("函数_装饰器函数"):
            params = reflect.get_parameters(db_service)
            self.assertEqual(list(params.keys()), [])

        with self.subTest("函数_事件监听函数"):
            from piz_core.infra import BaseEvent

            params = reflect.get_parameters(print_event)
            self.assertEqual(list(params.keys()), ["event"])
            self.assertEqual(params["event"].annotation, BaseEvent)

        with self.subTest("dataclass_基本"):
            params = reflect.get_parameters(SimpleDC)
            self.assertEqual(list(params.keys()), ["name", "age"])

        with self.subTest("dataclass_带默认值"):
            params = reflect.get_parameters(WithDefault)
            self.assertEqual(list(params.keys()), ["a", "b"])
            self.assertEqual(params["b"].default, "default")

        with self.subTest("dataclass_空"):
            params = reflect.get_parameters(EmptyDC)
            self.assertEqual(list(params.keys()), [])

        with self.subTest("dataclass_InitVar"):
            params = reflect.get_parameters(WithInitVar)
            self.assertEqual(list(params.keys()), ["value", "temp"])
            self.assertEqual(params["temp"].default, "ignored")

        with self.subTest("dataclass_字符串注解字段"):
            # User.address 字段是 "Address | None" 字符串注解
            # inspect.signature(User) 返回 __init__ 签名，参数名和默认值可验证
            params = reflect.get_parameters(User)
            self.assertEqual(list(params.keys()), ["name", "age", "address"])
            self.assertEqual(params["address"].default, None)

        with self.subTest("普通类_基本"):
            params = reflect.get_parameters(Sample)
            self.assertEqual(list(params.keys()), ["name"])
            self.assertEqual(params["name"].annotation, str)
            self.assertEqual(params["name"].default, inspect.Parameter.empty)

        with self.subTest("普通类_kwargs"):
            params = reflect.get_parameters(KwargsClass)
            self.assertEqual(list(params.keys()), ["kwargs"])
            self.assertEqual(params["kwargs"].kind, inspect.Parameter.VAR_KEYWORD)

        with self.subTest("普通类_必填参数"):
            params = reflect.get_parameters(NeedRequired)
            self.assertEqual(list(params.keys()), ["required"])
            self.assertEqual(params["required"].annotation, str)
            self.assertEqual(params["required"].default, inspect.Parameter.empty)

        with self.subTest("实例方法"):
            params = reflect.get_parameters(Sample.append)
            self.assertEqual(list(params.keys()), ["self", "obj", "valid"])
            self.assertEqual(params["obj"].annotation, object)
            self.assertEqual(params["valid"].annotation, type)

        with self.subTest("classmethod"):
            # classmethod 对象需取 __func__ 才能看到原始签名（含 cls）
            params = reflect.get_parameters(Sample.invoke.__func__)
            self.assertEqual(list(params.keys()), ["cls", "count"])
            self.assertEqual(params["count"].annotation, int)

        with self.subTest("staticmethod"):
            params = reflect.get_parameters(Sample.static_method)
            self.assertEqual(list(params.keys()), [])

        with self.subTest("异步实例方法"):
            params = reflect.get_parameters(MyHooks.on_start)
            self.assertEqual(list(params.keys()), ["self", "ctx"])

        with self.subTest("可调用对象"):
            params = reflect.get_parameters(CallableObj())
            self.assertEqual(list(params.keys()), [])

        with self.subTest("返回类型为只读映射"):
            params = reflect.get_parameters(_sample_func)
            self.assertIsInstance(params, types.MappingProxyType)
            with self.assertRaises(TypeError):
                params["extra"] = inspect.Parameter("extra", inspect.Parameter.POSITIONAL_OR_KEYWORD)

        with self.subTest("字符串注解_eval_str_true"):
            params = reflect.get_parameters(_str_annotated_func, eval_str=True)
            self.assertEqual(params["a"].annotation, int)
            self.assertEqual(params["b"].annotation, str)

        with self.subTest("字符串注解_eval_str_false"):
            params = reflect.get_parameters(_str_annotated_func, eval_str=False)
            self.assertEqual(params["a"].annotation, "int")
            self.assertEqual(params["b"].annotation, "str")

    def test_has_kwargs_param(self):
        with self.subTest("无参数"):
            self.assertFalse(reflect.has_kwargs_param(reflect.get_parameters(EmptyDC).values()))
            self.assertFalse(reflect.has_kwargs_param(reflect.get_parameters(Sample.static_method).values()))

        with self.subTest("仅位置参数"):
            self.assertFalse(reflect.has_kwargs_param(reflect.get_parameters(Sample).values()))
            self.assertFalse(reflect.has_kwargs_param(reflect.get_parameters(NeedRequired).values()))
            self.assertFalse(reflect.has_kwargs_param(reflect.get_parameters(Item).values()))

        with self.subTest("仅_args"):
            self.assertFalse(reflect.has_kwargs_param(reflect.get_parameters(_with_args_only).values()))

        with self.subTest("有_kwargs"):
            self.assertTrue(reflect.has_kwargs_param(reflect.get_parameters(KwargsClass).values()))
            self.assertTrue(reflect.has_kwargs_param(reflect.get_parameters(_sample_func).values()))
            self.assertTrue(reflect.has_kwargs_param(reflect.get_parameters(BadKwargsInit).values()))

        with self.subTest("同时有_args和_kwargs"):
            self.assertTrue(reflect.has_kwargs_param(reflect.get_parameters(_sample_func).values()))

        with self.subTest("空列表"):
            self.assertFalse(reflect.has_kwargs_param([]))

    def test_has_args_param(self):
        with self.subTest("无参数"):
            self.assertFalse(reflect.has_args_param(reflect.get_parameters(EmptyDC).values()))
            self.assertFalse(reflect.has_args_param(reflect.get_parameters(Sample.static_method).values()))

        with self.subTest("仅位置参数"):
            self.assertFalse(reflect.has_args_param(reflect.get_parameters(Sample).values()))
            self.assertFalse(reflect.has_args_param(reflect.get_parameters(NeedRequired).values()))

        with self.subTest("仅_args"):
            self.assertTrue(reflect.has_args_param(reflect.get_parameters(_with_args_only).values()))

        with self.subTest("有_kwargs无_args"):
            self.assertFalse(reflect.has_args_param(reflect.get_parameters(KwargsClass).values()))
            self.assertFalse(reflect.has_args_param(reflect.get_parameters(BadKwargsInit).values()))

        with self.subTest("同时有_args和_kwargs"):
            self.assertTrue(reflect.has_args_param(reflect.get_parameters(_sample_func).values()))

        with self.subTest("空列表"):
            self.assertFalse(reflect.has_args_param([]))

    def test_get_return_annotation(self):
        def func1() -> int:
            pass
        def func2() -> str:
            pass
        def func3():
            pass
        def func4() -> "int":
            pass
        def func5() -> None:
            pass
        # 正常获取返回注解（内置类型）
        self.assertEqual(reflect.get_return_annotation(func1), int)
        self.assertEqual(reflect.get_return_annotation(func2), str)
        # 无返回注解 -> inspect.Signature.empty
        self.assertEqual(reflect.get_return_annotation(func3), inspect.Signature.empty)
        # 字符串注解，eval_str=True -> 解析为真实类型
        self.assertEqual(reflect.get_return_annotation(func4, eval_str=True), int)
        # 字符串注解，eval_str=False -> 保持字符串不解析
        self.assertEqual(reflect.get_return_annotation(func4, eval_str=False), "int")
        # -> None 的返回注解：inspect.signature 直接返回 None（不是 type(None)）
        # 注：这与 is_expected_annotation 内部把 None 转成 type(None) 的处理不同。
        self.assertEqual(reflect.get_return_annotation(func5), None)
        # 异常：eval_str=True 且注解中的名字无法解析 -> NameError
        def bad_func() -> "UndefinedName":
            pass
        with self.assertRaises(NameError):
            reflect.get_return_annotation(bad_func, eval_str=True)

    def test_get_doc_description(self):
        # 测试 get_doc_description：提取函数描述，不含参数字段
        # (docstring, expected)
        cases = [

            (None, ""),
            ("", ""),
            ("    ", ""),
            ("获取用户信息", "获取用户信息"),
            ("获取用户信息\n\n:param user_id: 用户ID\n:return: 用户信息", "获取用户信息"),
            ("获取用户信息。\n支持多种查询方式。\n\n:param user_id: 用户ID", "获取用户信息。\n支持多种查询方式。"),
            ("获取用户信息\n:param user_id: 用户ID\n:raises ValueError: 参数错误", "获取用户信息"),
            (":param user_id: 用户ID\n:return: 用户信息", ""),
            ("  获取用户信息  \n\n:param user_id: 用户ID", "获取用户信息"),
        ]
        for doc, expected in cases:
            with self.subTest(doc=doc):
                result = reflect.get_func_doc(make_func(doc))
                self.assertEqual(result, expected)

    def test_get_field_doc(self):
        # 测试 get_field_doc：提取指定参数 / 异常 / 返回值的注释
        # (docstring, name, kind, expected)
        cases = [
            # 无文档或空文档
            (None, "user_id", "param", ""),
            ("", "user_id", "param", ""),
            # 查找不存在的参数
            ("获取用户信息\n:param name: 用户名", "user_id", "param", ""),
            # 参数存在，单行描述
            ("获取用户信息\n:param user_id: 用户唯一标识", "user_id", "param", "用户唯一标识"),
            # 参数存在，多行续写（遇下一个字段停止）
            ("获取用户信息\n:param user_id: 用户唯一标识\n可以是数字或字符串\n:param name: 用户名",
             "user_id", "param", "用户唯一标识 可以是数字或字符串"),
            # 参数多行续写含空行（空行应被忽略）
            ("获取用户信息\n:param user_id: 用户唯一标识\n\n可以是数字或字符串\n:param name: 用户名",
             "user_id", "param", "用户唯一标识 可以是数字或字符串"),
            # :return: 单行
            ("获取用户信息\n:param user_id: 用户ID\n:return: 用户信息对象", "", "return", "用户信息对象"),
            # :returns: 应被统一识别为 return
            ("获取用户信息\n:param user_id: 用户ID\n:returns: 用户信息对象", "", "return", "用户信息对象"),
            # return 多行续写
            ("获取用户信息\n:return: 用户信息对象\n包含姓名和年龄\n字典格式", "", "return", "用户信息对象 包含姓名和年龄 字典格式"),
            # :raises: 单行
            ("获取用户信息\n:param user_id: 用户ID\n:raises ValueError: 用户ID为空\n:raises TypeError: 类型错误",
             "ValueError", "raises", "用户ID为空"),
            # :raises: 多行续写
            ("获取用户信息\n:raises ValueError: 用户ID为空\n或格式不正确\n:return: 用户信息",
             "ValueError", "raises", "用户ID为空 或格式不正确"),
            # kind 不匹配（param 当 return 查）
            ("获取用户信息\n:param user_id: 用户ID", "user_id", "return", ""),
            # 多个同 kind 字段，取第一个匹配的 name
            ("获取用户信息\n:param user_id: 用户ID\n:param name: 用户名", "user_id", "param", "用户ID"),
        ]
        for doc, name, kind, expected in cases:
            with self.subTest(doc=doc, name=name, kind=kind):
                func = make_func(doc)
                result = reflect.get_field_doc(func, name, kind)
                self.assertEqual(result, expected)


# util/ser工具测试
class TestSerialization(unittest.TestCase):
    def setUp(self):
        # 创建临时测试目录
        path = os.path.dirname(__file__)
        self.temp_dir = os.path.join(str(path), "test_dir")

        if not os.path.exists(self.temp_dir):
            os.mkdir(self.temp_dir)

    def tearDown(self):
        # 清理临时测试目录
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_object_and_dump_object(self):
        # 测试 dump_object 的 data 参数和 kwargs
        obj = {"key": "value", "num": 42}
        pickle_file = os.path.join(self.temp_dir, "test.pkl")
        serialization.dump_object(pickle_file, obj, protocol=pickle.HIGHEST_PROTOCOL)
        # 测试 read_object 的 value 参数和 kwargs
        result = serialization.read_object(pickle_file, encoding="ASCII")
        self.assertEqual(result, obj)
        # 测试复杂对象
        complex_obj = [1, 2, {"nested": True}]
        serialization.dump_object(pickle_file, complex_obj)
        self.assertEqual(serialization.read_object(pickle_file), complex_obj)

    def test_dataclass_values(self):
        # 简单 dataclass 按字段顺序平铺
        simple = SimpleDC(name="Alice", age=30)
        self.assertTupleEqual(serialization.dataclass_values(simple), ("Alice", 30))
        # 含默认值的字段
        with_default = WithDefault(a=1)
        self.assertTupleEqual(serialization.dataclass_values(with_default), (1, "default"))
        # InitVar 字段应被过滤
        with_init = WithInitVar(value="hello", temp="temp_val")
        self.assertTupleEqual(serialization.dataclass_values(with_init), ("hello",))
        # 空 dataclass 返回空 tuple
        self.assertTupleEqual(serialization.dataclass_values(EmptyDC()), ())
        # 非 dataclass 抛 TypeError，不含 error_hint
        with self.assertRaises(TypeError) as ctx:
            serialization.dataclass_values("not a dataclass")
        msg = str(ctx.exception)
        self.assertIn("dataclass", msg)  # expected
        self.assertIn("str", msg)  # got (由 get_class_path 解析)
        # 非 dataclass 抛 TypeError，含 error_hint
        with self.assertRaises(TypeError) as ctx2:
            serialization.dataclass_values(12345, error_hint=" [hint: must be dataclass instance]")
        msg2 = str(ctx2.exception)
        self.assertIn("dataclass", msg2)
        self.assertIn("must be dataclass instance", msg2)

# util/system工具测试
class TestSystem(unittest.TestCase):
    def test_get_caller_info(self):
        # 测试 get_caller_info 返回调用者的栈帧摘要
        info = system.get_caller_info()
        self.assertIsInstance(info, traceback.FrameSummary)
        self.assertIsNotNone(info.filename)
        self.assertIsNotNone(info.lineno)
        self.assertIsNotNone(info.name)
        self.assertIsNotNone(info.line)
        # 验证返回的是调用者（本测试方法）的信息
        self.assertEqual(info.name, "test_get_caller_info")

    def test_get_caller_frame(self):
        # 测试 get_caller_frame 返回调用者的活跃帧对象
        frame = system.get_caller_frame()
        self.assertIsInstance(frame, types.FrameType)
        # 验证可以访问局部变量
        self.assertIn("self", frame.f_locals)
        # 验证函数名是调用者
        self.assertEqual(frame.f_code.co_name, "test_get_caller_frame")
        # 模拟 inspect.currentframe() 返回 None
        with patch("piz_core.util.system.inspect.currentframe", return_value=None):
            result = system.get_caller_frame()
            self.assertIsNone(result)


