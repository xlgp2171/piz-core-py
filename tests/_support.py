import json
import logging
from dataclasses import dataclass, InitVar
from typing import Annotated, Any

from piz_core import util
from piz_core.deco import inject, provide, component, validate_types, insert, select, update, delete
from piz_core.deco.event import event_listener
from piz_core.infra import setup_logging, LOG_VERBOSE_FORMAT
from piz_core.infra.db import BaseMapper, SqlDatabase
from piz_core.infra.event import BaseEvent, event_bus
from piz_core.infra.ioc import Injected, Prop, environment


setup_logging("debug", logging.DEBUG, log_format=LOG_VERBOSE_FORMAT)
environment.set_default_path("sample/config_main.toml")


@dataclass
class User:
    name: str
    age: int
    address: "Address | None" = None

@dataclass
class Address:
    city: str
    street: str

@dataclass
class StatusEvent(BaseEvent):
    name: str

    def __str__(self):
        return super().__str__() + f",\tname: {self.name}"

@dataclass
class UpdateEvent(BaseEvent):
    key: str
    value: Any

    def __str__(self):
        return super().__str__() + f",\tkv: {self.key}/{self.value}"

@dataclass(frozen=True, slots=True)
class SklModel:
    mid: int = None
    m_type: str = None
    score: float = None
    status: int = None
    create_time: str = None

@dataclass(frozen=True, slots=True)
class ModelTypes:
    value: list[str]

@dataclass(frozen=True)
class SklModels:
    score: float
    types: ModelTypes

@dataclass
class DataClassObj:
    name: str

@dataclass
class SimpleDC:
    name: str
    age: int

@dataclass
class WithInitVar:
    value: str
    temp: InitVar[str] = "ignored"

    def __post_init__(self, temp: str):
        pass

@dataclass
class EmptyDC:
    pass

@dataclass
class WithDefault:
    a: int
    b: str = "default"

class PlainObj:
    """非 dataclass 的普通对象"""
    def __init__(self):
        self.x = 100

class Sample:
    def __init__(self, name: str):
        self._name = name
        self._count = 0
        self._sample_data: list[tuple[object, type]] = []

    def append(self, obj: object, valid: type) -> bool:
        _match = False

        if _match := isinstance(obj, valid):
            self._count += 1
        self._sample_data.append((obj, valid))
        return _match

    def clear(self):
        self._sample_data.clear()
        self._count = 0

    def reset(self, count: int):
        self._count = count

    @classmethod
    def invoke(cls, count: int):
        pass

    @staticmethod
    def static_method():
        """静态方法"""
        pass

    @property
    def count(self):
        return self._count

    @property
    def name(self):
        return self._name

    def is_empty(self) -> bool:
        return len(self._sample_data) <= 0

    def __str__(self):
        return f"{self._count}"

@component
class DbMapper:
    def __init__(self, path: str = "sample/_data.json"):
        self._path = path

    def load(self) -> dict:
        if util.path_exists(self._path):
            with util.get_resource_as_stream(self._path, mode="r") as f:
                return json.loads(f.read() or "{}")
        else:
            return {}

    @validate_types
    def save(self, data: dict):
        if data:
            with util.get_resource_as_stream(self._path, mode="w") as f:
                f.write(json.dumps({**self.load(), **data} or {}))
            event_bus.publish(StatusEvent("SAVE_DATA"))

    @validate_types
    def save_item(self, k: str, v: str):
        self.save({k: v})

    @validate_types
    def load_item(self, k: str) -> str:
        return str(data[k]) if (data := self.load()) else util.EMPTY

@component(name="data_builder")
class DataBuilder:
    _default_name: str = Prop("dev.datasource.username")
    _security_key: str = Prop("piz.security.key", default="1236", process_func=lambda x: f"token {x}")

    def __init__(self):
        self.version = 0
        self._alias_name = ""

    def refresh_data(self) -> dict:
        self.version += 1
        return {"$version": self.version, "$timestamp": util.current_time_millis()}

    @property
    def alias_name(self):
        return self._alias_name if self._alias_name else self._default_name

    @property
    def security_key(self):
        return self._security_key

    @event_listener(UpdateEvent, StatusEvent)
    def _update_default_name(self, event: UpdateEvent | StatusEvent):
        if isinstance(event, UpdateEvent) and event.key == "name":
            self._alias_name = str(event.value)

class DbService:
    _mapper = Injected(instance_type=DbMapper)
    _builder: DataBuilder

    @inject
    def set(self, builder: Annotated[DataBuilder, Prop("piz.extra.impl")]):
        self._builder = builder

    def load_name(self) -> str:
        return self._mapper.load_item("$name")

    @validate_types
    def save_name(self, name: str):
        data = self._builder.refresh_data()
        self._mapper.save({**data, "$name": name})
        event_bus.publish(UpdateEvent(key="name", value=name))

    def save_default_name(self):
        self.save_name(self._builder.alias_name)

    def get_version(self) -> int:
        return util.to_int(self._mapper.load_item("$version"))

    def get_security_key(self) -> str:
        return self._builder.security_key

