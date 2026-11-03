"""面向使用者的错误类型。每个错误都带一段中文、可操作的说明。"""


class UserFacingError(Exception):
    """可以直接展示给研究人员的错误。message 必须是中文、可操作的。"""


class ConfigError(UserFacingError):
    pass


class DataError(UserFacingError):
    pass


class ComplianceError(Exception):
    """试图把患者级数据发送给 LLM。属于程序缺陷，不应被吞掉。"""


class ValidationGateError(Exception):
    """在登记与验证阶段之外、或针对未登记假设访问验证集。属于程序缺陷。"""


class BudgetExceeded(Exception):
    """token 预算耗尽。研究循环会保存进度并停止。"""
