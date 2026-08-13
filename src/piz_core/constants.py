""" 常量

:version: 0.3.260813
"""
from dataclasses import dataclass
from enum import Enum
from typing import Final


NAMESPACE: Final[str] = "piz"
""" 命名空间 """
CORE_TAG: Final[str] = f"[core]"
""" 项目标签 """


@dataclass(frozen=True)
class ConfigConstant:
    """ 配置常量
    """
    PROFILES_ACTIVE: list[str] = (NAMESPACE, "profiles", "active")
    """ 配置piz.profiles.active """


class BaseEnum(Enum):
    """ 消息枚举基类
    """
    @property
    def code(self) -> str:
        """ 枚举值
        """
        return str(self.value[0])

    @property
    def message(self) -> str:
        """ 消息内容
        """
        return str(self.value[1])

    @property
    def tip(self) -> str:
        """ 提示
        """
        return str(self.value[2]) if len(self.value) > 2 else self.message

    def format_message(self, *args):
        # message 里的 {} 需是合法占位符
        return f"[{self.code}]{self.message.format(*args)}"

    def __str__(self):
        from piz_core.util import dump_json

        return dump_json({"code": self.code, "message": self.message, "tip": self.tip})

    def __repr__(self):
        return f"[{self.code}]{self.message}"


class SysTag(BaseEnum):
    """ 系统标签枚举
    """
    SYSTEM = ("SYSTEM", "系统", "系统级基础设施、框架、公共服务、公共组件")
    BUSINESS = ("BUSINESS", "业务", "业务逻辑、业务规则、业务流程、业务数据")
    DATA = ("DATA", "数据", "结构化/非结构化数据、消息体、配置")
    CHART = ("CHART", "图表", "图表、统计表、报表")
    INPUT = ("INPUT", "输入", "接收的请求、参数、消息、外部数据流入")
    OUTPUT = ("OUTPUT", "输出", "发出的响应、结果、数据流出")
    STATE = ("STATE", "状态", "生命周期状态、状态快照、状态变更记录")
    ERROR = ("ERROR", "异常", "错误、故障、异常、不可恢复的失败")
    WARN = ("WARN", "警告", "警告、风险、降级、可容忍的异常")
    SECURITY = ("SECURITY", "安全", "认证、授权、加密、越权、攻击检测")
    AUDIT = ("AUDIT", "审计", "合规追踪、操作记录、变更审计")
    EVENT = ("EVENT", "事件", "一般事件、触发、调度、任务")
    PERF = ("PERF", "性能", "延迟、吞吐量、资源使用率、性能瓶颈")

    @classmethod
    def _missing_(cls, value: object):
        """ 使用 SysTag('DATA') 进行匹配否则返回 SysTag.ERROR
        """
        for i in SysTag:
            # 尝试匹配code属性
            if str(value) == i.code:
                return i
        return cls.ERROR


