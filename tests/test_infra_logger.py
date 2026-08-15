import json
import logging
import unittest
from unittest.mock import patch, MagicMock

from piz_core.const import SysTag
from piz_core.infra.logger import LogPayload, LogMode, setup_logging


# infra/logger组件测试
class TestLogger(unittest.TestCase):
    def test_log_payload(self):
        # 测试 LogPayload __init__ 参数 value: str - 合法 JSON 格式
        payload = LogPayload('{"mode": 2, "tag": "TEST", "name": "json_name", "message": "json_msg"}')
        self.assertEqual(payload.message, "json_msg")
        self.assertEqual(payload.name, "json_name")
        # 测试 LogPayload __init__ 参数 value: str - 非 JSON 普通字符串
        payload = LogPayload("plain text message")
        self.assertEqual(payload.message, "plain text message")
        self.assertEqual(payload.name, "")
        # 测试 LogPayload set_message 参数 message: str
        payload = LogPayload("old")
        payload.set_message("new")
        self.assertEqual(payload.message, "new")
        # 测试 LogPayload mode 属性 - 存在有效整数值
        payload = LogPayload('{"mode": 3}')
        self.assertEqual(payload.mode, 3)
        # 测试 LogPayload mode 属性 - 无效字符串返回默认值 LogMode.RECORD
        payload = LogPayload('{"mode": "not_a_number"}')
        self.assertEqual(payload.mode, LogMode.RECORD)
        # 测试 LogPayload mode 属性 - 缺失键返回默认值 LogMode.RECORD
        payload = LogPayload("{}")
        self.assertEqual(payload.mode, LogMode.RECORD)
        # 测试 LogPayload tag 属性 - 存在有效 tag code
        payload = LogPayload(f'{{"tag": {SysTag.OUTPUT.code}}}')
        self.assertEqual(payload.tag, SysTag.OUTPUT)
        # 测试 LogPayload tag 属性 - 缺失键返回默认 SysTag.OUTPUT
        payload = LogPayload("{}")
        self.assertEqual(payload.tag, SysTag.OUTPUT)
        # 测试 LogPayload name 属性 - 存在值
        payload = LogPayload('{"name": "exists"}')
        self.assertEqual(payload.name, "exists")
        # 测试 LogPayload name 属性 - 缺失键返回空字符串
        payload = LogPayload("{}")
        self.assertEqual(payload.name, "")
        # 测试 LogPayload message 属性 - 存在值
        payload = LogPayload('{"message": "exists"}')
        self.assertEqual(payload.message, "exists")
        # 测试 LogPayload message 属性 - 缺失键返回空字符串
        payload = LogPayload("{}")
        self.assertEqual(payload.message, "")
        # 测试 LogPayload encode 参数 - 使用默认值 name="", mode=LogMode.RECORD
        data = json.loads(LogPayload.encode(SysTag.OUTPUT, "hello"))
        self.assertEqual(data[LogPayload.KEY_MODE], LogMode.RECORD)
        self.assertEqual(data[LogPayload.KEY_TAG], SysTag.OUTPUT.code)
        self.assertEqual(data[LogPayload.KEY_NAME], "")
        self.assertEqual(data[LogPayload.KEY_MESSAGE], "hello")
        # 测试 LogPayload encode 参数 - 自定义 name
        result = LogPayload.encode(SysTag.OUTPUT, "msg", name="my_name")
        data = json.loads(result)
        self.assertEqual(data[LogPayload.KEY_NAME], "my_name")
        # 测试 LogPayload encode 参数 - 自定义 mode=LogMode.PUBLISH
        data = json.loads(LogPayload.encode(SysTag.OUTPUT, "msg", mode=LogMode.PUBLISH))
        self.assertEqual(data[LogPayload.KEY_MODE], LogMode.PUBLISH)
        # 测试 LogPayload encode 参数 - 自定义 mode=LogMode.IGNORE
        data = json.loads(LogPayload.encode(SysTag.OUTPUT, "msg", mode=LogMode.IGNORE))
        self.assertEqual(data[LogPayload.KEY_MODE], LogMode.IGNORE)
        # 测试 LogPayload encode 参数 - 所有参数均自定义
        data = json.loads(LogPayload.encode(SysTag.OUTPUT, "full_custom", name="full_name",
                                            mode=LogMode.PUBLISH | LogMode.RECORD))
        self.assertEqual(data[LogPayload.KEY_MODE], LogMode.PUBLISH | LogMode.RECORD)
        self.assertEqual(data[LogPayload.KEY_TAG], SysTag.OUTPUT.code)
        self.assertEqual(data[LogPayload.KEY_NAME], "full_name")
        self.assertEqual(data[LogPayload.KEY_MESSAGE], "full_custom")

    @patch('logging.root.removeHandler')
    @patch('logging.basicConfig')
    @patch('builtins.print')
    def test_setup_logging_all_handlers_enabled(
            self, mock_print, mock_basicConfig, mock_removeHandler):
        """测试 setup_logging 所有参数 - 启用 publish、file、console 全部处理器"""
        mock_publish = MagicMock()

        with patch('os.path.isdir', return_value=True), patch('os.path.join', side_effect=lambda *args: '/'.join(args)):
            setup_logging(file_name="app", level=logging.DEBUG, log_format="%(message)s", console=True,
                          publish_func=mock_publish, log_dir="logs", max_bytes=10 * 1024 * 1024, backup_count=3)
        mock_removeHandler.assert_called_once()
        kwargs = mock_basicConfig.call_args.kwargs
        self.assertEqual(kwargs['format'], "%(message)s")
        self.assertEqual(kwargs['level'], logging.DEBUG)
        self.assertTrue(kwargs['force'])
        self.assertEqual(len(kwargs['handlers']), 3)  # PUBLISH + ROTATING + STREAM
        mock_print.assert_called_once()
        logging.shutdown()

    @patch('logging.root.removeHandler')
    @patch('logging.basicConfig')
    @patch('builtins.print')
    def test_setup_logging_default_params(
            self, mock_print, mock_basicConfig, mock_removeHandler):
        # 测试 setup_logging 默认参数 - 仅控制台输出"""
        setup_logging()
        mock_removeHandler.assert_called_once()
        kwargs = mock_basicConfig.call_args.kwargs
        self.assertEqual(kwargs['level'], logging.DEBUG)
        self.assertEqual(kwargs['format'], "%(asctime)s [%(levelname)s] %(message)s")
        self.assertTrue(kwargs['force'])
        self.assertEqual(len(kwargs['handlers']), 1)  # 仅 STREAM
        mock_print.assert_called_once()
        logging.shutdown()

    def test_setup_logging(self):
        setup_logging("info", publish_func=lambda t,n,m: print(f"{t.code} - {n} - {m}"))
        logger = logging.getLogger(__name__)
        logger.error(LogPayload.encode(SysTag.BUSINESS, "载荷异常日志", "ERROR_TEST"), exc_info=True)
        logger.info(LogPayload.encode(
            SysTag.OUTPUT, "发布的消息", "PUBLISHED", LogMode.PUBLISH | LogMode.RECORD))
        logger.debug("DEBUG_调试信息")
        logger.info("INFO_TEST_标准日志")
