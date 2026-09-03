import unittest

from _support import DbService, db_service, SingletonClass, PrototypeClass
from piz_core.const import NAMESPACE
from piz_core.infra.ioc import environment, container, TYPE_INSTANCE, TYPE_CALLABLE
from piz_core.util import real_path


# infra/ioc和infra/event组件测试
class TestIocEvent(unittest.TestCase):
    def test_container_and_event(self):
        service: DbService = container.resolve(instance_name="db_service")
        service.save_default_name()
        self.assertEqual(service.load_name(), "root")
        self.assertEqual(service.get_version(), 1)
        service: DbService = db_service()
        service.save_name("Hello")
        self.assertEqual(service.get_version(), 2)
        service.save_default_name()
        self.assertEqual(service.load_name(), "Hello")
        self.assertEqual(service.get_version(), 3)
        self.assertEqual(service.get_security_key(), "token 1236")

    def test_environment(self):
        self.assertEqual(environment.get_config_value(f"{NAMESPACE}.information.version"), "0.2.0")
        self.assertEqual(environment.get_config_value("dev.username", default="user"), "user")
        self.assertEqual(environment.get_config_value(
            "dev.datasource.username", default="user"), "root")
        self.assertEqual(environment.loaded_paths(), [real_path() + "/sample/config_main.toml"])
        environment.set_config("/tmp/test", {"ssim": {"version": "0.5.0"}})
        self.assertEqual(environment.loaded_paths()[1], "/tmp/test")
        environment.remove_config("/tmp/test")
        self.assertEqual(len(environment.loaded_paths()), 1)
        self.assertFalse(environment.is_stale(environment.default_path))

    def test_container_scope(self):
        inspect = container.inspect()
        # 注册测试
        self.assertTrue("singletonClass" in inspect)
        self.assertEqual(inspect.get("singletonClass")[1], TYPE_INSTANCE)
        self.assertTrue("prototypeClass" in inspect)
        self.assertEqual(inspect.get("prototypeClass")[1], TYPE_CALLABLE)
        self.assertFalse("standaloneClass" in inspect)
        # 单例测试
        singleton: SingletonClass = container.resolve(instance_name="singletonClass")
        self.assertEqual(singleton.count, 0)
        singleton.reset(-1)
        singleton = container.resolve(instance_type=SingletonClass)
        self.assertEqual(singleton.count, -1)
        # 类型测试
        prototype1 = container.resolve(instance_type=PrototypeClass)
        self.assertEqual(prototype1.count, 0)
        prototype1.reset(1)
        prototype2: PrototypeClass = container.resolve(instance_name="prototypeClass")
        self.assertEqual(prototype2.count, 0)
        prototype2.reset(-1)
        self.assertEqual(prototype1.count, 1)
        self.assertEqual(prototype1.count - prototype2.count, 2)