class ErrorCode(BaseEnum):
    """ 异常消息枚举
    """
    # System（系统级、服务级、内部组件、运行时异常）
    S_000 = ("S000", "System unknown error", "系统未知异常")
    S_200 = ("S200", "Internal runtime error", "内部运行时错误")
    S_210 = ("S210", "Sequence allocation error", "序列分配错误")
    S_211 = ("S211", "Sequence exhausted wait timeout,\tdeadline: {0}ms", "序列耗尽等待超时，截止时间: {0}ms")
    S_220 = ("S220", "Illegal state", "非法状态")
    S_221 = ("S221", "Task already started,\ttask: {0}", "已启动，任务{0}")
    S_222 = ("S222", "Task Not started", "未启动")
    S_230 = ("S230", "Type assertion failed", "类型断言失败")
    S_231 = ("S231", "Impl type mismatch,\texpected: {0},\tgot: {1}", "实现类型不匹配，期望{0}实际{1}")

    # Parameter（请求参数、报文、接口契约、输入校验）
    P_000 = ("P000", "Parameter unknown error", "参数未知异常")
    P_100 = ("P100", "Required parameter missing", "必填参数缺失")
    P_101 = ("P101", "Argument not found in dict,\targs: {0}{1}", "参数字典中未找到字段{0}")
    P_102 = ("P102", "Event types empty{1}", "事件类型为空")
    P_103 = ("P103", "Nested field access failed,\targs: {0}{1}", "嵌套字段访问失败，路径: {0}")
    P_104 = ("P104", "Collection argument empty,\targs: {0}{1}", "集合参数为空，参数: {0}")
    P_105 = ("P105", "Required constructor argument missing,\ttype: {0},\texpected: {1},\tgot: {2}",
             "构造函数缺少必要参数，类型{0}预期{1}实际{2}")
    P_110 = ("P110", "Factory function invalid", "工厂函数无效")
    P_111 = ("P111", "instance function invalid,\tinstance name: {0}", "实例{0}的实例函数无效")
    P_200 = ("P200", "Parameter format invalid", "参数格式错误")
    P_210 = ("P210", "Parameter annotation metadata invalid", "参数注解元数据非法")
    P_211 = ("P211", "Missing Qualifier/Prop in Annotated metadata,\tfunc: {0},\targs: {1}",
             "方法{0}参数{1}的Annotated注解缺少Qualifier定义")
    P_300 = ("P300", "Parameter mismatch", "参数不匹配")
    P_310 = ("P310", "Type mismatch,\texpected: {0},\tgot: {1}{2}", "类型不匹配为期望{0}实际{1}")
    P_311 = ("P311", "Unsupported type for row conversion,\ttype: {0}{1}", "不支持的行转换类型：{0}")
    P_320 = ("P320", "Value mismatch,\texpected: {0},\tgot: {1}{2}", "值不匹配为期望{0}实际{1}")
    P_321 = ("P321", "Unsupported enum value,\tvalue: {0},\ttype: {1}{2}", "不支持的枚举值{0}和类型{1}")
    P_330 = ("P330", "Parameter structure mismatch", "参数结构不匹配")
    P_331 = ("P331", "Row length mismatch,\texpected: {0},\tgot: {1},\targs: {2}{3}", "行长度不匹配，期望{0}实际{1}")
    P_332 = ("P332", "Empty row data,\targs: {0}{1}", "行数据为空，参数: {0}")
    P_333 = ("P333", "Nested row data not allowed,\targs: {0}{1}", "不支持嵌套行数据，参数: {0}")
    P_400 = ("P400", "Parameter out of range", "参数超出范围")
    P_410 = ("P410", "Parameter value out of range", "参数值超出范围")
    P_411 = ("P411", "Value below minimum,\tvalue: {0},\tmin: {1}{2}", "值{0}低于最小值{1}")
    P_412 = ("P412", "Value not greater than minimum,\tvalue: {0},\tmin: {1}{2}", "值{0}未大于最小值{1}")
    P_421 = ("P421", "Value above maximum,\tvalue: {0},\tmax: {1}{2}", "值{0}高于最大值{1}")
    P_422 = ("P422", "Value not less than maximum,\tvalue: {0},\tmax: {1}{2}", "值{0}未小于最大值{1}")
    P_430 = ("P430", "Bit width exceeded", "位宽超出限制")
    P_431 = ("P431", "Bit width overflow,\tfield: {0},\tlimit: {1}", "字段{0}位宽溢出，限制{1}位")

    # Data（数据库、缓存、数据一致性、持久层）
    D_000 = ("D000", "Data unknown error", "数据未知错误")
    D_100 = ("D100", "Data not found", "数据不存在")
    D_110 = ("D110", "No instance matched for type,\ttype: {0}", "类型{0}未匹配到任何实例")
    D_120 = ("D120", "Type matched multiple instances,\ttype: {0},\tnames: {1}", "类型{0}匹配到多个实例")
    D_130 = ("D130", "No instance resolved by type or name,\ttype: {0},\tname: {1}", "类型{0}或名称{1}未解析到实例")
    D_300 = ("D300", "Data format invalid", "数据格式错误")
    D_310 = ("D310", "Row structure error", "行结构错误")
    D_311 = ("D311", "Row length mismatch,\texpected: {0},\tgot: {1}{2}", "行长度不匹配，期望{0}实际{1}")
    D_800 = ("D800", "Data backup failed", "数据备份失败")
    D_810 = ("D811", "Database backup failed,\tpath: {0}", "数据库备份失败，备份路径: {0}")

    # Network/IO（网络通信、连接、超时、协议、文件IO）
    N_100 = ("N100", "Connection failed", "连接失败")
    N_110 = ("N110", "HTTP connection failed,\treason: {0}", "HTTP连接失败原因为{0}")

    # Config（配置缺失、格式错误、环境变量、配置中心）
    C_300 = ("C300", "Config value illegal", "配置值非法")
    C_310 = ("C310", "Config property read-only", "配置属性只读")
    C_311 = ("C311", "Attribute is read-only,\tattr: {0}", "属性{0}为只读")
    C_500 = ("C500", "Config file load failed", "配置文件加载失败")
    C_501 = ("C501", "Config file not found,\tpath: {0}", "配置文件未找到，路径: {0}")



    @classmethod
    def _missing_(cls, value: object):
        """ 使用 ErrorCode('DATA') 进行匹配否则返回 ErrorCode.S_000
        """
        for i in ErrorCode:
            # 尝试匹配code属性
            if str(value) == i.code:
                return i
        return cls.S_000

def namespaced(key: str) -> str:
    """ 自动处理重复前缀，确保拼接规范 """
    return f"{NAMESPACE}_{key.removeprefix(NAMESPACE + '_')}"