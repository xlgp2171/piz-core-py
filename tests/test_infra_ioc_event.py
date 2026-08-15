import unittest

from _support import DbService, db_service
from piz_core.const import NAMESPACE
from piz_core.infra.ioc import environment, container
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


