# yt-dlp 功能地图

> 给项目主人补课用：哪些能力你已经在用、哪些值得加、哪些不用管。
> 所有条目都在本地 `yt-dlp.exe 2026.11.23` 上验证过存在（`--help` 895 行）。
> 最后更新：2026-11-24

---

## 0. 先搞懂三个概念，后面全通

**① 格式选择器（`-f`）的语法**
```
-f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]"
     └──┬──┘└────┬─────┘└───┬───┘ └┬┘└────┬────┘└──────┬──────┘
       bv*     过滤条件     + 表示    ba     过滤条件    / 表示回退
   最佳视频流              音视频合并  最佳音频流          前一个不行才用后一个
```
- `/` 的优先级**低于** `+`：`A+B/C` = (A+B) 或 C
- `bv*` 和 `bv` 的区别：`bv*` 允许选中「本身已带音频」的流，`bv` 只选纯视频
- `b` = 最佳「已合并」流（YouTube 上通常只有 720p 以下）

**② 输出模板（`-o`）**
`%(title)s.%(ext)s` 里的字段来自视频元数据。常用：`%(title)s` `%(id)s` `%(height)s` `%(width)s` `%(fps)s` `%(vcodec)s` `%(acodec)s` `%(format_id)s` `%(ext)s` `%(resolution)s` `%(abr)s` `%(upload_date)s`。
- **`%(ext)s` 必须保留**，否则合并成 mkv 后扩展名还是 .mp4
- 想知道某个视频有哪些字段：`yt-dlp -j URL`，字段极多
- `%(height)sp` 这种写法是「字段 + 字面量 p」，不是特殊语法

**③ 阶段（when）**
`--print`、`--exec`、`--use-postprocessor` 都可以带阶段前缀：`before_dl:` `after_move:` `video:` 等。`after_move` = 所有后处理（合并、转码）都完成之后——这是拿到最终文件名的唯一可靠时机。

---

## 1. 你已经在用的

| 参数 | 作用 | 你在哪用的 |
|---|---|---|
| `--js-runtimes deno` | 启用 JS 运行时解析 YouTube 的签名挑战 | 你的 conf + GUI 默认 |
| `-f "bv*[ext=mp4]+ba[ext=m4a]"` | 视频+音频分流再合并 | conf 默认 |
| `--merge-output-format mp4` | 强制合并容器 | conf（GUI 已改成可切换） |
| `--retries / --fragment-retries infinite` | 无限重试防 403 | GUI 默认 |
| `--skip-unavailable-fragments` | 跳过失效分片 | GUI 默认 |
| `-N 8` | 8 线程并发下载分片 | GUI 设置项 |
| `--cookies-from-browser chrome` | 借用浏览器登录态 | GUI 设置项 |
| `-P / -o` | 目录与文件名模板 | GUI 界面 |
| `-J` | 拿完整元数据 JSON | GUI 解析用 |

---

## 2. 值得加上的（按对你的价值排序）

### ① `--print after_move:filepath` ★★★★★
下载完成后打印最终文件的完整路径。
```bash
yt-dlp ... --print after_move:filepath "URL"
# 输出：C:\Users\GUOCAN\Downloads\标题 [2160p VP9].mp4
```
**为什么对你重要**：现在 GUI 只知道「下载目录」，不知道「具体哪个文件」。有了这行，就能做「打开文件」「复制路径」「下载历史」「下完自动重命名」。这是当前架构最缺的一块拼图。
⚠️ `--print` 默认隐含 `--simulate`（只解析不下载），要真下载必须显式加 `--no-simulate`。

### ② `--download-archive FILE` ★★★★☆
```bash
--download-archive archive.txt
```
记录已下载视频的 ID，下次自动跳过。**价值**：批量补档时不会重复下；同时它就是现成的「下载历史」数据源（一行一个 `youtube dQw4w9WgXcQ`）。

