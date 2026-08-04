# piz-core-py

## Overview
快速架构方案，技术验证使用，实现了基本功能

- 运行在python3.12环境


## Features
- 轻量级IOC框架，包括装饰器 `@inject` `@component` `@provide` `@event_listener` 和描述符 `Injected` `Prop`
- 轻量级数据库框架，包括装饰器 `@select` `@insert` `@update` `@delete` 和基类 `BaseMapper`
- Sqlite基础应用实现
- 统一的日志处理和辅助工具


## Installation
1. `python -m build`
2. `python install`


## Quick Start
配置文件 *config.toml*
```toml
[user]
def-enabled = 1

[dev.datasource]
path = "demo.db"
ddl = """
CREATE TABLE IF NOT EXISTS user (
    uid bigint PRIMARY KEY,
    username varchar(32) DEFAULT NULL,
    password varchar(64) DEFAULT NULL,
    description varchar(128) DEFAULT NULL,
    status tinyint(1) DEFAULT NULL,
    create_time datetime DEFAULT NULL
);"""
```
示例代码 *example.py* ：
```python
import logging
from dataclasses import dataclass, field
from typing import cast

from piz_core.deco import select, component, insert, provide, event_listener, inject
from piz_core.infra import id_generator, setup_logging
from piz_core.infra.db import BaseMapper, SqlDatabase
from piz_core.infra.event import BaseEvent, event_bus
from piz_core.infra.ioc import environment, Injected, Prop
from piz_core.infra.sqlite import SqliteDatabase
from piz_core.util import now_as_string, dataclass_to_tuple

logger = logging.getLogger(__name__)

# 声明实体
@dataclass
class User:
    uid: int = None
    username: str = None
    password: str = None
    description: str = None
    status: int = None
    create_time: str = field(default_factory=lambda: now_as_string())

# 声明事件
@dataclass
class UserEvent(BaseEvent):
    target: User

# 声明组件（监听事件）
@component
class Monitor:
    # 监听全部事件
    @event_listener(BaseEvent)
    def monitored(self, event: BaseEvent):
        if isinstance(event, UserEvent):
            logger.info(f"event: User, target: {event.target}, timestamp: {event.timestamp}")

# 声明组件（数据映射）            
@component
class UserMapper(BaseMapper[SqlDatabase], impl_name="sqlite_db"):
    # 查询方法
    @select("SELECT uid, username, status, create_time FROM user "
            "WHERE username = #{username} AND password = #{password}", res_type=User)
    def select_user_by_username(self, username: str, password: str) -> User: ...
    # 插入方法
    @insert("INSERT INTO user VALUES(#{values})")
    def insert_user(self, values: tuple) -> int: ...

# 声明组件（业务处理）   
@component
class UserService:
    _mapper = Injected(instance_type=UserMapper)
    _def_enabled: int = Prop("user.def-enabled", default=1)
    # 业务方法
    def save_user(self, username: str, password: str) -> int:
        user = User(_id := id_generator.next_id(), username, password, status=self._def_enabled)

        with self._mapper.transaction():
            return _id if self._mapper.insert_user(dataclass_to_tuple(user)) > 0 else -1
    # 业务方法
    def login(self, username: str, password: str) -> bool:
        user = self._mapper.select_user_by_username(username, password)

        if user is not None and user.status == 1:
            event_bus.publish(UserEvent(user))
            return True
        return False

# 组件（应用）   
class WebApplication:
    USERNAME = "PIZ"
    PASSWORD = "123456"

    def __init__(self):
        self._service: UserService = cast(UserService, cast(object, None))

    @inject
    def set_service(self, service: UserService):
        self._service = service

    def run(self):
        self._service.save_user(self.USERNAME, self.PASSWORD)
        if self._service.login(self.USERNAME, self.PASSWORD):
            logger.info(f"user '{self.USERNAME}' login success")

# 注册sqlite服务
@provide(name="sqlite_db")
def sqlite_database() -> SqliteDatabase:
    path: str = environment.get_config_value("dev.datasource.path")
    ddl: str = environment.get_config_value("dev.datasource.ddl")
    return SqliteDatabase(path, init_ddl=ddl)

# 注册应用
@provide
def application():
    return WebApplication()

if __name__ == "__main__":
    setup_logging()
    application().run()
```


# TODO
1. @pre_destroy


## License
本项目代码采用 [MIT 许可证](LICENSE) 发布

本项目未依赖或使用任何第三方开源库及预训练模型