@component
class ModelMapper(BaseMapper[SqlDatabase], impl_name="sqlite_db"):
    @insert("INSERT INTO skl_model(id,model_type,score,status,create_time) "
            "VALUES(#{mid}, #{m_type}, #{score}, #{status}, #{create_time})")
    @validate_types
    def insert_model1(self, *, mid: int, m_type: str, score: float, status: int, create_time: str) -> int: ...

    @insert("INSERT INTO skl_model(id,model_type,score,status,create_time) "
            "VALUES(#{mid}, #{m_type}, #{score}, #{status}, #{create_time})")
    @validate_types
    def insert_model2(self, model: SklModel) -> int: ...

    @insert("INSERT INTO skl_model(id,model_type,score,status,create_time) "
            "VALUES(#{model.mid}, #{model.m_type}, #{model.score}, #{model.status}, #{model.create_time})")
    @validate_types
    def insert_model3(self, model: dict) -> int: ...

    @insert("INSERT INTO skl_model(id,model_type,score,status,create_time) VALUES(#{model})")
    @validate_types
    def insert_model4(self, model: list[Any]) -> int: ...

    @insert("INSERT INTO skl_model(id,model_type,score,status,create_time) "
            "VALUES(#{mid}, #{m_type}, #{score}, #{status}, #{create_time})")
    @validate_types
    def insert_model5(self, models: list[SklModel]) -> int: ...

    @insert("INSERT INTO skl_model(id,model_type,score,status,create_time) "
            "VALUES(#{mid}, #{m_type}, #{score}, #{status}, #{create_time})")
    @validate_types
    def insert_model6(self, models: list[dict[str, Any]]) -> int: ...

    @insert("INSERT INTO skl_model(id,model_type,score,status,create_time) VALUES(#{models})")
    @validate_types
    def insert_model7(self, models: list[tuple]) -> int: ...

    @select("SELECT COUNT(*) FROM skl_model", res_type=int)
    def select_model1(self) -> int: ...

    @select("SELECT id as mid,model_type as m_type,score,status,create_time FROM skl_model "
            "WHERE id=#{mid}", res_type=SklModel)
    def select_model2(self, mid: int) -> SklModel: ...

    @select("SELECT id as mid,model_type as m_type,score,status,create_time FROM skl_model "
            "WHERE model_type = #{model.m_type} AND score < #{model.score}", many=False, res_type=SklModel)
    def select_model3(self, model: SklModel) -> SklModel: ...

    @select("SELECT * FROM skl_model WHERE model_type IN (#{m_types}) AND score > #{score}")
    def select_model4(self, m_types: list[str], score: float) -> list[dict]: ...

    @select("SELECT id as mid, model_type as m_type, score FROM skl_model "
            "WHERE id IN (#{ids}) AND model_type IN (#{m_types})", res_type=SklModel)
    def select_model5(self, ids: list[int], m_types: list[str]) -> list[SklModel]: ...

    @select("SELECT * FROM skl_model WHERE model_type IN (#{types}) AND score > #{model.score}")
    def select_model6(self, model: SklModel, types: list[str]) -> list: ...

    @select("SELECT * FROM skl_model WHERE model_type = #{event.name} AND create_time >= #{model.create_time}")
    def select_model7(self, model: SklModel, event: StatusEvent) -> list: ...

    @select("SELECT id as mid,model_type as m_type,score,status,create_time FROM skl_model "
            "WHERE model_type IN (#{models.types.value}) AND create_time > #{create_time}", res_type=SklModel)
    def select_model8(self, create_time: str, models: SklModels) -> list[SklModel]: ...

    @update("UPDATE skl_model SET status = #{status} WHERE score > #{model.score} AND model_type = #{model.m_type}")
    def update_model1(self, status: int, model: SklModel) -> int: ...

    @update("UPDATE skl_model SET status = #{status} WHERE id = #{mid}")
    def update_model2(self, status: int, mid: int) -> int: ...

    @delete("DELETE FROM skl_model WHERE score < #{model.score} AND status IN (#{model.status})")
    def delete_model1(self, model: dict) -> int: ...

class Foo:
    def __init__(self):
        self.x = 1

class Item:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class MyDict(dict):
    pass

class KwargsClass:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class FilteredClass:
    def __init__(self, name, age):
        self.name = name
        self.age = age

class NoInitMatch:
    def __init__(self, required_arg):
        self.required_arg = required_arg

class ReadOnlyProp:
    _x = 0

    @property
    def x(self):
        return self._x

class BadKwargsInit:
    def __init__(self, **kwargs):
        if kwargs.get("trigger") == "bad":
            raise ValueError("bad kwargs")
        self.__dict__.update(kwargs)

class NeedRequired:
    def __init__(self, required: str):
        self.required = required

class BadFilteredInit:
    def __init__(self, name: str):
        if name == "bad":
            raise ValueError("bad name")
        self.name = name

class NoMatchParams:
    def __init__(self, a: int, b: str):
        self.a = a
        self.b = b

class Minimal:
    pass

class CallableObj:
    def __call__(self):
        pass

class SlotClass:
    __slots__ = ("x",)

    def __init__(self):
        self.x = 1

@provide
def db_service() -> DbService:
    return DbService()

@event_listener(BaseEvent)
def print_event(event: BaseEvent):
    print("MONITOR: ", event)

def _sample_func(a: int, b, *args: float, c: str = "default", **kwargs: bool):
    """混合签名：有注解 / 无注解 / 变长 / 带默认值的关键字参数"""
    pass


DICT_DATA_A = {
    "level1": {
        "level2": {
            "level3": {
                "key": "val"
            },
            "key": "value"
        },
        "num": 42
    }
}

DICT_DATA_B = {
    "dict_key": {"inner": "value"},
    "list_key": [1, 2, 3],
    "str_key": "hello"
}