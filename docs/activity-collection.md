# 活动时长采集

柱状图和近期 AI 活动时长统一读取 `data/codex-activity.json`。
该文件由使用 Codex 的电脑生成，GitHub Actions 无法直接读取本机日志。

## 计算方法

- 扫描 Codex 的 `sessions`、`archived_sessions` 下全部 JSONL 文件，包括同一会话的续接片段。
- 只使用用户/助手消息和工具调用等活动事件的时间戳，忽略系统消息和内部子代理。
- 同一会话的相邻事件间隔不超过 15 分钟时，计入其间时长；超过阈值的间隔不计入。
- 合并并行会话的重叠区间，按北京时间午夜拆分每日统计。
- 结果是 AI 活动估算，不等于精确工作时长，不包含没有事件的阅读、思考等活动。
- WakaTime 的时间不会再叠加到这份时长中。代码行数、Token 和费用继续展示 WakaTime 的采集明细，可能存在漏记。

## 持续同步

在使用 Codex 的 Linux 电脑上执行：

```sh
python3 scripts/install_sync.py --repo via2004/via2004 --codex-dir "$HOME/.codex"
systemctl --user start codex-activity-sync.service
```

需要已有的 `gh` 登录会话和该仓库写权限。用户级 systemd timer 每 15 分钟扫描一次，有新数据才提交。
电脑离线时仍会保留本地采集结果；恢复联网后的下一次运行重试。电脑关机或用户服务未运行时不会同步。

工作目录在 `~/.local/share/codex-activity-sync/`。私有缓存仅保存会话 ID 和事件时间戳，不保存对话或代码正文。
公共仓库只保存日期、时长、事件数量等汇总，不上传原始会话 ID、路径、提示词或代码。
旧事件时间戳会保留在本地缓存中，防止源日志归档或删除后历史统计缩水。

`data/codex-activity.json` 更新后会触发 GitHub Actions，自动刷新 README 和柱状图。
每日定时任务继续刷新 WakaTime 明细；接口暂不可用时保留上次明细并显示其原始更新时间，本地时长仍可更新。

## 排查

```sh
systemctl --user status codex-activity-sync.timer
systemctl --user status codex-activity-sync.service
journalctl --user -u codex-activity-sync.service -n 30 --no-pager
```

若修改了本地采集脚本，重新执行安装命令即可更新运行副本；不会删除缓存。
如果更换电脑，先迁移本地缓存；发布器会拒绝用缺少既有历史的结果覆盖远端统计。
这里只配置一台电脑作为汇总来源，多台电脑的活动还需要先合并时间区间。