### ③ `--download-sections "*00:30-01:30"` ★★★★☆
只下指定片段（需要 ffmpeg，会重新封装）。
```bash
--download-sections "*00:30-01:30"      # 下 30 秒到 1 分 30 秒
--download-sections "*10:15-inf"        # 从 10:15 到结尾
--download-sections "intro"             # 按章节标题匹配
```
**价值**：只想存某段舞蹈/某个讲解时，省掉 90% 的时间和空间。

### ④ `--embed-metadata --embed-chapters --embed-thumbnail` ★★★★☆
把标题、作者、章节、封面图写进文件本身。
**价值**：本地库里在播放器中直接显示封面和章节，不再是一堆文件名。对「收藏向」下载提升明显。

### ⑤ `--write-subs --sub-langs "zh.*,en" --embed-subs` ★★★☆☆
下载字幕并嵌入（mp4/mkv/webm 支持嵌入）。`--write-auto-subs` 取自动生成字幕。
**价值**：外语视频可看；嵌进去就是单文件带字幕，不用管 .srt 丢哪了。

### ⑥ `--sponsorblock-remove sponsor,selfpromo` ★★★☆☆
用 SponsorBlock 众包数据剪掉恰饭片段/片头。
**价值**：看视频不被打断。代价：要重编码切片，慢一些；小众视频可能没有数据。

### ⑦ `-r 4M` / `--throttled-rate 100K` ★★★☆☆
```bash
-r 4M                  # 限速 4MB/s
--throttled-rate 100K  # 速度低于 100KB/s 就认为被限速，重新取流
```
**价值**：晚上挂机下载不影响你正常上网；后者能缓解 YouTube 故意降速（你遇到的 403 有一类就是它）。

### ⑧ `--trim-filenames 180` + `--windows-filenames` ★★★☆☆
限制文件名长度、强制 Windows 安全字符。**价值**：中文长标题 + 260 字符路径上限，早晚会撞。

### ⑨ `--extractor-args "youtube:player_client=..."` ★★☆☆☆
换 YouTube 客户端取流（`web` / `ios` / `android` / `tv` / `mweb` 等）。某些客户端能绕开限流。
**价值**：403/机器人验证的备用手段，但取值会随版本变，得试。

### ⑩ `--audio-multistreams` ★★☆☆☆
把多音轨（多语言）合并进一个文件。多数视频用不上。

### ⑪ `--remux-video mkv` / `--recode-video` ★★☆☆☆
换容器（无损）或转码（有损，慢）。GUI 的「容器」下拉已经覆盖了 remux 的常用场景。

---

## 3. 你大概率不需要

| 参数 | 为什么不需要 |
|---|---|
| `--split-chapters` / `--remove-chapters` | 除非要按章节切成多个文件 |
| `--write-info-json` / `--write-description` | 调试/归档用，日常多余 |
| `--remote-components ejs:github` | 官方 exe 已自带 ejs，官方文档明说不需要 |
| `--impersonate chrome` | 主要针对别的站点反爬；YouTube 上通常无益，且可能拖慢 |
| `--xattrs` | Linux 专用 |
| `--use-extractors` / `--list-extractors` | 调试用 |

---

## 4. 三个容易踩的坑

1. **`--print` 会顺手把下载变成「只解析」**。必须 `--no-simulate`，否则你以为在下载，其实什么都没下。
2. **`-N` 只对 DASH/HLS 分片流有效**。对普通直链 mp4 没用。
3. **`--merge-output-format` 只影响「合并」，不影响「转码」**。想把 H.264 转成 H.265 得用 `--recode-video`，那是有损且慢的。

---

## 5. 怎么自己查

```bash
yt-dlp --help | less              # 895 行，按需搜
yt-dlp -j "URL"                   # 看这个视频有哪些字段/格式
yt-dlp -F "URL"                   # 看格式表（我们 GUI 用 -J 代替了）
yt-dlp --simulate -f "<选择器>" "URL"   # 只验证选择器，不下载
```

官方文档：<https://github.com/yt-dlp/yt-dlp#usage-and-options>
JS 运行时说明：<https://github.com/yt-dlp/yt-dlp/wiki/EJS>
