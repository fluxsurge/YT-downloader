# 交接文档（HANDOFF）

> **读者**：后续接手这个项目的开发者或 AI。
> **目的**：不只记录「做了什么」，更记录「为什么这么做」「哪里会炸」「下一步该做什么」。
> **维护约定**：每次改动代码后，同步更新 §10 路线图、§11 变更日志；踩到新坑写进 §7 故障排查；改完记得同步 README。
> **最后更新**：2026-11-27　**版本**：1.4.1

---

## 目录

1. [项目概览](#1-项目概览)
2. [快速开始](#2-快速开始)
3. [系统架构](#3-系统架构)
4. [模块索引](#4-模块索引)
5. [配置项参考](#5-配置项参考)
6. [关键决策记录（ADR）](#6-关键决策记录adr)
7. [故障排查手册](#7-故障排查手册)
8. [验证与回归](#8-验证与回归)
9. [已知问题与技术债](#9-已知问题与技术债)
10. [路线图与待办](#10-路线图与待办)
11. [变更日志](#11-变更日志)
12. [术语表](#12-术语表)
13. [新接手 30 分钟检查清单](#13-新接手-30-分钟检查清单)
14. [版本与存档](#14-版本与存档)
15. [容器速查（mp4 / webm / mkv）](#15-容器速查mp4--webm--mkv)

---

## 1. 项目概览

**是什么**：YouTube 视频下载器的 Windows 桌面 GUI，内核是 yt-dlp。把原本在 PowerShell 里的一长串参数变成点几下完成。

**核心用户诉求**（来自用户原话）：
- 稳定下 MP4，支持 720p/1080p/4K
- 解决 YouTube 反爬（403、机器人验证）
- 同一视频会下**多个版本**（不同画质 / 编码 / 容器），要能共存不撞名
- 视频和音频**自由组合**，也可以只要音频
- 保留命令行级的灵活性，不要做成「傻瓜软件」

**当前状态**：1.1.0 可用。单链接解析 + 视频/音频自由组合 + 下载 + 最终路径回传 + 键盘流。

**明确不做（非目标）**：不做视频转码器、不做播放器、不做 YouTube 之外的站点适配。

**定位（决定取舍的判据）**：**个人维护、准备开源的工具**（2026-11-27 起）。
所以：优先「省事、可维护」，同时开始承担「陌生人第一次用」的成本。
具体体现：
- 存档快照**默认脱敏**（家目录→`%USERPROFILE%`，清空 cookies/代理，丢弃 deps_cache）；`--raw` 才保留原值
- 文档分两层：`README.md` 面向使用者，`HANDOFF.md` 面向维护者（含打包、测试、架构）
- 依赖仍外置（ffmpeg/deno），但打包脚本提供 `--bundle-deps` 给需要离线包的人
- 格式逻辑仍只为 YouTube 调优，不追求通用站点
- **尚未决定**：开源许可证（LICENSE 文件待定）、是否发布 Release

| 项 | 值 |
|---|---|
| 路径 | `C:/Users/GUOCAN/WorkBuddy AI/2026-11-24-16-49-13/yt-dlp-gui/` |
| Python | 3.14（项目内 `.venv`） |
| GUI 库 | PySide6-Essentials 6.12（**不是**全量 PySide6） |
| 引擎 | `yt-dlp.exe` 2026.11.23（项目内唯一副本） |
| 依赖 | deno 2.9.7、ffmpeg 9.0.1 |

---

## 2. 快速开始

```bat
setup.bat       :: 首次：建 .venv + 装 PySide6-Essentials（需联网）
run.bat         :: 日常：双击启动
run_debug.bat   :: 排错：保留控制台，能看到 traceback
```

**两个硬性约束，改动时别破坏：**

1. **`run.bat` 只认项目内 `.venv`**。系统 PATH 里的 Python 没装 PySide6，直接 `python main.py` 会 ImportError 静默闪退——这是第一版双击「点了没反应」的真实原因。
2. **`.bat` 必须 CRLF 换行 + 纯 ASCII**。LF 换行会让 cmd 解析错乱（`goto`、`if errorlevel` 全部失效）；UTF-8 中文在 `chcp` 生效前会乱码。

```bash
python -c "import pathlib;p=pathlib.Path('run.bat');p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))"
```

---

## 3. 系统架构

### 3.1 解析

```
URL → normalize_url() → ProbeThread → engine.probe() (-J)
   → parse_formats() → [Format]
   → video_formats(pref) / audio_formats()
   → _rebuild_video_table()（默认过滤 <1080p）
   → _rebuild_audio_table()
   → _apply_mode(mode) → _select_video() + _ensure_audio()
```

### 3.2 下载

```
_start_download()
   │  build_combo_selector(video_sel, audio_sel, audio_only) → "625+140/625+ba/..."
   │  output_template_for(cfg, video, audio, audio_only) → "%(title)s.2160p.VP9.%(ext)s"
   │  container_arg(cfg) → "" | "mp4" | "mkv"
   ▼
DownloadThread → Downloader.command() → argv list → Popen
   ▼
逐行读 stdout
   ├─ "FILEPATH|" 开头 → parse_filepath_line() → 记录最终文件 → 打开文件可用
   ├─ "PROG|"     开头 → parse_progress_line() → 进度/速度/剩余
   ├─ "PP|"       开头 → 后处理阶段
   └─ 其他             → 日志窗口
   ▼
done(code, tail) → 成功 / 跳过 / 失败（403 一键切 Cookie 重试）
```

### 3.3 线程模型

| 线程 | 触发 | 阻塞操作 |
|---|---|---|
| `ProbeThread` | 点「解析」 | `yt-dlp -J`（3~10s） |
| `DownloadThread` | 点「开始下载」 | `Popen` 读流（分钟级） |
| `UpdateThread` | 点「引擎更新」 | `yt-dlp -U` |
| `VersionCheckThread` | 启动 1.2s 后 | GitHub API |
| `ConnectThread` | 点「测试连通」 | HTTP GET generate_204 |
| `ThumbThread` | 解析成功后 | 下载缩略图 |

**铁律**：UI 线程里不许出现 `subprocess.run` 或 `urllib`。

---

## 4. 模块索引

### `app/engine.py`

| 函数 / 类 | 职责 |
|---|---|
| `find_ytdlp / find_ffmpeg / find_deno` | 按「配置路径 → 程序目录 → PATH」找工具 |
| `detect_deps()` → `Deps` | 探测三个依赖 + 版本号 |
| `base_args(cfg, deps)` | 公共参数：`--ignore-config --no-colors --encoding utf-8 --no-playlist --js-runtimes --proxy --cookies --ffmpeg-location` + 高级参数 |
| `normalize_url()` | 清链接；裸 11 位 ID 也识别 |
| `parse_formats(info)` → `[Format]` | 过滤 storyboard/mhtml |
| `video_formats(f, codec_pref)` | 排序：分辨率 ↓ → 帧率 ↓ → 编码偏好 → 码率 ↓ |
| `best_video(f, cap, codec_pref)` | 取「≤cap 的第一行」 |
| `codec_tag(codec)` | 文件名用短名（H264 而非 H.264，避免与扩展名混淆） |
| `output_label / output_template_for` | 生成 `.2160p.VP9` 这类标签与完整模板 |
| `build_combo_selector(video, audio, audio_only)` | **组合选择器，最容易出错的地方**，见 ADR-06 / ADR-10 |
| `container_arg / container_hint` | 容器参数与界面显示值 |
| `translate_error(text)` | 把 yt-dlp 报错翻成人话（规则表 `_ERROR_RULES`） |
| `probe()` | `-J` 解析 |
| `parse_progress_line / parse_filepath_line` | 解析 `PROG\|`、`PP\|`、`FILEPATH\|` 行 |
| `Downloader` | 命令拼装 + `Popen` + 逐行读 + `taskkill /T` 取消 |
| `check_latest_version / is_newer / update_engine / test_connectivity` | 版本与网络 |

### `app/ui/main_window.py`

| 区域 | 关键方法 |
|---|---|
| 构建 | `_build_header / _build_url_row / _build_info_row / _build_options_row / _build_video_header / _build_audio_header / _build_summary_row / _build_path_row / _build_progress_row / _build_log / _build_statusbar / _bind_shortcuts` |
| 解析 | `_on_parse / _on_probe_ok / _on_probe_fail` |
| 双表 | `_populate / _rebuild_video_table / _rebuild_audio_table / _highlight / _row_of / _select_video / _select_audio / _ensure_audio` |
| 选择 | `_on_video_clicked / _on_video_selection / _on_audio_clicked / _on_audio_selection / _on_chip / _apply_mode / _on_show_all_toggled / _on_audio_only_toggled` |
| 下载 | `_start_download / _on_progress / _on_filepath / _on_download_done / _on_cancel / _on_retry_other / _on_open_file` |
| 键盘 | `_shortcut_paste / _shortcut_enter / _shortcut_escape` |

### 其他

- `app/config.py`：`load_config / save_config / resolve_proxy / app_dir`，配置落在项目根 `config.json`（便携）。
- `app/theme.py`：`build_qss(chevron)`，`$BRAND` 占位符替换（避免 f-string 双花括号地狱）。
- `app/branding.py`：`app_icon()` 读 `assets/icon.ico`，缺失时 QPainter 兜底；`chevron_path()` 按需生成下拉箭头。
- `app/history.py`：下载历史（`history.json`），去重键 `video_id|video_format|audio_format|container`；`load / find / record / remove / clear`。
- `app/ui/history_dialog.py`：历史窗口（双击打开文件、删除单条、清空）。
- `app/ui/settings_dialog.py`：设置窗口（引擎/ffmpeg/deno 路径、代理、Cookie、并发、文件名模板、高级参数、从 conf 导入、清理临时文件）。
- `tools/make_icon.py`：生成 `icon.ico`（9 尺寸）+ `icon.png` + `chevron_down.png`。
- `tools/build_exe.py`：PyInstaller 打包（onedir + 拷贝引擎/资源 + 出 zip）。
- `tools/snapshot.py`：打包存档，见 §14。

---

## 5. 配置项参考

| 键 | 默认 | 含义 |
|---|---|---|
| `ytdlp_path` | `""` | 空=用程序目录的 exe |
| `ffmpeg_dir` | `""` | 空=用 PATH |
| `deno_path` | `""` | 空=用 PATH；填了传 `--js-runtimes deno:<path>` |
| `proxy_mode` | `auto` | `auto`读注册表→环境变量 / `manual` / `off` |
| `proxy_url` | `""` | manual 时使用，自动补 `http://` |
| `cookies_browser` | `""` | `chrome`/`edge`/`firefox`/`brave` |
| `cookies_file` | `""` | Netscape 格式 cookies.txt，**优先级高于浏览器** |
| `concurrent_fragments` | `8` | `-N`，夹在 1~16 |
| `infinite_retry` | `true` | true→`--retries infinite` |
| `download_dir` | `~/Downloads` | 下载成功后写入，实现「记住上次目录」 |
| `output_template` | `%(title)s.%(ext)s` | **这个默认值同时充当「未自定义」标记**：等于默认值时自动加版本标签，改成别的就完全照用 |
| `audio_pref` | `m4a` | `m4a`/`opus`/`best`，影响 `_ensure_audio` 自动配哪条 |
| `audio_mode` | `copy` | `copy`=直出原始流（不转码）/ `mp3`=转 mp3 320k，仅「仅下载音频」时生效 |
| `codec_pref` | `auto` | `auto`/`vp9`/`av1`，只影响挑哪一行 |
| `container` | `auto` | `auto`=不传 `--merge-output-format`；`mp4`/`mkv`=强制 |
| `extra_args` | `""` | 高级参数，`shlex(posix=False)` 拆分以兼容 Windows 反斜杠 |
| `last_quality` | `best` | 只记 3 个具名模式（best/1080/720） |
| `check_update` | `true` | 启动时静默查 GitHub |
| `window_geometry` | `""` | base64 的 `saveGeometry()` |

---

## 6. 关键决策记录（ADR）

### ADR-01 用 `-J` 拿 JSON，不解析 `-F` 表格
**背景**：`-F` 是给人看的对齐表格，列宽靠空格，编码可能是 GBK。
**决策**：解析走 `-J`。
**后果**：字段结构化、无对齐风险；JSON 可能几十 KB~几 MB。
**替代**：`--print-json`（逐条打印，适合播放列表）。

### ADR-02 进度用 `--progress-template`
**背景**：多文件下载时百分比互相覆盖，合并阶段还有第三种格式。
**决策**：自定义 `PROG|` 与 `PP|` 两套模板。
**后果**：字段稳定；若 yt-dlp 改字段名需同步改模板。

### ADR-03 每次调用都加 `--ignore-config`
**背景**：用户桌面有 `yt-dlp.conf`，会与 GUI 参数叠加。
**决策**：强制忽略，另提供「从 conf 导入」。
**后果**：行为可预测。

### ADR-04 容器默认「自动」= 不传 `--merge-output-format`
**背景**：无条件 mp4 时 VP9(webm)+m4a 被塞进 mp4，播放器不认（黑屏）。
**决策**：默认不传，由 yt-dlp 按编码决定；可强制 mp4/mkv。
**自动模式的规则（v1.3.1 起直接移植 yt-dlp 源码，8 种组合与实测一致）**

规则实现在 `engine.predict_container()`，逐行对应 yt-dlp 的 `get_compatible_ext()`，共三层：

1. **编码白名单**：先试 mp4（avc1/hev1/hvc1/av01 + mp4a），再试 webm（vp8/vp9/av01 + opus/vorbis）
2. **扩展名兜底**：编码都不匹配时，看两条流的源扩展名是否同族
   （`{mp3,mp4,m4a,m4v,mov…}` / `{webm,weba}`）
3. 都不行 → **mkv**

| 视频流 | 音频流 | 结果 | 命中的层 |
|---|---|---|---|
| mp4 H.264 | m4a AAC | `.mp4` | ① 编码白名单 |
| mp4 AV1 | m4a AAC | `.mp4` | ① |
| **mp4 VP9（625）** | **m4a AAC** | **`.mp4`** | ② 扩展名兜底 |
| webm VP9 | webm Opus | `.webm` | ① |
| mp4 AV1 | webm Opus | `.webm` | ① |
| webm VP9 | m4a AAC | `.mkv` | ③ |
| mp4 H.264 | webm Opus | `.mkv` | ③ |
| mp4 VP9 | webm Opus | `.webm` | ① |

**第 3 行是最容易踩的**：625 是「VP9 编码 + mp4 封装」，VP9 不在 mp4 白名单里，但两条流同属 mp4 族，第 ② 层兜底成 mp4。只看前两层会误判成 mkv。

**两层含义要分清**：
1. 真正决定容器的是 **yt-dlp / ffmpeg**——我们只是不传参数，把选择权交出去
2. `container_hint()` 只是**预测**，用于摘要显示与**历史去重键**；预测不准会导致该跳过的没跳过

**强制容器的实测**：`--merge-output-format mp4` 配 VP9+Opus 会成功——ffmpeg 把 `vp9` + `opus` 原样 remux 进 mp4（不转码，ffprobe 验证），但播放器兼容性差。所以强制 mp4 只适合确定播放器支持的场景。

**后果**：扩展名不再统一。早期文档写成「webm 流一律 mkv」是错的，已按实测更正。

### ADR-05 快捷按钮 = 高亮行的 `format_id`（所见即所得）
**背景**：用「最优画质」选择器时 yt-dlp 有自己排序，出现过高亮 625(VP9) 实际下 401(AV1)。
**决策**：先算出该选哪一行，再用该行 `format_id` 拼选择器。
**后果**：界面与结果永远一致。

### ADR-06 选择器里 audio 片段必须是单值
**背景**：曾写成 `ba[ext=m4a]/ba`，`/` 把回退项拆散，语义变成「视频失败就只下音频」。
**决策**：audio 片段只允许单值，回退只在最外层用 `/` 串联。
**后果**：回退链语义正确。**改 `build_combo_selector` 必须先跑 §8.1 验证。**

### ADR-07 Cookie 默认关闭
**背景**：读浏览器 Cookie 需先完全退出浏览器，Chrome 127+ 有 App-Bound 加密，账号有限流风险。
**决策**：默认无 Cookie；403 时弹窗一键切；设置页支持 cookies.txt。

### ADR-08 代理默认 auto + 状态栏可视化
**背景**：代理关了但注册表残留时请求直接失败，报错难懂。
**决策**：auto 读注册表→环境变量，状态栏常驻显示 + 「测试连通」。

### ADR-09 表格点击用 `itemClicked`
**背景**：`itemSelectionChanged` 会被 `_syncing` 吞掉，标志卡住后点任何行都无反应。
**决策**：真实点击走 `itemClicked`；`_populate` 用 try/finally 兜底 `_syncing`；`itemSelectionChanged` 只用于键盘导航。

### ADR-10 视频/音频双表 + 自由组合（v1.1）
**背景**：单表混排时音频行在底部要滚动；点音频行会静默切成「仅音频转 mp3」，属误操作。用户明确要「视频和音频分开选择、自由组合、可选仅音频」。
**决策**：两张独立表，各自保留选中；「仅下载音频」勾选框决定是否忽略视频；选定视频后 `_ensure_audio()` 自动配一条（按 `audio_pref`），手动点过音频行则标记 `_audio_manual` 不再覆盖。
**后果**：两个选择 = 一个组合的两部分，语义无歧义；代价是垂直空间被占（音频表 1~4 行弹性，最小窗口下保底 2 行）+ 自动配逻辑。
**替代**：分段切换（一表换内容）、双标签页、分组标题行——都被否掉，因为音频行很少，同屏可见更省事。

### ADR-11 文件名 `标题.版本标签.扩展名`（v1.1）
**背景**：同视频多版本撞名，yt-dlp 静默跳过并退出 0，界面误显示「完成」。
**决策**：点号分隔（用户不喜欢 `[]`）。标签由程序按选中行生成：`2160p.VP9`；高度未知退化为 `VP9.625`；仅音频为 `audio`。用户自定义模板时不追加标签。
**后果**：永不撞名、可读性好；代价是文件名变长（用 `--trim-filenames`，长度按保存目录动态计算，见 `filename_budget()`）。
**替代**：只加分辨率（同分辨率不同编码仍撞）、格式 ID（不可读）、`[]` 包裹（用户嫌难看）。

### ADR-12 `--print after_move:filepath` 回传最终路径（v1.1）
**背景**：GUI 只知道下载目录，不知道具体文件，无法「打开文件」/做历史。
**决策**：命令加 `--no-quiet --print "after_move:FILEPATH|%(filepath)s"`，逐行匹配 `FILEPATH|` 前缀。
**后果**：能精确打开文件、为历史记录铺路。**坑**：`--print` 隐含 `--quiet` 和 `--simulate`，必须配 `--no-quiet`，且用 `after_move` 阶段（否则拿到的是合并前的中间文件路径）。

### ADR-14 自建历史，不用 `--download-archive`（v1.1.1）
**背景**：需要「同一组合重复下载可跳过」，同时用户要下同视频的多个版本。
**决策**：自建 `history.json`，键 = `video_id + 视频格式 + 音频格式 + 容器`，命中且文件仍在才跳过；提供「仍要重新下载」（`--force-overwrites`）。
**后果**：多版本互不影响；代价是历史文件需要自己维护（已有 `remove/clear`）。
**为什么不用 `--download-archive`**：它按**视频 ID** 记录（一行 `youtube dQw4w9WgXcQ`），一旦记下，同视频换画质也会被整体跳过，与核心需求直接冲突。archive 只能当导入/导出格式。

### ADR-15 大小估算：码率 × 时长（v1.1.1）
**背景**：625（4K VP9，m3u8 流）没有 `filesize`，导致「合计」只剩音频大小，看起来像下了个 3 MB 的 4K。
**决策**：`filesize` 缺失时用 `tbr(kbps) × 1000 / 8 × duration` 推算，显示加 `≈`；两者都没有则显示「视频大小未知」。
**后果**：估算值误差取决于码率是否恒定（VBR 会偏），但足以判断「这是几百 MB 还是几 GB」。

### ADR-16 容器预测：直接移植 yt-dlp 的 `get_compatible_ext()`（v1.3.1 定稿）
**背景**：`container_hint()` 最初只看视频流 ext，webm 视频一律预测 mkv。实测 webm+opus 实际落 `.webm`，摘要撒谎；更严重的是**历史键用的就是这个预测值**，预测错会造成该跳过的没跳过、或错误跳过。
**决策演进**：
1. v1.1.2 先改成「容器族」：m4a 归 mp4 族、webm 归 webm 族，同族保留、跨族 mkv
2. v1.2.0 用 6 种组合真下载核对，发现「容器族」仍是错的：**AV1+Opus 实际落 webm**（AV1 也在 webm 白名单里），不是 mkv
3. v1.3.0 改成编码白名单，仍漏了一种：**VP9-in-mp4（格式 625）+ m4a 实际落 mp4**，我们预测 mkv
4. v1.3.1 直接把 yt-dlp 的 `get_compatible_ext()` 逐行移植过来（`app/engine.py: predict_container`），包含它最后的**兜底逻辑**：编码都不匹配时，按「源扩展名是否同族」决定——`{mp4, m4a}` 同属一族，所以 625+140 落 mp4
**后果**：8 种组合与实测 8/8 一致。**教训**：容器选择有三层（编码白名单 → 扩展名兜底 → mkv），只看前两层必错；能移植就别自己归纳。

### ADR-17 音频输出可选「直出」或「转 mp3」（v1.1.2）
**背景**：原来仅音频固定 `-x --audio-format mp3 --audio-quality 0`，把 128kbps 源转成 320k mp3 是有损膨胀，慢且占空间。
**决策**：新增 `audio_mode`：`copy`（默认，直出 m4a/webm，不转码）与 `mp3`（转 320k）。下拉只在「仅下载音频」时可用。
**后果**：默认路径无损且快；两种模式的文件名不同（`.audio.m4a` / `.audio.mp3`），历史键也因此区分，可共存。

### ADR-18 打包：onedir + 引擎放同级目录（v1.2.0）
**背景**：要能脱离 Python 环境运行，同时 yt-dlp 更新远比 GUI 频繁。
**决策**：
- `--onedir`（**禁止 `--onefile`**：每次启动要向 `%TEMP%` 解压 100MB+，白屏 3~5 秒且易被杀软拦）
- `yt-dlp.exe` / `assets/` / `config.json` 由打包脚本 **post-build 拷到 exe 同级**，不用 `--add-binary`（那会塞进 `_internal`，引擎就没法独立更新了）
- `config.py` 的 `CONFIG_PATH` 改为基于 `app_dir()` 计算（否则 frozen 后会写进 `_internal`）
- 无控制台构建加了 `sys.excepthook`：traceback 写 `startup_error.log` 并弹框，否则用户只看到「双击没反应」
**后果**：目录 124.9MB、压缩包 63.7MB；引擎可单独替换；`-U` 自更新可用（便携目录有写权限）。
**替代**：把 yt-dlp 当库内嵌（`pip install yt-dlp`）——会失去逐行进度、杀进程树取消、`-U` 自更新，否掉。

### ADR-19 附加项：主界面可勾选 + 按容器能力自动降级（v1.3.0）
**背景**：用户要「尽可能全面」地嵌入封面/元数据/章节/字幕，同时要能个性化定制。
**决策**：
- 主界面第三行放四个胶囊（封面/元数据/章节/字幕），默认前三个开、字幕关（字幕接口易 429，且会给文件添 .srt）
- 不做「一个总开关」，而是逐项存 `embed_thumbnail / embed_metadata / embed_chapters / embed_subs`
- 容器能力矩阵 `_EMBED_MATRIX` 决定上限：mkv 全支持、mp4 字幕降级为外挂、webm 只留元数据、音频无章节字幕
- 装不下的项**置灰 + 右侧提示原因**，摘要行显示实际生效的附加项
**后果**：用户勾了但容器装不下时不会静默失效，能看见「已跳过」。
**选择指引**：写给用户看的「怎么选」在 README「附加项怎么选」一节（含四场景速查表），改动默认值时记得同步。
**替代**：放设置页（每次改要进弹窗，已否）；单一总开关（无法个性化，已否）。

**字幕的两个坑（实测）**：
1. 字幕接口 429 会被 yt-dlp 当**致命错误**，整个下载直接失败（视频一字节没下）。修法：开字幕时加 `--ignore-errors`，并在 `_on_download_done` 里把「退出码非 0 但文件已产出」判定为部分成功。
2. `--write-subs` 和 `--embed-subs` 同时给，yt-dlp 会额外保留一份 `.srt`。内嵌时只给 `--embed-subs`，外挂时才给 `--write-subs`。
3. 语言码用 `zh.*` 会抓到 `zh-Hans-es-419` 这类自动翻译组合，默认改成精确码 `zh-Hans,zh-Hant,en`。

### ADR-20 启动性能：首窗口 1.1s 是平台初始化，用启动图遮（v1.3.1）
**实测**（本机，源码模式）：
| 阶段 | 耗时 |
|---|---|
| import PySide6 + app | 0.40s |
| 首次窗口 show() | **1.1~1.3s**（平台/输入法/图形子系统初始化，与控件无关） |
| 主窗口构建 | 0.6~0.9s |
| `detect_deps()`（旧） | **2.7s**，其中 `yt-dlp --version` 独占 2.3s（onefile 每次解包） |

**处置**：
1. 依赖检测移到后台线程（`DepsThread`），窗口先出来；`yt-dlp --version` 结果按「路径+大小+mtime」缓存进 `config.deps_cache`，二次启动 2.84s → 0.17s
2. 加无文字的 `QSplashScreen`（`main.py: _make_splash`）——**不能画文字**，drawText 会触发同样的字体初始化，等于没遮
3. 剩余 ~1.1s 是 Qt 首次创建窗口的固定成本，无法绕开；启动图把它从「全空白」变成「有 logo」

### ADR-21 单实例用 QLockFile + 枚举窗口唤醒（v1.4.0）
**背景**：双开会并发写 config.json / history.json。
**决策**：启动最早期用 `QLockFile(app.lock)` 抢锁；抢不到就 `EnumWindows` 按标题包含「YT 下载器」找到已有窗口，`ShowWindow(SW_RESTORE)` + `SetForegroundWindow`，新进程退出。
**后果**：第二个实例约 1.4s 退出（时间几乎都花在 import PySide6 上，锁检查本身是毫秒级）。标题会随视频名变化，所以用包含匹配而不是精确匹配。

### ADR-22 下载前做写权限 + 空间预检（v1.4.0）
**背景**：4K 一次几十 GB，磁盘满或只读共享盘会在下载中途才暴露。
**决策**：`probe_writable()` 用 0 字节探测文件（比 `os.access` 可靠）；`check_disk_space()` 按估算大小 ×2 预留（合并阶段要同时存在视频流+音频流+成品）。空间不足只**询问**不强制拦截。
**后果**：预检在「历史跳过」之后，跳过时不打扰；估算本身是近似值，×2 而非 ×2.5 是为了减少误报。

### ADR-23 三段式进度靠「百分比骤降」判断换流（v1.4.0）
**背景**：视频流下完开始下音频流时百分比从 100% 跳回 0%，观感像出错。
**决策**：`--progress-template` 不含文件名，所以不新增字段；用「百分比比上次骤降 20% 以上且仍在第①段」判定进入第②段，PP 事件进入第③段。
**后果**：无需改 yt-dlp 参数；代价是极端情况下（网络抖动导致进度回退）可能误判，概率很低。

### ADR-24 引擎更新前备份、更新后探活、失败回滚（v1.4.0）
**背景**：`yt-dlp -U` 就地替换自身，中途断网/被杀软拦截会留下半个文件（变砖）。
**决策**：更新前 `copy2` 成 `.bak`；更新后跑一次 `--version` 探活；失败则回滚 `.bak` 并如实报告；成功删除备份。
**后果**：更新失败不再变砖。代价是多一次 `--version`（2.3s）。

### ADR-25 开源后的取舍调整（v1.4.0）
**背景**：用户决定开源，定位从「个人自用」变为「个人维护、准备开源」。
**决策**：
- 存档快照**默认脱敏**（家目录→`%USERPROFILE%`、清空 cookies/代理、丢弃 deps_cache），`--raw` 保留原值
- 文档分层：README 只留使用者内容，打包/测试/架构全部进 HANDOFF（§16）
- 打包写入 PE 版本资源（版本号/产品名/中文描述），降低「未知发布者」观感
- `build_exe.py --bundle-deps` 可选内置 ffmpeg/deno
**未决**：LICENSE 选哪个、是否发 Release —— 需要用户拍板，别自己替他选。

### ADR-13 默认过滤 <1080p（v1.1）
**背景**：用户基本只下 ≥1080p，38 行里一半是噪音。
**决策**：默认只显示 ≥1080p，勾「显示全部画质」展开；点 720p 胶囊会自动展开。
**后果**：38 行降到 11 行；代价是多一个开关。

---

## 7. 故障排查手册

| 症状 | 可能原因 | 处理 |
|---|---|---|
| 双击 `run.bat` 没反应 | `.venv` 缺失 / 无 PySide6 | 跑 `setup.bat`；或用 `run_debug.bat` |
| 双击 exe 没反应 | 启动期异常（无控制台看不到） | 看 exe 同级 `startup_error.log` |
| 重复打包失败 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` | 沙箱批量删除保护 | `build_exe.py` 已改用 `rmdir /s /q` 预清理 |
| `run.bat` 报「不是内部或外部命令」 | bat 被存成 LF | 按 §2 转 CRLF |
| 界面中文变方块 | 用了 `QT_QPA_PLATFORM=offscreen`（字体数为 0） | 真实平台 + `WA_DontShowOnScreen` |
| 解析报「要求验证身份」 | 请求频率过高 | Cookie 改 Chrome；或等几分钟 |
| 下载中途 403 | CDN 令牌过期/限流 | 已无限重试；仍失败→带 Cookie 或更新引擎 |
| 合并后没声音 | 只下了视频流 | 检查摘要里是否有「+ 音频 xxx」 |
| 下完播放器黑屏 | VP9 被塞进 mp4 | 容器改「自动」或「mkv」 |
| 提示「这个组合已经下过了」 | 同画质+编码+容器重复 | 换画质/编码/容器，或删旧文件 |
| 点表格没反应 | `_syncing` 卡死（旧版本） | ADR-09 已修；复现则查 `_populate` 异常 |
| 找不到刚下的文件 | 不知道落在哪个文件 | 点状态栏「打开文件」（靠 FILEPATH 回传） |
| 音频表看不到更多条目 | 固定高度 4 行 | 表内滚动 |
| 代理连不上 | 端口变了（如 Clash 换端口） | 设置改手动，或状态栏「测试连通」 |
| `pip install` 报 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` | 沙箱批量删除保护 | 删大目录用 `cmd //c rmdir /s /q` |

---

## 8. 验证与回归

### 8.1 验证选择器（不下载，几秒）

```bash
yt-dlp.exe --simulate --print "%(format_id)s %(vcodec)s %(ext)s" -f "<选择器>" "<url>"
```

改 `build_combo_selector` / 编码偏好 / 容器后**必做**：确认「高亮行」与「实际结果」一致。

### 8.2 验证界面布局（不截屏整个桌面）

```python
w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
w.show()
app.processEvents()
w.grab().save("shot.png")
```

### 8.3 验证命名与路径回传（小样本真下载）

用 144p（`160+140`）几 MB 就能验证：文件名是否带 `.144p.H264`、`FILEPATH|` 行是否回传、重复下载是否被跳过。

⚠️ **GUI 层测试别用模态框**：跳过/失败会弹 `QMessageBox`，headless 下会卡住事件循环。要么把 `main_window.QMessageBox` 替换成假类，要么直接测 `engine.Downloader`。

⚠️ **测试必须隔离配置与历史**：主窗口里的下拉切换、下载目录都会 `save_config()` 落盘。曾因测试把 `download_dir` 写成临时目录、`container` 写成 mkv，污染了用户真实偏好。

`config.py` 与 `history.py` 的路径支持环境变量覆盖，测试脚本在 **import 之前**设置即可：

```python
os.environ["YTDLP_GUI_CONFIG"] = os.path.join(tempfile.gettempdir(), "cfg_test.json")
os.environ["YTDLP_GUI_HISTORY"] = os.path.join(tempfile.gettempdir(), "hist_test.json")
```

（比 `--mock` 启动参数更轻：不加任何用户可见的开关，任何测试框架都能用。）

### 8.5 冒烟测试（改 UI 后必跑）

```bash
.venv\Scripts\python.exe _smoke.py
```

覆盖 44 条交互路径：设置窗口构造/读取/保存、解析填表、4 个清晰度胶囊、4 个下拉全部取值、4 个附加项开关、仅音频、两个「显示全部」、点选两表、摘要、历史窗口、三个下载回调分支。

它抓不到布局问题，但能抓住「控件被删/改名后仍被引用」这类重构事故——`subs_edit` 那次就是这么漏的。

### 8.4 回归清单

- [ ] 解析：两张表都有行，标题/时长/封面正常
- [ ] 视频表默认只显示 ≥1080p；勾「显示全部」后行数变多
- [ ] 点视频行：摘要的格式 ID 变化，音频自动配好
- [ ] 点音频行：摘要的音频 ID 变化
- [ ] 勾「仅下载音频」：视频表置灰、摘要变「仅音频 → mp3」
- [ ] 切编码偏好：高亮行变化，`--simulate` 结果一致
- [ ] 切容器：摘要末尾容器跟着变
- [ ] 下载小样本：进度/速度/剩余在动，完成后「打开文件」可用
- [ ] 同组合再下一次：提示已跳过
- [ ] `Esc` 能取消，任务管理器无残留 ffmpeg

---

## 9. 已知问题与技术债

| # | 问题 | 影响 | 计划 |
|---|---|---|---|
| 1 | 下载中百分比会在「视频流完成 → 音频流开始」时从 100% 跳回 0% | 观感困惑 | 加「正在下载视频流/音频流」阶段标识 |
| 2 | ~~仅音频固定转 mp3 320k~~ | 已解决 | v1.1.2 起默认直出，可切 mp3 |
| 3 | 无批量、无断点续传面板 | 功能缺失 | 见路线图 |
| 4 | 未打包 exe | 依赖 Python 环境 | 见路线图 |
| 5 | 只针对 YouTube 调过格式逻辑 | 其他站点可能异常 | 非目标 |
| 6 | ~~音频表固定 4 行~~ | 已解决 | v1.3.2 起 1~4 行弹性，最小窗口保底 2 行 |
| 7 | 视频表底部常出现半行被裁 | 观感 | 可改为按整行高度取整 |

**界面尺寸约束（v1.3.2）**
- 最小窗口 880×780；恢复上次几何时会强制夹到最小尺寸，否则两张表会互相压盖
- 该尺寸下：视频表 ≥3 行、音频表 ≥2 行、日志 96px，全部控件可见且不重叠
- 改这两张表的最小高度前，先按 §8.2 渲染最小尺寸截图确认没有重叠

---

## 10. 路线图与待办

**当前阶段：稳定观察期（2026-11-26 起）**
用户认为功能已基本够用，准备实际使用一段时间再决定优化点。此期间优先修 bug、不主动加功能；
用户反馈的问题按「能否复现 → 是否个例 → 是否值得改」判断，别为了加功能破坏已经跑顺的路径。

**评审遗留待办（2026-11-27 评审后保留，未排期）**
- [ ] P0-1 Job Objects：GUI 崩溃时由内核销毁子进程
- [ ] P0-2 配置原子写 + 损坏自愈（history 已是 tmp+replace，config 还不是）
- [ ] P0-8 解析代际令牌（日志上限 5000 块已有）
- [ ] P1-12 下载 60s 无输出看门狗（只警告，不杀）
- [ ] P2-20 高 DPI：先在 150% 缩放下实测表格是否压盖，再决定改不改
- [ ] P3-22 配置 `_schema_version` + 迁移路由
- [ ] P3-23 轮转日志（`RotatingFileHandler`）
- [ ] F2 播放列表（需先移除硬编码的 `--no-playlist`）
- [ ] F3 限速 `-r`
- [ ] F5 片段截取 `--download-sections`
- [ ] F6 SponsorBlock（只做 `--sponsorblock-mark`）
- [ ] F7 仅下附加项 `--skip-download`
- [ ] F9 本地换壳工具箱（remux / 提取音轨）
- [ ] F10 CLI 命令预览

**批量队列**：架构改动大，等稳定期结束、且想清楚与历史的交互后再启动。

**已完成**：下载历史（自建 `history.json`，键 = `video_id + 视频格式 + 音频格式 + 容器`）。详见 ADR-14。

**打包遗留决策（只影响分发场景，个人自用不需要）**
- ffmpeg（约 80MB）/ deno（约 50~80MB）是否随包内置：自用 → 维持外置（状态栏会标红提示缺失）；真要发给别人 → 拷到 exe 同级即可，设置项已支持指定路径，不用改代码。
- 不做「首次启动在线下载 ffmpeg/deno」：受限网络易被防火墙拦，直链变更也是长期负担。

**用户已提出、下一轮一起改（不要单独动）**
- [ ] 历史界面加提示：删除单条 / 清空**只删记录，不删已下载的文件**。位置建议放在顶部 hint 行，与现有「同一个组合只会记录一条；双击可直接打开文件」并列。清空确认框里已有括号说明，但入口处也该讲清楚。

---

## 11. 变更日志

### 2026-11-27（v1.4.1）
- 修：三段进度提前跳段。`finished` 行没有 total → 百分比算成 0 → 触发兜底「骤降」判断。兜底现在要求 `status == downloading` 且有 total
- 进度模板加 `%(info.format_id)s`（第 10 段），阶段判断改为按格式 ID 精确匹配；`_phase_for_format()` 支持 `140` 与 `140-3` 这类同轨多副本
- 下载标签显示当前格式 ID，便于肉眼核对
- tests 增至 37 条（新增 5 条进度行解析用例）

### 2026-11-27（v1.4.0）— 按第三方评审清单整改
**已做**
- 单实例互斥 + 唤醒已有窗口（ADR-21）
- 下载前写权限/磁盘空间预检（ADR-22）
- 三段式进度：视频流 → 音频流 → 封装（ADR-23）
- 引擎更新备份 + 探活 + 自动回滚（ADR-24）
- 强制 mp4 装 VP9/Opus 时摘要标 ⚠ 软提示（不拦截）
- 字幕部分失败改橙色标记；字幕请求间隔 `--sleep-subtitles 1`
- 状态栏新增「定位文件」（explorer /select）与「复制路径」
- 403 弹窗改为优先引导 cookies.txt，可直接跳设置
- 历史窗口补「只删记录，不删本地文件」提示
- 存档默认脱敏（ADR-25）；打包写入 PE 版本资源；新增 `--bundle-deps`
- README 移除打包章节（移入 §16），文档按「使用者/维护者」分层
- 新增 `tests/test_engine.py`（32 条参数化用例，0.2s 跑完）

**评审处置：未采纳（已确认丢弃，不再跟踪）**
P0-5 纯音频状态机（早已实现）、P0-7 封面 webp/文件名尾部清洗（实测嵌的是 png，尾部清洗 yt-dlp 已做）、
P1-9 Cookie 自动降并发 + PO Token（前提不成立）、P1-13 临时文件 7 天自动删（与续传冲突）、
P2-15 场景预设条（界面已满）、P2-16 编码徽标/摘要合流（复杂度高收益低）、P2-17 剪贴板嗅探（打扰）、
P3-21 AppState 大重构（稳定期风险大）、F8 双语字幕合并（自写对齐脆弱）

**评审处置：记入待办（未来可能做）**
P0-1 Job Objects、P0-2 配置原子写+自愈、P0-8 解析代际令牌、P1-12 无输出看门狗、
P2-20 高 DPI 适配（需先在 150% 下实测）、P3-22 配置 schema 版本、P3-23 日志轮转、
F2 播放列表、F3 限速、F5 片段截取、F6 SponsorBlock（只做 mark）、F7 仅下附加项、
F9 本地换壳工具箱、F10 CLI 命令预览

### 2026-11-26（v1.3.3）
- 修：点「设置」报 `AttributeError: 'SettingsDialog' object has no attribute 'subs_edit'`——重构时控件被删，「读取配置」那句还留在控件创建之前。已挪进 `_load()`
- 修：设置页「字幕语言」标签重复（表单标签 + 行内标签各一个）
- 修：文件名模板的提示仍在教用户改模板，那会关掉自动版本标签。改为说明「保持默认即可」
- 修：异常弹窗标题从「启动失败」改为「出错了」（运行时异常也会走这里）
- 新增 `_smoke.py` 冒烟测试：44 项交互路径全覆盖（见 §8.5）

### 2026-11-26（v1.3.2）
- 修：窗口过矮时视频表与音频表互相压盖（最小高度之和超出可用空间）。两表最小高度降到 84/58，恢复几何时夹到最小尺寸
- 音频表在最小窗口下保底 2 行
- 文档：ADR-04 规则表补上 625 行与「三层判断」；ADR-10/ADR-11 去掉过期的「固定 4 行」「180 字符」表述
- 文档：README 补「显示全部音频」说明

### 2026-11-26（v1.3.1）
- 容器预测改为逐行移植 yt-dlp 的 `get_compatible_ext()`，补上「扩展名兜底」一层；修 625（VP9-in-mp4）+ m4a 被误判为 mkv（ADR-16）
- 音频流加「显示全部音频」勾选，默认隐藏 <100kbps 的低码率音轨
- 修「音频流」标签被挤压（最小高度 18px）
- 启动优化：依赖检测移入后台 + 版本号缓存（2.84s → 0.17s）；新增启动图（ADR-20）
- 容器下拉提示语按真实算法重写

### 2026-11-25（v1.3.0）
- 新增附加项：封面 / 元数据 / 章节 / 字幕，主界面可勾选，按容器能力自动降级（ADR-19）
- 字幕默认关闭；开启后字幕限流（429）不再拖垮整个下载，改为「视频已完成、附加项失败」
- 内嵌字幕不再残留 .srt（只给 --embed-subs）；默认语言改精确码 zh-Hans,zh-Hant,en
- 设置页移除「下载增强」总开关，只保留字幕语言
- 文档：README 加附加项联动表；HANDOFF §15.4 加能力矩阵

### 2026-11-25（v1.2.1）
- 修：小窗口下视频表比音频表还矮（倒挂）。视频表最小 150px，音频表改为 3~4 行弹性（114~142），剩余空间按 2:1 分配
- 文档：新增 §15 容器速查（三种容器差异、yt-dlp 特性、选型建议、与代码的对应）
- 文档：README 补「三种容器怎么选」；自动容器规则按实测改为编码白名单（原「同族保留」表述有误）
- 实测：6 种音视频组合真下载核对容器预测，6/6 一致

### 2026-11-25（v1.2.0）
- 新增 `tools/build_exe.py`：PyInstaller `--onedir` 绿色版（124.9MB / zip 63.7MB）
- 引擎与资源拷到 exe 同级，`_internal` 里不放 yt-dlp（ADR-18）
- 修 `CONFIG_PATH` 在 frozen 下会落到 `_internal` 的问题
- 无控制台构建加 `sys.excepthook` → `startup_error.log` + 弹框
- `tools/snapshot.py` 默认把 `dist/` 产物一并打包（`--no-dist` 可关闭）
- 新增 `requirements-dev.txt`（只锁打包用的 PyInstaller）

### 2026-11-25（v1.1.2）
- 修：容器预测只按视频流判断，webm+opus 实际是 `.webm` 却显示 mkv，且污染历史键（ADR-16）
- 新增「输出」下拉：直出原始流（默认）/ 转 mp3 320k（ADR-17）
- `--trim-filenames` 由固定 180 改为按保存目录动态计算（`filename_budget()`）
- 取消下载不再弹「失败」框；明确提示临时文件已保留可续传
- 设置页新增「维护 → 清理临时文件」（扫 `.part/.ytdl`）
- 依赖锁定 `PySide6-Essentials==6.12.*`（requirements.txt 与 setup.bat）
- 测试隔离改用 `YTDLP_GUI_CONFIG` / `YTDLP_GUI_HISTORY` 环境变量
- README 重写为面向用户（设计决策移入本文档 ADR）

### 2026-11-25（v1.1.1）
- 自建下载历史（ADR-14）：命中即跳过、可强制重下、历史窗口可打开文件
- 修：4K VP9（625）等无 filesize 的格式，「合计」只算了音频大小 → 改为按码率×时长估算并标 `≈`（ADR-15）
- 表格「大小」列同步支持估算值

### 2026-11-25（v1.1.0）
- 视频/音频拆成两张表，自由组合（ADR-10）；「仅下载音频」勾选框
- 命名规则改为 `标题.版本标签.扩展名`（ADR-11），高度未知退化、`--trim-filenames 180`
- 接入 `--print after_move:filepath`（ADR-12）：完成后可「打开文件」
- 默认过滤 <1080p（ADR-13），可展开；720p 胶囊自动展开
- 键盘流：`Ctrl+V` 解析、`Enter` 下载、`Esc` 取消
- 完成后显示低调的「再下一次（换个画质）」
- 新增 `tools/snapshot.py`（打包存档）、版本号机制
- 修：音频表首列未写 `format_id`，选中高亮靠文本比对蒙对

### 2026-11-24（v1.0.x）
- 第 3 轮：下拉控件重做（真箭头、hover/focus、按 13px 实测宽度）、参数分两行、空闲隐藏进度区、新增功能地图
- 第 2 轮：修 `run.bat` 闪退（改用 `.venv` + `setup.bat`）；品牌化（YouTube 红 + 播放键图标）；修「VP9 选不中」（ADR-05）；容器下拉；编码偏好
- 第 1 轮（MVP）：PySide6 主窗口、`-J` 解析、`--progress-template` 进度、taskkill 取消、代理/Cookie/更新

---

## 12. 术语表

| 术语 | 含义 |
|---|---|
| `format_id` | yt-dlp 给每个格式的编号（625、313、401…），随视频变化 |
| `bv*` / `ba` | best video / best audio；`*` 允许选中已带音频的流 |
| 分片（fragment） | DASH/HLS 切成的小段，`-N` 控制并发 |
| 合并（merge） | 视频流+音频流用 ffmpeg 合成，**不转码** |
| 后处理（postprocess） | 合并、转码、嵌入元数据等阶段 |
| `PROG` / `PP` / `FILEPATH` | 本项目的三类输出行前缀 |
| `_syncing` | 防止「程序化选中」触发用户选择回调的标志 |
| `_audio_manual` | 用户手动点过音频行后置位，自动配音频不再覆盖 |

---

## 13. 新接手 30 分钟检查清单

1. 读 §1、§3、§6（ADR 表）
2. `run_debug.bat` 启动一次
3. 粘贴链接解析，确认两张表都有数据
4. 用 §8.1 的 simulate 命令验证一次组合选择器
5. 用 §8.2 渲染一张截图
6. 打开 `docs/yt-dlp-feature-map.md` 看引擎还有哪些能力没用上
7. 看 §9 技术债，确认这次只动目标那一条

---

## 14. 版本与存档

**版本号**：`app/__init__.py` 里的 `__version__`，语义化（大功能 +1 小版本）。

**打存档**：

```bat
.venv\Scripts\python.exe tools\snapshot.py            :: v1.1.0_20261125_1340.zip
.venv\Scripts\python.exe tools\snapshot.py 音频双表   :: 带备注
```

产出 `archives/v<版本>_<时间>_<备注>.zip`，含：
- 全部源码（`main.py` / `app/` / `tools/`）
- 文档（`HANDOFF.md` / `README.md` / `docs/`）
- 资源（`assets/`、`docs/screenshot.png`）
- `config.json`（当前偏好，可直接覆盖回去）
- `MANIFEST.txt`（版本、时间、Python/PySide6/yt-dlp/ffmpeg/deno 版本）

**含 exe 产物**：`dist/` 存在时会一并打包（`--no-dist` 可关闭），解压后直接进 `dist/YT下载器/` 双击即可运行。
**不含**：`.venv`（太大，重跑 `setup.bat` 即可）、`__pycache__`、`build/`、`archives/` 自身。
**默认脱敏**：`config.json` 里的家目录替换为 `%USERPROFILE%`，`cookies_file` / 手动代理清空，`deps_cache` 丢弃；需要原样时加 `--raw`（会提示勿外发）。
**EXE**：目前未打包；等 PyInstaller 落地后再把 `dist/` 一并纳入存档。

**回退方法**：解压到新目录 → 重跑 `setup.bat` → 双击 `run.bat`。

**何时打存档**：每次功能批量落地并通过回归后，先问用户再打；不要每改一行就打。

---

## 15. 容器速查（mp4 / webm / mkv）

**先记住一件事：容器不影响画质。** 画质由编码 + 码率决定；换容器是 remux，不重编码、秒级、无损。
「mkv 画质更好」是错觉——只是 mkv 里通常装的是高码率 VP9。

### 15.1 定位差异

| | mp4 | webm | mkv |
|---|---|---|---|
| 本质 | ISO 标准，消费电子事实标准 | Matroska 精简子集，为网页而生 | Matroska 完整版，万能盒子 |
| 视频编码 | H.264 / HEVC / AV1 | VP8 / VP9 / AV1 | 全部 |
| 音频编码 | AAC | Opus / Vorbis | 全部（含 FLAC / DTS） |
| 播放兼容 | 手机/电视/车机/网页全认 | 浏览器好，桌面播放器一般 | VLC/MPC 通吃，iPhone 与老电视不认 |
| 剪辑软件 | 好 | 差 | 一般 |
| 多音轨 / 字幕 / 章节 | 基本不支持 | 有限 | 强项 |
| 体积 | 同画质最大 | 同画质最小 | 与源流一致 |

### 15.2 yt-dlp 的相关特性

1. **自动模式是「最兼容优先」**：按编码白名单依次试 mp4 → webm → mkv，不追求画质（规则见 ADR-04）
2. **`--merge-output-format` 只在合并那一刻生效**；对已下好的文件换容器要用 `--remux-video`（不重下）
3. **多音轨 / 多字幕 / 章节 / 封面嵌入只有 mkv 能完整保留**；`--embed-subs` 虽支持 mp4，但 mp4 只能装 mov_text，srt/ass 样式全丢
4. **强制 mp4 不会报错，但可能产出「错盒」文件**：实测 vp9+opus 能原样装进 mp4，播放器却黑屏。强制 mp4 必须同时保证 H.264/AV1 + AAC

### 15.3 选型建议

| 场景 | 选什么 | 注意 |
|---|---|---|
| 投屏 / 手机 / 电视 / 发给别人 | 强制 mp4 | 配 H.264(137) 或 AV1(401) + AAC(140) |
| 本地收藏 / 长期归档 | mkv | 多音轨、字幕、章节都能装 |
| 网页嵌入 / 浏览器播放 | webm | 体积最小 |
| 要剪辑 | mp4 + H.264 | VP9/AV1 多要转码 |
| 日常 | 自动 | 不需要判断 |

### 15.4 附加项能力矩阵（v1.3.0）

| 附加项 | mkv | mp4 | webm | mp3/m4a |
|---|---|---|---|---|
| 封面（attachment/attached_pic） | ✓ | ✓ | ✗ | ✓ |
| 元数据（title/artist 标签） | ✓ | ✓ | ✓ | ✓ |
| 章节 | ✓ | ✓ | ✗ | ✗ |
| 字幕 | 内嵌 srt | 外挂 .srt（mov_text 会丢样式） | 外挂 .srt | ✗ |

代码：`_EMBED_MATRIX` → `enhance_plan()` → `enhance_args()` → `enhance_text()`（摘要显示）。
主界面胶囊的可用状态由 `_refresh_attach_state()` 按当前预测容器刷新。

### 15.5 与代码的对应

- `engine.container_hint()`：编码白名单预测（ADR-16），用于摘要显示与**历史去重键**
- `engine.container_arg()`：`auto` 返回空串（不传参数）；`mp4`/`mkv` 返回强制值
- `_MP4_VIDEO / _MP4_AUDIO / _WEBM_VIDEO / _WEBM_AUDIO`：白名单常量，改动前先按 §8.1 跑真下载核对

---

## 16. 打包与分发

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe tools\build_exe.py                 :: 标准绿色版
.venv\Scripts\python.exe tools\build_exe.py --console       :: 带控制台，排错用
.venv\Scripts\python.exe tools\build_exe.py --bundle-deps   :: 连 ffmpeg/deno 一起打（真·离线）
```

产物：`dist/YT下载器/` + `archives/YT下载器_v<版本>_win64.zip`。

**约定**：
- 必须 `--onedir`，禁止 `--onefile`（每次启动解压 100MB+ 到 `%TEMP%`，白屏且易被杀软拦）
- `yt-dlp.exe` / `assets/` / `config.json` 由 post-build 拷到 exe **同级**，不塞 `_internal`，这样引擎能独立更新
- 打包时自动生成 PE 版本资源（版本号/产品名），降低「未知发布者」观感与杀软误报
- `--bundle-deps` 会把 `ffmpeg.exe` / `deno.exe` 一并拷入，体积约 250MB；默认不打包

**分发前自查**：
1. `pytest tests -q` 全绿
2. `_smoke.py` 全绿
3. 双击 exe 能起、能解析、能下一个小样本
4. 确认 `dist/YT下载器/config.json` 里没有个人路径（`--bundle-deps` 与存档都会带配置）

### 16.1 存档与回退

```bat
.venv\Scripts\python.exe tools\snapshot.py            :: 用当前版本号打包
.venv\Scripts\python.exe tools\snapshot.py 备注文字    :: 带备注
```

产出 `archives/v<版本>_<时间>_<备注>.zip`（默认脱敏；`--raw` 保留原值），内含源码、文档、截图、配置和 `MANIFEST.txt`（记录版本、时间、环境版本）。回退就是解压到新目录 + 重跑 `setup.bat`。
