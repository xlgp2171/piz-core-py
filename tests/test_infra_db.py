
import unittest

from _support import ModelMapper, SklModel, StatusEvent, SklModels, ModelTypes
from piz_core.deco import provide
from piz_core.infra.ioc import Prop, environment, container
from piz_core.infra.sqlite import SqliteDatabase
from piz_core.util import delete_path, real_path, now_as_string


# infra/db组件测试
class TestDatabase(unittest.TestCase):
    db_path: str = Prop("dev.datasource.url")
    db_ddl: str = Prop("dev.datasource.ddl")

    @classmethod
    def setUpClass(cls):

        environment.set_default_path("sample/config_main.toml")
        cls.create_database()

    @classmethod
    def tearDownClass(cls):
        container.resolve(instance_type=SqliteDatabase).close()
        delete_path(real_path(cls.db_path))
        delete_path(real_path(cls.db_path + "-wal"))
        delete_path(real_path(cls.db_path + "-shm"))

    @classmethod
    @provide(name="sqlite_db", eager=False)
    def create_database(cls):
        return SqliteDatabase(cls.db_path, init_ddl=cls.db_ddl)

    def test_mapper_and_transaction(self):
        mapper: ModelMapper = container.resolve(instance_type=ModelMapper)
        # 单个插入
        self.assertEqual(mapper.insert_model1(
            mid=1, m_type="text", score=89.25, status=0, create_time=now_as_string()), 1)
        count = 1
        self.assertEqual(mapper.insert_model2(SklModel(2, "text", 91.25, -1, "2026-03-01 10:30:00")), 1)
        count += 1
        self.assertEqual(mapper.insert_model3(
            {"mid": 3, "m_type": "text", "score": 87.25, "status": -1, "create_time": "2026-02-01 10:30:00"}), 1)
        count += 1
        self.assertEqual(mapper.insert_model4([4, "event", 84.25, -1, "2026-01-01 10:30:00"]), 1)
        count += 1
        # 批量插入
        self.assertEqual(mapper.insert_model5([
            SklModel(5, "event", 88.64, 0, now_as_string()),
            SklModel(6, "event", 85.64, -1, "2026-03-02 15:30:00")]), 2)
        count += 2
        self.assertEqual(mapper.insert_model6([
            {"mid": 7, "m_type": "event", "score": 82.64, "status": -1, "create_time": "2026-02-02 15:30:00"},
            {"mid": 8, "m_type": "event", "score": 78.64, "status": -1, "create_time": "2026-01-02 15:30:00"}]), 2)
        count += 2
        self.assertEqual(mapper.insert_model7([(9, "images", 79.39, -1, "2026-03-03 20:30:00"),
            (10, "images", 75.39, -1, "2026-02-03 20:30:00"), (11, "images", 73.39, -1, "2026-01-03 20:30:00")]), 3)
        count += 3
        # 统计查询
        self.assertEqual(mapper.select_model1(), count)
        # 单个查询
        self.assertEqual(mapper.select_model2(mid=1).status, 0)
        self.assertEqual(mapper.select_model3(SklModel(m_type="event", score=80)).create_time, "2026-01-02 15:30:00")
        # 批量查询
        self.assertEqual(mapper.select_model4(["text", "event", "images"], 90.1)[0]["status"], -1)
        self.assertEqual(mapper.select_model5([1, 3, 5, 7, 11], ["text"])[0].m_type, "text")
        self.assertEqual(len(mapper.select_model6(SklModel(score=88), ["text", "event"])), 3)
        self.assertEqual(mapper.select_model7(
            SklModel(create_time="2026-03-03 20:30:00"), StatusEvent("images"))[0]["id"], 9)
        self.assertEqual(len(mapper.select_model8(
            "2026-01-01 00:00:00", SklModels(90, ModelTypes(["text", "event", "images"])))), count)
        # 单个修改
        self.assertEqual(mapper.update_model1(0, SklModel(score=90, m_type="text")), 1)
        self.assertEqual(mapper.update_model2(-1, 1), 1)
        # 单个删除
        self.assertEqual(mapper.delete_model1({"score": 90, "status": [0, -1]}), count - 1)
        self.assertEqual(len(mapper.select_model4(["text", "event", "images"], 0)), 1)
        # 事务处理
        try:
            with mapper.transaction():
                self.assertEqual(mapper.delete_model1({"score": 100, "status": [0]}), 1)
                self.assertEqual(mapper.select_model1(), 0)
                raise RuntimeError("Planned errors")
        except RuntimeError:
            pass
        self.assertEqual(len(mapper.select_model4(["text", "event", "images"], 0)), 1)