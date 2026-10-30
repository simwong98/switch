# Changelog

## Unreleased

- Fixed Open only activating Claude Desktop without selecting the conversation in third-party mode. Sessions indexed under `Claude-3p` now use the direct local-session link; standard Desktop links and read-state synchronization are unchanged.
- 修复第三方模式下“打开”只唤起 Claude Desktop、不切换会话的问题：`Claude-3p` 中的会话改用本地会话直达链接，标准 Desktop 链接及已读同步规则保持不变。
- Fixed a forked Claude session, such as a `/btw` side chat, posing as its original conversation. The fork copies the original records and session ID, so the original card could show the side chat's reply and state. Sessions are now identified by their transcript file; an archived fork stays hidden and an unarchived fork gets its own card.
- 修复分叉出的 Claude 会话（如 `/btw` 旁路对话）冒充原会话的问题：分叉会复制原会话的记录和会话 ID，导致原卡片显示旁路对话的回复和状态。现在按会话文件识别会话，已归档的分叉不显示，未归档的分叉单独成卡。
- Fixed missing Claude sessions started with a model-bound slash command such as `/goal …`. Commands recorded as human turns now count as user messages immediately; local settings commands such as `/login` and `/effort` remain excluded.
- Claude Desktop connected to a third-party model gateway keeps its Code session index in `Claude-3p`; Switch now reads it, so those cards get the Desktop title, read state and Open button.
- 修复通过斜杠命令（如 `/goal …`）向模型提交任务时 Claude 会话不显示的问题：记录为用户轮次的命令立即算作用户消息，`/login`、`/effort` 等本地设置命令仍不收。
- 接入第三方模型网关的 Claude Desktop 把 Code 会话索引放在 `Claude-3p` 目录，现在也会读取，卡片能拿到 Desktop 标题、已读状态和“打开”按钮。
- Fixed false Codex inactivity warnings on Windows when an open rollout file keeps an old modification time. New user messages, replies and tool activity now advance the activity timestamp from the log records.
- 修复 Windows 日志持续追加但文件修改时间未刷新时的 Codex“无更新”误报；普通消息、回复和工具活动均通过日志时间更新活跃状态。
- Fixed duplicate Windows instances sharing an occupied loopback port; the listener now reserves its port exclusively and the real lifecycle regression also runs on Windows.
- 修复 Windows 第二个实例可绑定已占用端口的问题，改用独占监听，并启用真实启动、端口冲突、认证停止回归测试。
- Fixed Windows legacy-encoding failures in Codex session titles, native read-state loading and UTF-8 hook input. Added regressions and made the test suite portable across Windows/POSIX; POSIX-only integration checks remain explicitly skipped on Windows.
- 修复 Windows 默认编码导致的 Codex 中文标题乱码、原生已读状态读取失败、UTF-8 hook 输入丢失；新增回归用例并修正测试的平台假设，Windows 明确跳过 POSIX 专属集成检查。
- Fixed Codex Desktop new-reply flags that stayed after a reply finished in an already open conversation. Switch now follows Codex's current read/unread state on every refresh, and keeps its last known state when that state is unavailable or older than the reply.

Initial public version of Switch:

- Local Codex and Claude Code session board with Priority, Later and Unsorted groups.
- Multiple expanded cards, drag ordering, independent column scrolling and removal undo.
- Latest full-reply reading, automatic updates and Desktop read/unread synchronization.
- Chinese/English interface and light/dark themes.
- Optional Priority-only desktop notifications and browser App badges.
- Browser-managed App installation, optional client hooks and macOS login startup.
- Local settings import/export and ownership-aware uninstall.
- Python standard-library runtime, bundled Markdown rendering and synthetic regression tests.

首个公开版本：本地多任务看板、回复全文阅读、中英文与明暗主题、仅“重要”栏提醒及角标、浏览器 App、可选 hooks 与 macOS 登录自启，以及设置迁移和卸载清理。Windows 验证范围见 README。

修复：在已打开的 Codex Desktop 会话里完成回复后，新回复标记不再残留；现在每次刷新都以 Codex 当前的已读/未读状态为准，状态不可用或早于回复时保持已知状态。
