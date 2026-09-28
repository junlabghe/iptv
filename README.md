# IPTV 直播源聚合

每天自动从公开 M3U 播放列表抓取、合并、过滤、去重，
生成 TVBox / 各类 IPTV 播放器可直接导入的 `tv.m3u` 和 `tv.txt`。

只聚合**公开免费源**，不涉及登录账号与付费内容。

## 文件

| 文件 | 说明 |
|---|---|
| `iptv_update.py` | 聚合脚本（只用 Python 标准库，`curl` 仅作兜底） |
| `sources.txt` | 来源列表，一行一个 URL，`#` 开头为注释 |
| `tv.m3u` | 生成的 M3U 播放列表（脚本输出） |
| `tv.txt` | 生成的 TVBox 文本格式（脚本输出） |

## 每天自动更新

已配置 GitHub Actions：每天 06:00（北京时间）自动运行脚本并提交更新，
也可在仓库 Actions 页面手动触发。`tv.m3u` / `tv.txt` 的 raw 链接永久不变，
TVBox 里填一次就行。

工作流文件：`.github/workflows/update.yml`（定时 `0 22 * * *` UTC）。
仓库 Settings → Actions → General 里 Workflow permissions 需设为
Read and write，以便 workflow 能提交更新。

## TVBox 导入

把 `tv.m3u` 或 `tv.txt` 的**固定订阅链接**填到 TVBox 的配置地址即可；
源每天更新后，TVBox 重新加载配置就能拿到最新列表。

## 注意

- 公开源质量参差：个别地址可能失效或标注错乱，脚本靠多源冗余缓解，
  不能保证每条都可播。
- `fanmingming` 源为 IPv6 专线，纯 IPv4 网络/设备播不了，仅作补充。
