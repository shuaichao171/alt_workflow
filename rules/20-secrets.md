# 敏感信息

- 密钥、令牌、账号、本机绝对路径只存放在 `private/` 目录；新增敏感配置时同步更新 `private.example/` 里的模板（只放占位值）。
- 不要在回复、日志、提交信息或公开文件中输出 `private/secrets.json` 里的密钥值。需要用密钥时由脚本读取，AI 不直接读取或复述。
- 不要读取、输出或改动各 CLI 自身的登录凭据（如 `~/.codex/auth.json`、`.env`）。
- 提交或公开前运行 `python scripts/check_public.py`：自动检查 `private/`、`output/` 未被跟踪或暂存、模板仍是占位值、已跟踪文件中没有真实密钥。
