""" 统一配置

:version: 0.3.260815
"""
from dataclasses import dataclass


@dataclass
class Settings:
    node_id = 0
    """ 节点标识（默认0，范围0-63） """
    validate_types_enabled: bool = True
    """ 方法输入类型验证开关（默认True） """
    log_mode = 1
    """ 日志模式（默认LogMode.RECORD） """