
import unittest

from piz_core.infra import id_generator
from piz_core.infra.ioc import Prop, environment
from piz_core.infra.sqlite import SqliteDatabase
from piz_core.util import delete_path, real_path


# infra/sqlite组件测试
class TestSqliteDatabase(unittest.TestCase):
    db_path: str = Prop("dev.datasource.url")
    db_ddl: str = Prop("dev.datasource.ddl")

    @classmethod
    def setUpClass(cls):
        environment.set_default_path("sample/config_main.toml")
        cls.db = SqliteDatabase(cls.db_path, init_ddl=cls.db_ddl)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        delete_path(real_path(cls.db_path))
        delete_path(real_path(cls.db_path + "-wal"))
        delete_path(real_path(cls.db_path + "-shm"))

    def test_execute_sql(self):
        # 插入测试
        _id = id_generator.next_id()
        count = self.db.execute("INSERT INTO skl_model(id,model_type,score,status,create_time) VALUES "
                                "(:id,:model_type,:score,:status,:create_time)",
                                {"id":_id, "model_type":"text", "score":91.25, "status":0,
                                 "create_time":"2026-01-23 21:01:23"})
        count += self.db.execute_many("INSERT INTO skl_model(id,model_type,score,status,create_time) "
                                      "VALUES (?,?,?,?,?)",[
            (id_generator.next_id(),"text",85.31,-1,'2026-01-21 00:00:00'),
            (id_generator.next_id(),"text",80.87,-1,'2026-01-19 00:00:00')])
        self.assertEqual(count, 3)
        # 查询测试
        row = self.db.query_one("SELECT * FROM skl_model WHERE id=?", (_id,))
        self.assertEqual(row["status"], 0)
        rows = self.db.query_many("SELECT * FROM skl_model WHERE score>? ORDER BY id", (85,))
        self.assertEqual(len(rows), 2)
        count = self.db.query_value("SELECT COUNT(*) FROM skl_model")
        self.assertEqual(count, 3)
        # 修改测试
        self.db.execute("UPDATE skl_model SET score=score + 0.25 WHERE model_type=:model_type",
                        {"model_type": "text"})
        self.db.query_many("SELECT * FROM skl_model")
        # 删除测试
        count = self.db.execute("DELETE FROM skl_model WHERE create_time<?", ("2026-01-20 00:00:00",))
        self.assertEqual(count, 1)
        # 内同一事务，查询和修改同步数据
        with self.db.transaction():
            self.db.execute("UPDATE skl_model SET score=score - ? WHERE id=?", (0.35, _id))
            # 事务内的查询走事务连接，能读到自己未提交的写入（read-your-writes）
            value = self.db.query_value("SELECT score FROM skl_model WHERE id=?", (_id,))
        self.assertEqual(value, 91.25 + 0.25 - 0.35)
        # 异常事务自动ROLLBACK
        try:
            with self.db.transaction():
                count = self.db.execute("UPDATE skl_model SET status=-1 WHERE id=?", (_id,))
                self.assertEqual(count, 1)
                raise RuntimeError
        except RuntimeError:
            pass
        value = self.db.query_value("SELECT status FROM skl_model WHERE id=?", (_id,))
        self.assertEqual(value, 0)
        # 嵌套事务：内层可独立回滚，不影响外层
        with self.db.transaction():
            self.db.execute("UPDATE skl_model SET create_time='2026-01-23 00:00:00' WHERE status=0")  # 外层，会提交
            try:
                with self.db.transaction():  # 嵌套 → SAVEPOINT
                    self.db.execute("DELETE FROM skl_model WHERE status=0")
                    raise ValueError
            except ValueError:
                pass
        value = self.db.query_value("SELECT create_time FROM skl_model WHERE status=0")
        self.assertEqual(value, '2026-01-23 00:00:00')