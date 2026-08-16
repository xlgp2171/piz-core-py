import threading
import time
import unittest
from datetime import datetime

from piz_core.infra import id_generator
from piz_core.infra.ident import Identity, IdBuilder


# infra/ident组件测试
class TestIdGenerator(unittest.TestCase):
    def test_next_id_returns_positive_integer(self):
        """next_id 应返回正整数"""
        id_val = id_generator.next_id()
        self.assertIsInstance(id_val, int)
        self.assertGreater(id_val, 0)

    def test_next_id_monotonic_increasing(self):
        """连续调用 next_id 应严格单调递增"""
        id1 = id_generator.next_id()
        id2 = id_generator.next_id()
        self.assertLess(id1, id2)

    def test_next_id_uniqueness(self):
        """批量生成的 ID 应全局唯一"""
        ids = [id_generator.next_id() for _ in range(300)]
        self.assertEqual(len(set(ids)), len(ids))

    def test_parse_returns_identity(self):
        """parse 应返回 Identity 数据类实例"""
        id_val = id_generator.next_id()
        identity = id_generator.parse(id_val)
        self.assertIsInstance(identity, Identity)

    def test_parse_identity_version(self):
        """默认生成器解析出的 version 应为 1"""
        id_val = id_generator.next_id()
        identity = id_generator.parse(id_val)
        self.assertEqual(identity.version, 1)

    def test_parse_identity_timestamp_range(self):
        """解析出的绝对时间戳应在生成时刻前后 1 秒内"""
        before_ms = int(time.time() * 1000)
        id_val = id_generator.next_id()
        after_ms = int(time.time() * 1000)
        identity = id_generator.parse(id_val)
        real_ts = identity.real_timestamp
        self.assertGreaterEqual(real_ts, before_ms - 1000)
        self.assertLessEqual(real_ts, after_ms + 1000)

    def test_parse_identity_real_timestamp_calculation(self):
        """real_timestamp 应等于 timestamp + EPOCH(1514736000000)"""
        EPOCH = 1514736000000
        id_val = id_generator.next_id()
        identity = id_generator.parse(id_val)
        self.assertEqual(identity.real_timestamp, identity.timestamp + EPOCH)

    def test_parse_identity_real_datetime_type(self):
        """real_datetime 应返回 datetime 类型"""
        id_val = id_generator.next_id()
        identity = id_generator.parse(id_val)
        self.assertIsInstance(identity.real_datetime, datetime)

    def test_parse_identity_real_datetime_consistency(self):
        """real_datetime 的时间戳应与 real_timestamp 对应"""
        id_val = id_generator.next_id()
        identity = id_generator.parse(id_val)
        expected_ts = identity.real_timestamp / 1000.0
        self.assertAlmostEqual(identity.real_datetime.timestamp(), expected_ts, places=2)

    def test_parse_invalid_top_raises(self):
        """top 位不合法（如 0）时应抛出 ValueError"""
        with self.assertRaises(ValueError):
            id_generator.parse(0)

    def test_get_builder_returns_id_builder(self):
        """get_builder 应返回 IdBuilder 实例"""
        builder = id_generator.get_builder(1)
        self.assertIsInstance(builder, IdBuilder)

    def test_get_builder_caching(self):
        """相同参数的 get_builder 调用应返回同一缓存实例"""
        builder1 = id_generator.get_builder(20)
        builder2 = id_generator.get_builder(20)
        self.assertIs(builder1, builder2)

    def test_builder_next_id_returns_positive_integer(self):
        """IdBuilder.next_id 应返回正整数"""
        builder = id_generator.get_builder(3)
        id_val = builder.next_id()
        self.assertIsInstance(id_val, int)
        self.assertGreater(id_val, 0)

    def test_builder_next_id_monotonic_increasing(self):
        """同一 Builder 连续生成的 ID 应递增"""
        builder = id_generator.get_builder(4)
        id1 = builder.next_id()
        id2 = builder.next_id()
        self.assertLess(id1, id2)

    def test_builder_factory_parse_custom_field(self):
        """通过 builder 生成的 ID，其 custom 字段应与创建时一致"""
        custom_val = 15
        builder = id_generator.get_builder(custom_val)
        id_val = builder.next_id()
        identity = builder.factory.parse(id_val, ignore_version=True)
        self.assertEqual(identity.custom, custom_val)

    def test_different_builders_different_customs(self):
        """不同 custom 的 builder 应生成不同 custom 字段的 ID"""
        builder_a = id_generator.get_builder(5)
        builder_b = id_generator.get_builder(10)

        id_a = builder_a.next_id()
        id_b = builder_b.next_id()

        identity_a = builder_a.factory.parse(id_a, ignore_version=True)
        identity_b = builder_b.factory.parse(id_b, ignore_version=True)

        self.assertEqual(identity_a.custom, 5)
        self.assertEqual(identity_b.custom, 10)

    def test_custom_boundary_values(self):
        """custom 边界值 0 和 63 应正常工作"""
        for custom in [0, 63]:
            with self.subTest(custom=custom):
                builder = id_generator.get_builder(custom)
                id_val = builder.next_id()
                identity = builder.factory.parse(id_val, ignore_version=True)
                self.assertEqual(identity.custom, custom)

    def test_invalid_custom_raises_value_error(self):
        """custom 超出 6 位位宽（>=64）应抛出 ValueError"""
        with self.assertRaises(ValueError):
            id_generator.get_builder(64)

    def test_builder_factory_parse_version_field(self):
        """指定 version 的 builder 生成的 ID，version 字段应正确"""
        builder = id_generator.get_builder(1, version=2)
        id_val = builder.next_id()
        identity = builder.factory.parse(id_val, ignore_version=False)
        self.assertEqual(identity.version, 2)

    def test_invalid_version_raises_value_error(self):
        """version 超出 3 位位宽（>=8）应抛出 ValueError"""
        with self.assertRaises(ValueError):
            id_generator.get_builder(60, version=9)

    def test_parse_version_mismatch_raises(self):
        """默认解析器解析不同 version 的 ID 应抛出 ValueError"""
        builder_v2 = id_generator.get_builder(1, version=2)
        id_val = builder_v2.next_id()
        with self.assertRaises(ValueError):
            id_generator.parse(id_val)

    def test_sequence_increment_within_same_millisecond(self):
        """同一毫秒内连续生成 ID，sequence 应递增"""
        builder = id_generator.get_builder(0)
        ids = [builder.next_id() for _ in range(30)]
        identities = [builder.factory.parse(i, ignore_version=True) for i in ids]

        for i in range(len(identities) - 1):
            curr, nxt = identities[i], identities[i + 1]
            if curr.timestamp == nxt.timestamp:
                self.assertEqual(nxt.sequence, curr.sequence + 1)

    def test_concurrent_next_id_uniqueness(self):
        """多线程并发调用 id_generator.next_id()，所有 ID 应全局唯一"""
        results = []
        lock = threading.Lock()
        num_threads = 10
        ids_per_thread = 100

        def generate():
            local_ids = [id_generator.next_id() for _ in range(ids_per_thread)]
            with lock:
                results.extend(local_ids)
        threads = [threading.Thread(target=generate) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), num_threads * ids_per_thread)
        self.assertEqual(len(set(results)), len(results))

    def test_concurrent_same_builder_uniqueness(self):
        """多线程共享同一 Builder 并发生成 ID，应保证唯一性"""
        builder = id_generator.get_builder(7)
        results = []
        lock = threading.Lock()
        num_threads = 8
        ids_per_thread = 50

        def generate():
            local_ids = [builder.next_id() for _ in range(ids_per_thread)]
            with lock:
                results.extend(local_ids)
        threads = [threading.Thread(target=generate) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), num_threads * ids_per_thread)
        self.assertEqual(len(set(results)), len(results))

    def test_concurrent_different_builders(self):
        """多线程使用不同 custom 的 Builder 并发生成，ID 应全局唯一"""
        results = []
        lock = threading.Lock()
        customs = list(range(10))
        ids_per_thread = 50

        def generate(custom):
            builder = id_generator.get_builder(custom)
            local_ids = [builder.next_id() for _ in range(ids_per_thread)]
            with lock:
                results.extend(local_ids)
        threads = [threading.Thread(target=generate, args=(c,)) for c in customs]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), len(customs) * ids_per_thread)
        self.assertEqual(len(set(results)), len(results))

    def test_concurrent_parse_consistency(self):
        """多线程并发解析同一 ID，结果应完全一致"""
        id_val = id_generator.next_id()
        results = []
        lock = threading.Lock()
        num_threads = 20

        def parse_id():
            identity = id_generator.parse(id_val)
            with lock:
                results.append(identity)

        threads = [threading.Thread(target=parse_id) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), num_threads)
        first = results[0]

        for identity in results[1:]:
            self.assertEqual(identity.version, first.version)
            self.assertEqual(identity.timestamp, first.timestamp)
            self.assertEqual(identity.sequence, first.sequence)
            self.assertEqual(identity.custom, first.custom)

    def test_concurrent_mixed_operations(self):
        """混合并发：同时生成、解析、获取 Builder，系统应稳定无异常"""
        errors = []
        lock = threading.Lock()
        num_threads = 12

        def mixed_task(thread_id):
            try:
                # 通过默认生成器生成
                id1 = id_generator.next_id()
                identity1 = id_generator.parse(id1)
                self.assertEqual(identity1.version, 1)
                # 获取 builder 并生成
                builder = id_generator.get_builder(thread_id % 64)
                id2 = builder.next_id()
                identity2 = builder.factory.parse(id2, ignore_version=True)
                self.assertEqual(identity2.custom, thread_id % 64)
                # 验证时间戳合理性
                self.assertGreater(identity1.real_timestamp, 1514736000000)
                self.assertIsInstance(identity1.real_datetime, datetime)
            except Exception as e:
                with lock:
                    errors.append(str(e))
        threads = [threading.Thread(target=mixed_task, args=(i,)) for i in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0, f"并发混合操作出现错误: {errors}")

    def test_high_concurrent_throughput(self):
        """高并发压力测试：短时间内大量生成，验证无重复"""
        builder = id_generator.get_builder(42)
        results = []
        lock = threading.Lock()
        num_threads = 16
        ids_per_thread = 200

        def generate():
            local_ids = [builder.next_id() for _ in range(ids_per_thread)]
            with lock:
                results.extend(local_ids)
        start = time.time()
        threads = [threading.Thread(target=generate) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start
        total = num_threads * ids_per_thread
        self.assertEqual(len(results), total)
        self.assertEqual(len(set(results)), total)
        # 仅作性能参考，不硬性断言耗时
        print(f"\n[性能参考] 高并发测试: {total} 个 ID，{num_threads} 线程，耗时 {elapsed:.3f}s")

    def test_concurrent_get_builder_caching(self):
        """多线程并发获取同一参数的 Builder，应返回同一缓存实例"""
        instances = []
        lock = threading.Lock()
        num_threads = 20

        def get_builder():
            builder = id_generator.get_builder(33)
            with lock:
                instances.append(builder)
        threads = [threading.Thread(target=get_builder) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(instances), num_threads)
        first = instances[0]

        for b in instances[1:]:
            self.assertIs(b, first)
