# Video Generator

[English](README.md) · [한국어](README.ko.md) · [日本語](README.ja.md) · **简体中文** · [Español](README.es.md)

给出一个主题,AI 智能体就会查资料、写脚本、配音,并做出 3D 画面,完成一部讲解视频。这个文件夹就是为此准备的工作目录。

人要做的只有**选择、阅读、写下要改的地方、批准**。不需要自己写代码,也不需要记命令。每到重要阶段都会打开一个网页,在那里点按钮或写意见即可。

> **关于语言。** 这套工具以韩语为主:主旁白是韩语,网页界面和给智能体的说明文件也都是用韩语写的。下文中的按钮名称按界面原样列出,并附上中文释义。

![成品视频的画面](readme/sample.png)

*用这个文件夹制作的《土星为什么有环》(2 分 38 秒)中的画面。*

<sub>图中使用的 3D 模型(经修改后使用):["Saturn"](https://sketchfab.com/3d-models/saturn-c09a1970148c43ad99db134a9d6d00b5) by Nestaeric, ["Asteroids Pack (rocky version)"](https://sketchfab.com/3d-models/asteroids-pack-rocky-version-adde1ecf129e4509be8af61b84bafa85) by SebastianSosnowski, ["Wandering Asteroids Of Andromeda"](https://sketchfab.com/3d-models/wandering-asteroids-of-andromeda-6a8e84e0fdea43628b8b3ab85b130281) by ARCTIC WOLVES™, ["Asteroid low poly"](https://sketchfab.com/3d-models/asteroid-low-poly-9a43ef48a70647188576ccb5987b7e64) by pasquill。均为 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。</sub>

## 它能做出什么

- 1~3 分钟的韩语讲解视频(横屏、竖屏、正方形任选)
- 韩语旁白和背景音乐
- 英语、日语、中文、西班牙语的配音和字幕(只选需要的语言)

画面不是生成式视频,而是用 Blender 计算并绘制的 3D 场景。因此,天体的位置、力的方向这类必须准确的内容,不会在不同场景之间变来变去。

## 需要准备的东西

| 需要什么 | 为什么需要 |
|---|---|
| Apple silicon Mac(M1 及以上) | 生成语音的模型只能在这种环境下运行 |
| AI 编程智能体(Claude Code、Codex 等) | 负责查资料、写脚本、设计画面 |
| Python 3.13 | 工具本体 |
| FFmpeg | 合并视频和音频 |
| Blender 5.2 | 绘制 3D 画面。安装到 `/Applications/Blender.app` |
| espeak-ng | 只在生成西班牙语语音时需要 |

## 安装

在终端中进入这个文件夹,运行一次下面的命令。如果不太清楚,也可以直接对智能体说"按照 README 帮我安装"。

```bash
python3 -m pip install -r requirements.txt
brew install ffmpeg espeak-ng
```

Blender 从 [blender.org](https://www.blender.org/download/) 下载,放进"应用程序"文件夹。

第一次生成语音时会自动下载语音模型。只有这时需要联网,要花几分钟。之后不需要网络,也不需要 API 密钥,全部在这台电脑上运行。

## 如何开始

用智能体打开这个文件夹,然后这样说:

> 按照视频生成流程帮我做一个视频。主题是"土星为什么有环"。

如果有脚本草稿,可以一起贴进去。也可以给一份 PDF,让它按其中的内容来做。如果有想用的 3D 模型,放进 `assets/` 文件夹并告诉智能体。

智能体会按照这个文件夹里 [AGENTS.md](AGENTS.md) 写明的顺序进行。人只在下面六个阶段参与。

## 整体流程

| 阶段 | 智能体做什么 | 人做什么 |
|---|---|---|
| 1. 设置 | 打开设置页面 | 选择节奏、声音、音乐、输出,然后点 **저장 후 닫기**(保存并关闭) |
| 2. 脚本 | 查资料、写出脚本草稿并显示在网页上 | 阅读后写意见,或点 **대본 승인**(批准脚本) |
| 3. 语音 | 用批准的脚本生成语音 | 等待 |
| 4. 预览 | 设计画面,绘制代表性画面并显示在网页上 | 查看后写意见,或点 **프리뷰 승인**(批准预览) |
| 5. 初稿 | 用低画质制作完整视频 | 播放查看,然后在对话中回复 `초본승인`(批准初稿) |
| 6. 成品 | 用原画质重新制作 | 等待 |

一共批准三次:脚本、预览、初稿。前一个阶段没有批准,下一个阶段就不会开始。这是为了避免把耗时很长的工作花在错误的脚本或画面上。

### 阶段 1 — 选择设置

![设置页面](readme/settings.png)

只需要看左侧列表里的四组。

- **영상 템포**(视频节奏):沉稳讲解 / 普通视频 / 短视频节奏。说话的速度和画面切换的间隔会一起确定。
- **목소리**(声音):选择整体的说话语气。展开 **목소리 미리 듣기**(试听声音)可以在保存前先听一听。
- **배경음악**(背景音乐):从 `bgmusic/` 文件夹里的音乐中选择,并设定音量。留空则不加音乐。
- **출력**(输出):确定视频规格、附加语言,以及字幕是压进视频里还是单独输出。

选好之后,点右下角的 **저장 후 닫기**(保存并关闭)。窗口关闭后,智能体会进入下一个阶段。上一次的设置会保留下来,如果没有要改的,直接关闭即可。

**고급 옵션**(高级选项)是折叠起来的,平时不需要打开。各项的说明见 [settings.md](settings.md)。

### 阶段 2 — 审阅脚本

![脚本审阅页面](readme/story.png)

- 在**左侧列表**中选择一个场景,中间会显示该场景的脚本和要在画面上展示的内容。
- 在 **이 장면의 수정 사항**(本场景的修改事项)里写下要改的地方。用平常的话写就可以,比如"这句话和上一个场景重复了""讲得再通俗一点"。
- **영상 아이디어**(画面创意)是可选的。有想要的画面或表现方式就写,没有就留空。
- 对整部视频的意见,展开最下方的 **영상 전체에 대한 수정 의견**(对整部视频的修改意见)来写。

写完后点右上角的按钮。

- **수정 의견 저장**(保存修改意见):有需要修改的地方时使用。保存后请告诉智能体"我留了修改意见"。网页不会自动通知智能体。
- **대본 승인**(批准脚本):这样就可以时使用。批准后页面会关闭,并开始制作语音。

只保存而不点批准,不会进入下一个阶段。智能体修改脚本后,刷新同一个页面,重新阅读并批准。

### 阶段 3 — 生成语音

由智能体自行完成。以二十个场景计,需要几分钟。

语音模型偶尔会把某句话读得太慢而无法通过检查。这时智能体会建议去掉逗号或稍微改一下句子。因为这等于改动了脚本,所以会重新请你批准。

### 阶段 4 — 审阅预览

![预览审阅页面](readme/preview.png)

在绘制整部视频之前,会先给每个场景展示几张代表性画面。在这一步修改是最快的。

- 点击**大图下方的小图**,可以按时间顺序查看该场景内的画面。用 **이미지 크게 보기**(放大图片)放大查看。
- 用 **나레이션 대본**(旁白脚本)下方的播放按钮,可以听这个场景的语音。
- **영상대본**(画面脚本)是用文字写出这段时间画面上发生了什么。
- 在 **이 장면의 수정 사항**(本场景的修改事项)里写下对画面的意见。照看到的写就行,比如"箭头太长了""不需要卫星的场景里也出现了卫星"。

右上角有三个按钮。

- **수정 의견 저장**(保存修改意见):只保存意见。
- **수정 반영 후 프리뷰 다시 만들기**(按修改意见重新生成预览):保存意见并请求重新制作。点击后页面会关闭。如果智能体没有马上继续,请告诉它"我提交了预览意见"。
- **프리뷰 승인**(批准预览):这样就可以时使用。批准后页面会关闭。只要还写着意见,这个按钮就点不了。

智能体修改之后,会用新的预览重新打开审阅页面。反复进行,直到满意为止。

预览图画得很小(长边 384 像素)。这是为了快速确认,所以细节可能会显得模糊。

### 阶段 5 — 确认初稿

批准预览后,智能体会用低画质制作完整视频,并告诉你 `final-draft.mp4` 文件的位置。里面带有语音和音乐。请自己播放,检查动作不自然和发音奇怪的地方。智能体没办法播放视频,也听不到声音。

- 如果有要改的地方,在对话中说明。只改画面的话,语音不会重新生成。
- 如果没问题,在对话中回复 `초본승인`(批准初稿)。

### 阶段 6 — 成品

用原画质重新绘制。智能体会给出一个显示进度的网页地址,完成后视频会出现在那个页面上。

这需要不少时间。土星那部视频(2 分 38 秒,1920×1080),初稿用了大约 17 分钟,成品用了大约 2 小时 15 分钟。让电脑开着,去做别的事情就好。

## 成果在哪里

每部视频都会生成一个 `runs/日期-主题/` 文件夹。

| 文件 | 内容 |
|---|---|
| `final.mp4` | 成品视频(韩语语音、背景音乐) |
| `final-en.m4a` 等 | 各语言的音轨。根据设置,也可能输出为各语言的视频 `final-en.mp4` |
| `subtitles/` | 各语言的字幕文件(`.srt`、`.ass`) |
| `video-only.mp4` | 没有声音的视频 |
| `final-draft.mp4` | 阶段 5 中确认过的初稿 |
| `story-review.md` | 脚本和出处 |
| `research.md` | 调研内容,以及画面中夸张或省略的部分 |

`runs/` 文件夹不会提交到 git。需要的视频请另外保存。

## 值得了解的事

- **意见越具体越好。** 比起"看着怪怪的","第 9 个场景的箭头没有对准卫星的中心"一次就能改好。写上场景编号会更好。
- **"继续吧"不算批准。** 只有网页上的批准按钮,或对话中明确的批准("대본 승인""프리뷰 승인""초본승인")才算数。
- **改了脚本就要重新生成语音。** 只改画面的话,语音原样沿用。所以最好在阶段 2 把脚本充分打磨好。
- **第一次做的主题会比较慢。** 智能体需要针对这个主题重新编写绘制画面的代码。如果和已经做过的主题相近,就会快得多。
- **外部的 3D 模型和音乐是有使用条件的。** 放进 `assets/` 的模型,其来源和许可证要记录在 `assets/CREDITS.md` 里。公开视频时,大多数模型都要求署名,也有一些仅限非商业用途或禁止修改。
- **翻译由智能体完成。** 没有母语者校对。为了配合每个场景的时长,有些句子可能比韩语原文更短。

## 文件夹结构

| 文件夹/文件 | 内容 | Git |
|---|---|---|
| `video_harness/` | 工具本体(语音、画面、检查、网页界面) | 提交 |
| `settings.json` | 上一次选择的设置 | 提交 |
| `AGENTS.md` | 智能体遵循的顺序 | 提交 |
| `readme/` | 本文档的图片 | 提交 |
| `assets/` | 3D 模型及其来源记录 | 忽略 |
| `bgmusic/` | 背景音乐。只提交 `README.md` | 忽略 |
| `runs/` | 每部视频的工作文件夹和成果 | 忽略 |

## 更多细节(面向开发者)

这些是智能体在内部使用的命令,几乎不需要自己运行。

```bash
python -m video_harness settings-ui                 # 设置页面
python -m video_harness story-ui runs/<run>         # 脚本审阅页面
python -m video_harness voice runs/<run>/script.json
python -m video_harness preview runs/<run>          # 检查计划 → 渲染代表性画面 → 预览页面
python -m video_harness preview-ui runs/<run>       # 只重新打开预览页面
python -m video_harness produce runs/<run> --quality draft
python -m video_harness produce runs/<run> --quality final
python -m video_harness validate runs/<run>
```

以下文档是用韩语写的。

- 完整的工作顺序和批准规则:[video_harness/agent/WORKFLOW.md](video_harness/agent/WORKFLOW.md)
- 脚本和画面的基本表现准则:[video_harness/agent/DIRECTION.md](video_harness/agent/DIRECTION.md)
- 工具的结构:[video_harness/docs/architecture.md](video_harness/docs/architecture.md)
- 如何添加 Blender 场景:[video_harness/docs/blender-rendering.md](video_harness/docs/blender-rendering.md)
- 问题链和画面连续性检查:[video_harness/docs/creative-gates.md](video_harness/docs/creative-gates.md)
- 场景转换原则:[video_harness/docs/continuous-transitions.md](video_harness/docs/continuous-transitions.md)
- 声音表演和停顿:[video_harness/docs/voice-acting.md](video_harness/docs/voice-acting.md)

测试不需要 API 密钥,也不需要下载模型就能运行。

```bash
python -m pytest -q -p no:cacheprovider
```

只有在使用 Three.js 渲染器,或运行网页界面的浏览器测试时,才需要下面的额外安装。只用 Blender 制作则不需要。

```bash
cd video_harness/science_renderer
npm ci
npx playwright install chromium --only-shell
```

## 许可证

[MIT](LICENSE)。适用于本仓库中的代码。你自行添加或下载的 3D 模型、音乐和语音模型,各自适用它们原有的许可证。
