"""后端注册表：type 名 -> (check, run)。新增后端时写一个模块并在这里合并它的 BACKENDS。"""
from . import codex, command, openai_compat

BACKENDS = {**codex.BACKENDS, **openai_compat.BACKENDS, **command.BACKENDS}
