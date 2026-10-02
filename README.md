# Agent Video

**Let your agent watch videos.**

源码与更新：[GitHub 仓库](https://github.com/russeell/Agent-Video)。

给 Agent 一个视频链接、本地文件或视频需求，让它按问题获取文字、画面、音频、视频和信息。寻找视频时，宿主先搜索候选，Agent Video 再按需提供内容证据。所有材料保存在同一个结果目录，方便继续追问和直接交付文件。

平台解析与下载由本项目实现，不需要安装 yt-dlp、F2 或 BBDownT。FFmpeg / ffprobe 用于底层媒体处理；本地语音转录可选。

> 当前为最小可用的 v0.1 MVP。当前重点完善 YouTube、Bilibili、抖音与 TikTok，保留本地文件和已有腾讯视频适配；各项能力按实际样本标记验证范围。

## 安装

需要 Python 3.11+。完整安装包含 Python 环境和宿主 Skill 注册。以下命令在下载后的项目根目录运行，适用于 macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

将 FFmpeg 和 ffprobe 加入 PATH。媒体获取、合并、抽帧和音频提取按需使用它们；只读取平台信息或字幕通常不需要解码器。

然后按使用的宿主注册产品 Skill；两者都使用时分别执行：

```bash
# Codex
mkdir -p "$HOME/.agents/skills"
ln -s "$(pwd -P)" "$HOME/.agents/skills/agent-video"

# Claude Code
mkdir -p "$HOME/.claude/skills"
ln -s "$(pwd -P)" "$HOME/.claude/skills/agent-video"
```

链接的是完整项目目录，包含 [SKILL.md](SKILL.md)、README、脚本和 `.venv`，只复制 SKILL.md 无法运行。保留项目原位置；已有 `agent-video` 时先检查它的指向，不重复创建或覆盖其他安装。更新同一项目目录后链接继续有效；移动目录后需要重建链接，并在新位置重新创建虚拟环境。

[Codex 官方文档](https://learn.chatgpt.com/docs/build-skills)和 [Claude Code 官方文档](https://code.claude.com/docs/en/skills)说明了目录发现与自动匹配方式。安装后开始新一轮对话；若 Skill 尚未出现，重启宿主。在 Codex 的 Skill 列表或 Claude Code 的 `/agent-video` 菜单中确认它可用。

Windows 使用 PowerShell 在项目根目录创建环境，并用目录联接注册；下面以 Codex 为例，Claude Code 将 `.agents` 替换为 `.claude`：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.agents\skills\agent-video" -Target (Get-Location).Path
```

Windows 后续调用使用 `.venv\Scripts\python.exe`。其他宿主支持 Agent Skills 时，将完整项目放入它规定的 Skill 目录，并按同样方式创建环境。当前分发以源码目录为单位；仅 `pip install` 不会自动注册 Skill。本机开发 Skill `agent-video-dev` 不属于产品安装内容。

完成后可从其他工作目录检查入口；将路径替换为实际安装位置：

```bash
"$HOME/.agents/skills/agent-video/.venv/bin/python" "$HOME/.agents/skills/agent-video/scripts/watch.py" --help
```

卸载时移除宿主的 `agent-video` 目录链接即可；保留项目和结果文件。

## 使用

Skill 可用后，直接向 Agent 提问：“这个视频讲了什么”“02:10 在说什么”“提取视频文字”“下载最清晰版本”或“保存刚才的视频”，并提供链接、文件或当前视频的上下文。无需每次指定项目名称；Agent 根据请求选择材料，调用脚本后读取证据、回答或交付文件。

自动匹配由宿主 Agent 决定；未触发时可明确说“使用 Agent Video”，或在 Codex 中提及 `$agent-video`、在 Claude Code 中调用 `/agent-video`。安装 Skill 不会改变网站支持范围或宿主执行权限。

也可以说“找一个中文、10分钟以内、实际演示 FFmpeg 抽帧的视频”。Agent 使用宿主当前可用的搜索工具，按主题和已知条件初筛、去重，再按需求读少量候选。只要链接时无需观看；讲述内容可由字幕验证，实际操作演示需要看过画面，推荐会说明实际读过什么。中文标题不证明中文讲话，未知条件与无法读取的候选不会被当作已验证。搜索工具需要宿主提供，项目没有内置搜索接口；模糊画面描述的全网寻片不在范围内。

搜索范围依次为：用户指定平台 → 当前视频任务的平台 → YouTube。没有平台或上下文时，Agent 会简短说明先在 YouTube 找；结果不足或读取受限时保持当前平台，只有用户明确要求跨平台才扩大。默认搜索 YouTube 不代表所有 YouTube 视频均可读取，实际支持见下表。

找到后可以继续问“01:28 的命令是什么意思”“把那里截清楚”“保存这条视频”，Agent 会继续使用对应 manifest 和已有文件。

以下为脚本直接调用示例：

```bash
# 文字稿，附带可取得的视频信息
.venv/bin/python scripts/watch.py "/path/to/video.mp4"

# 看画面、取信息或直接拿文件
.venv/bin/python scripts/watch.py "<video-url>" --get frames --max-frames 6
.venv/bin/python scripts/watch.py "<video-url>" --get info
.venv/bin/python scripts/watch.py "<video-url>" --get video,audio

# 用返回的 manifest 路径继续补取
.venv/bin/python scripts/watch.py --evidence "/path/to/manifest.json" --get frames --start 01:20 --end 01:35
.venv/bin/python scripts/watch.py --evidence "/path/to/manifest.json" --get frames --at 01:23 --width 1600
.venv/bin/python scripts/watch.py --evidence "/path/to/manifest.json" --get video
```

`--get` 支持 `info,transcript,frames,audio,video` 的组合，默认 `transcript`。没有字幕时仅在 ASR 已配置后转录；程序不自动改成抽帧，Agent 根据问题决定下一步。完整参数见 `--help`。

默认结果保存在当前目录 `.agent-video/`。stdout 是短 JSON，包含状态、manifest 和材料路径；长文字、图片和媒体都在文件里。已有材料优先复用，只有缺少或不满足要求时才补取。

- 文字稿来自字幕或语音转录；简介、弹幕和抽样硬字幕不会冒充完整文字稿。录屏正文可由 Agent 读取画面并单独保存整理稿；项目未内置 OCR 引擎。
- 帧和文字时间相对原视频，帧同时记录请求和实际时间。
- 区间超出已知视频时长时返回越界诊断，不把短片段登记成覆盖整个请求；定点抽帧中某个时刻失败，其他成功帧仍保留。
- `--get video` 默认选择当前可取得的最高质量，与 `--quality source` 一致，不再默认限制1080p。显式 `--quality 1080p` 可限制下载档位；仅抽帧时 `auto` 仍按目标尺寸选择。最高可取得质量不代表上传原始母版。需要读小字可用 `--width 0 --quality source`。
- 平台声明档位与实际可取得格式分别记录；画面不足时提示实际尺寸，复用当前上限，不反复下载相同低清源。显式提供新的 Cookie 或更高质量要求时可重新检查。
- 先看画面再保存时，已有完整、最高质量的视频轨就只补取缺少的音轨并无损合并；再次保存直接返回完整文件。
- B 站一次取一个分 P，默认 P1；可使用 URL 的 `p` 或 `--part`，继续 evidence 时仍是同一部分。
- 用户原文件只读；结果目录由用户决定保留或删除，同一结果目录串行调用。
- 临时网络故障、下载途中断流或长度不足时最多尝试三次；HLS 只重试当前片段。完整下载后才交付，失败不覆盖已有文件。
- Cookie 仅接受显式 `--cookies` 文件，不读取浏览器凭据；不要提交凭据和运行结果。

退出码：`0` 请求完成，`2` 部分成功，`1` 无可用材料，`64` 参数错误。部分成功时先使用已有材料，并查看 `diagnostics` 的原因与下一步。

## 可选语音转录

```bash
.venv/bin/python -m pip install -e '.[asr]'
```

首次使用时明确下载一个模型，例如多语言 small（约 484 MB，保存在项目外）：

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import truststore
truststore.inject_into_ssl()
from huggingface_hub import snapshot_download
snapshot_download("Systran/faster-whisper-small", token=False,
    local_dir=Path.home() / ".cache/agent-video/models/faster-whisper-small",
    allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"])
PY
```

让调用脚本的进程使用这个模型目录：

```bash
export AGENT_VIDEO_ASR_MODEL="$HOME/.cache/agent-video/models/faster-whisper-small"
```

已准备其他 faster-whisper 模型时可直接使用它的绝对路径。默认 CPU / int8；普通读取不会下载模型，区间转录只处理目标音频段。未配置时仍可取得信息、字幕、画面和媒体。

在单独终端 `export` 不会更新已经运行的 Agent 桌面进程；可把模型目录告诉 Agent，由它在调用脚本时传入 `AGENT_VIDEO_ASR_MODEL`。可选依赖已限制 PyAV 版本，避免 faster-whisper 1.2.1 与 PyAV 19 的已知不兼容。

## 验证与限制

2026-10-03 在 macOS、Python 3.12、FFmpeg 8.0.1 验证：

| 来源 / 能力 | 实际结果 |
|---|---|
| 本地文件 | 信息、字幕选择、定点 / 区间帧、音视频导出和跨轮复用通过；双音轨切换实测正确，无声录屏的理解、定点追问、高清补帧和文件交付通过 |
| Bilibili | 匿名信息、分 P、1080p 完整音视频、定点画面与保存复用通过。本轮 BV1qt421J7MV 由新字幕接口取得35段中文自动字幕，0.44–132.68秒，不下载媒体或启动ASR；另验真实音轨下载和80–95秒中文ASR。BV1ggFseVES3 当前接口无可访问字幕，130–145秒ASR无语音，改读屏幕文字，不冒充讲话文字稿 |
| 按描述寻找视频 | 宿主网页搜索与匿名 B 站搜索 API 实测可用；按主题、时长初筛后读取 BV1qt421J7MV，抽样画面确认实际 FFmpeg 操作，完成01:28追问、1920×1080补帧与完整文件交付。同材料15秒中文ASR通过；补帧、重复保存与重复转录零网络。只要链接的 Python 教程请求只取得信息；去重、未知字段、筛选后无匹配及 YouTube 无法读取画面分别检查 |
| 搜索范围 | 无平台/上下文时默认 YouTube，实际核实 Python 候选135秒与619秒，按时长筛选、仅交付链接；B 站上下文沿用B站完成实操验证与复用，明确指定 YouTube 时覆盖B站上下文。结果不足或读取失败没有自动跨平台；明确允许跨平台时才比较已有两站候选 |
| 腾讯视频（实验） | [公开短视频 q326831cny0](https://v.qq.com/x/page/q326831cny0.html) 匿名完整下载和抽帧通过：1280×720、215.958秒、H.264 + AAC；不推广到所有腾讯内容 |
| TikTok（实验） | 两个公开样本实际信息、完整视频与音频通过。Hank Green 样本取得12段英文字幕、576×1024 H.264 + AAC双声道、21.268秒，全片解码通过；另一约6秒样本平台未返回字幕，真实small ASR和画面读取通过。定点追问、源尺寸补帧、保存及语言选择复用通过；少量样本不代表全站可用 |
| YouTube（实验） | 自研网页信息与原生播放器请求，字幕、直链和非加密点播 HLS。hkJFPUKTUwk 取得1659段中文字幕；py5B55ywvh0 Shorts 完整下载1080×1920 VP9 + AAC双声道、144.056秒，全片解码通过。另验英文人工与自动字幕；文字追问、高清补帧和重复保存复用通过 |
| Douyin（实验） | 尚未完成内容或文件验收。当前匿名样本网页HTTP200但返回JavaScript签名挑战，详情API HTTP403；未取得可用作品数据、音视频或字幕，ASR路径因无音轨受阻。既有嵌入数据解析保留，不声称下载可用 |
| 本地 ASR（可选） | small / CPU / int8 实测英文真人语音、中文合成语音及15秒中文真人教程口播，区间时间和文字稿复用通过；静音音轨返回 no_speech，无音轨返回 no_audio，仍交付其他材料。中文有错字；真人样本仅核对语言与主题，未做准确率评估；ASR估计时间限制在实际处理音频与请求区间内，平台字幕时间保持原值 |

线上入口只使用明确的专用平台适配：YouTube、Bilibili、抖音、TikTok，以及保留的腾讯视频。未知网站、媒体直链与普通 HTML 网页返回 `unsupported_source`，不请求网页或尝试通用解析；可将已有媒体文件作为本地输入。HTTP 下载、非加密 VOD HLS 的 TS / fMP4 传输和音视频合并供平台共享使用，协议支持不等于新增网站支持。复杂 HLS 字节范围 / discontinuity / 加密 / 直播、MPD 和跨调用断点续传未支持；YouTube 的外置音轨选择由其专用适配完成。腾讯只接单视频 `/x/page/VID.html` 或 `/x/cover/CID/VID.html`，不遍历整剧集，不补齐试看，不处理 DRM。以上是少量样本验证，不能推断平台所有链接均可用。

不处理直播、DRM、账号批量、图集、评论正文、自动翻译、说话人分离或内置全视频 OCR。平台接口变化、地区、网络和认证条件可能影响获取。遇到需要尚未实现的平台挑战时返回具体限制，不暗中调用外部下载项目。

YouTube 的信息请求只读取网页；文字或媒体请求共享一次 visionOS 播放器请求，字幕成功时不下载整段视频。媒体选择包含 HLS 高清变体，外置音轨与画面分别获取，再无损合并，优先明确标记的原声。下载请求不启动 ASR。当前未实现需要 JavaScript 签名、PO token 或登录验证的其他获取路径；公开视频也可能受地区或访问条件限制，不保证每条链接可用。

多语言字幕不一定能证明原语音语言，平台默认字幕也可能是翻译。原语言未知时诊断会列出可用语言，可用 `--language zh` 等明确选择，并在追问中沿用。文字时间来自平台字幕；自动字幕可能有错字或超出页面标称时长的结束时间。hkJFPUKTUwk 的中文字幕到70:08.137结束，视频标称71:29，末尾约81秒没有字幕，不能视为全部声音的完整转写。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

测试按职责放在二级目录：

```text
tests/
├── platforms/  # 各专用平台解析与请求
├── shared/     # HTTP、HLS、材料选择与平台路由
├── media/      # 字幕、音轨、帧和区间处理
└── flows/      # 入口、组合请求和材料复用
```

默认回归使用临时合成媒体与本地 HTTP 服务；上面的 discover 命令递归运行这些目录。需 FFmpeg / ffprobe 的测试在缺失时明确跳过；跳过代表未验证。线上获取、真实 ASR 和宿主完整流程单独验证，不在每次回归中下载视频或大模型。

干净安装已在 macOS、Python 3.14 的全新环境、含空格源码路径及不同工作目录下验证；源码包和 wheel 构建通过，开发资料与运行材料不在包内。产品仍以完整源码 Skill 目录分发，优先发布源码归档；wheel 本身不包含可注册的 Skill 目录。Windows / Linux 尚未完成实测。

## 参考

设计参考 [yt-dlp](https://github.com/yt-dlp/yt-dlp)、[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)、[claude-video](https://github.com/bradautomates/claude-video)、[claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video)、[BBDownT](https://github.com/LOVAHE/BBDownT) 和 [F2](https://github.com/Johnserf-Seed/f2) 的职责拆分与材料获取思路；[Video-Browser](https://github.com/chrisx599/Video-Browser) 的候选筛选与渐进阅读仅参考思路，未移植代码。以上不是运行依赖。源码移植或改编涉及的许可与署名随相应文件保留。
