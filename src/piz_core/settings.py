""" 统一配置

:version: 0.3.260730
"""
from dataclasses import dataclass


@dataclass
class Settings:
    node_id = 0
    """ 节点标识（默认0，范围0-63） """
    validate_types_enabled: bool = True
    """ 方法输入类型验证开关（默认True） """

