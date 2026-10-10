# Video Generator

New video-specific code, validators and tests belong in `runs/<run>/scripts/`, assets in `assets/`, and disposable outputs in `.render-cache/`. Declare dependencies in `render-source.json`; ordinary production requires no shared-code edit or Git commit. New settings v7 default the Blender EEVEE Shadow Pool to 2048 MB; older run snapshots stay unchanged.

[Run render sources](video_harness/docs/run-render-sources.md)

**English** · [한국어](README.ko.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md)

Give it a topic, and an AI agent researches it, writes the script, adds the voice, and builds the 3D visuals to finish one explainer video. This folder is the workspace for that.

All a person does is **choose, read, note what to fix, and approve**. You don't need to write code or memorize commands. At each important step a web page opens, and you press a button or type your feedback there.

> **Language note.** The harness is Korean-first: the primary narration is Korean, and the web screens and the agent's instruction files are written in Korean. Button names below are shown as they appear on screen, with an English gloss.

![Scenes from a finished video](readme/sample.png)

*Scenes from "Why Saturn Has Rings" (2 min 38 s), made with this folder.*

<sub>3D models in the image, used with modifications: ["Saturn"](https://sketchfab.com/3d-models/saturn-c09a1970148c43ad99db134a9d6d00b5) by Nestaeric, ["Asteroids Pack (rocky version)"](https://sketchfab.com/3d-models/asteroids-pack-rocky-version-adde1ecf129e4509be8af61b84bafa85) by SebastianSosnowski, ["Wandering Asteroids Of Andromeda"](https://sketchfab.com/3d-models/wandering-asteroids-of-andromeda-6a8e84e0fdea43628b8b3ab85b130281) by ARCTIC WOLVES™, ["Asteroid low poly"](https://sketchfab.com/3d-models/asteroid-low-poly-9a43ef48a70647188576ccb5987b7e64) by pasquill. All [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).</sub>

## What it makes

- A 1–3 minute Korean explainer video (landscape, portrait, or square)
- Korean narration and background music
- English, Japanese, Chinese, and Spanish voice and subtitles (only the languages you choose)

The visuals are not generative video. They are 3D scenes computed and drawn in Blender, so things that must be accurate — the position of a planet, the direction of a force — stay consistent from scene to scene.

## Requirements

| What you need | Why |
|---|---|
| Apple silicon Mac (M1 or later) | The voice models only run in this environment |
| An AI coding agent (Claude Code, Codex, etc.) | Does the research, script, and visual design |
| Python 3.13 | The harness itself |
| FFmpeg | Combines video and audio |
| Blender 5.2 | Draws the 3D scenes. Install it at `/Applications/Blender.app` |
| espeak-ng | Only needed for Spanish voice |

## Installation

In a terminal, go to this folder and run the following once. If you're unsure, you can tell the agent "install this following the README".

```bash
python3 -m pip install -r requirements.txt
brew install ffmpeg espeak-ng
```

Download Blender from [blender.org](https://www.blender.org/download/) and put it in the Applications folder.

The voice models are downloaded automatically the first time you generate a voice. That is the only time an internet connection is needed, and it takes a few minutes. After that everything runs on this computer, with no internet connection or API key.

## Getting started

Open this folder with your agent and say something like:

> Make a video following the video generation harness. The topic is "Why Saturn Has Rings".

If you have a draft script, paste it in as well. You can also hand over a PDF and ask for a video based on it. If there is a 3D model you want to use, put it in the `assets/` folder and tell the agent.

The agent follows the order written in [AGENTS.md](AGENTS.md). A person steps in only at the six stages below.

## The whole flow

| Stage | What the agent does | What you do |
|---|---|---|
| 1. Settings | Opens the settings page | Choose tempo, voice, music, and output, then **저장 후 닫기** (Save and close) |
| 2. Script | Researches, drafts the script, and shows it on the web | Read it, then leave feedback or press **대본 승인** (Approve script) |
| 3. Voice | Generates the voice from the approved script | Wait |
| 4. Preview | Designs the visuals, renders key frames, and shows them on the web | Look, then leave feedback or press **프리뷰 승인** (Approve preview) |
| 5. Draft | Renders the full video at low resolution | Play it and reply `초본승인` ("draft approved") in the chat |
| 6. Final | Renders again at full resolution | Wait |

There are three approvals: script, preview, and draft. The next stage does not start until the previous one is approved. This keeps long-running work from being spent on the wrong script or visuals.

### Stage 1 — Choose settings

![Settings page](readme/settings.png)

You only need to look at the four groups in the list on the left.

- **영상 템포** (Video tempo): calm explanation / regular video / shorts tempo. This sets both the speaking speed and how often the picture changes.
- **목소리** (Voice): choose the overall tone. Expand **목소리 미리 듣기** (Voice preview) to listen before saving.
- **배경음악** (Background music): pick from the music in the `bgmusic/` folder and set the volume. Leave it empty for no music.
- **출력** (Output): choose the video format, extra languages, and whether subtitles are burned into the video or delivered separately.

When you're done, press **저장 후 닫기** (Save and close) at the bottom right. When the window closes, the agent moves on. Your previous settings are kept, so if nothing needs changing you can close it right away.

**고급 옵션** (Advanced options) is collapsed. You normally don't need to open it. Each item is explained in [settings.md](settings.md).

### Stage 2 — Review the script

![Script review page](readme/story.png)

- Pick a scene in the **list on the left** and its script and planned visuals appear in the middle.
- Write what to fix under **이 장면의 수정 사항** (Changes for this scene). Plain language is fine: "this sentence repeats the previous scene", "explain this more simply".
- **영상 아이디어** (Video ideas) is optional. Write down any visuals or direction you want, or leave it empty.
- For feedback on the whole video, expand **영상 전체에 대한 수정 의견** (Feedback on the whole video) at the bottom.

When you're done, press a button at the top right.

- **수정 의견 저장** (Save feedback): when something needs fixing. After saving, tell the agent "I left feedback". The web page does not notify the agent by itself.
- **대본 승인** (Approve script): when it's good as is. Approving closes the page and starts voice generation.

Saving without approving does not move things forward. When the agent revises the script, refresh the same page, read it again, and approve.

### Stage 3 — Generate the voice

The agent handles this by itself. It takes a few minutes for about twenty scenes.

Occasionally the voice model reads a particular sentence too slowly and it fails the check. The agent will then suggest removing a comma or adjusting the sentence slightly. Because that changes the script, it asks for approval again.

### Stage 4 — Review the preview

![Preview review page](readme/preview.png)

Before the whole video is rendered, you first see a few key frames for each scene. Fixing things here is the fastest.

- Click the **small images under the large one** to step through that scene in time order. Use **이미지 크게 보기** (Enlarge image) to zoom in.
- Use the play button under **나레이션 대본** (Narration script) to hear that scene's voice.
- **영상대본** (Visual script) describes in words what happens on screen at that time.
- Write feedback about the visuals under **이 장면의 수정 사항** (Changes for this scene). Describe what you see: "the arrow is too long", "the moon shows up in scenes that don't need it".

There are three buttons at the top right.

- **수정 의견 저장** (Save feedback): saves your feedback only.
- **수정 반영 후 프리뷰 다시 만들기** (Apply changes and rebuild preview): saves your feedback and requests a new preview. Pressing it closes the page. If the agent doesn't pick it up right away, tell it "I submitted preview feedback".
- **프리뷰 승인** (Approve preview): when it's good as is. Approving closes the page. It can't be pressed while feedback is written.

After the agent makes changes, the review page opens again with the new preview. Repeat until you're happy.

Preview images are rendered small (384 pixels on the long side). They are for quick checking, so details may look blurry.

### Stage 5 — Check the draft

Once you approve the preview, the agent renders the full video at low resolution and tells you where `final-draft.mp4` is. It includes voice and music. Play it yourself and check for awkward motion and odd pronunciation. The agent cannot play the video or listen to the audio.

- If something needs fixing, say so in the chat. If only the visuals change, the voice is not regenerated.
- If it's fine, reply `초본승인` ("draft approved") in the chat.

### Stage 6 — Final video

The video is rendered again at full resolution. The agent gives you the address of a web page that shows progress, and the video appears on that page when it finishes.

This takes a while. For the Saturn video (2 min 38 s, 1920×1080), the draft took about 17 minutes and the final about 2 hours 15 minutes. Leave the computer on and do something else.

## Where the results are

Each video gets its own `runs/<date>-<topic>/` folder.

| File | Contents |
|---|---|
| `final.mp4` | Finished video (Korean voice, background music) |
| `final-<lang>.mp4` | Complete videos with narration and music in Korean, English, Japanese, Chinese and Spanish; subtitles are optional. Separate audio tracks are retained only for older runs |
| `subtitles/` | Per-language subtitle files (`.srt`, `.ass`) |
| `video-only.mp4` | Video without sound |
| `final-draft.mp4` | The draft you checked in stage 5 |
| `story-review.md` | Script and sources |
| `research.md` | Research notes, and what the visuals exaggerate or leave out |

The `runs/` folder is not committed to git. Move any video you need somewhere else.

## Good to know

- **Specific feedback works best.** "The arrow in scene 9 doesn't line up with the center of the moon" gets fixed in one pass; "it looks off" does not. Including the scene number helps even more.
- **"Go ahead" is not an approval.** Approval only counts through the approve button on the web or a clear approval in the chat ("대본 승인", "프리뷰 승인", "초본승인").
- **Changing the script regenerates the voice.** Changing only the visuals keeps the voice as is. So it pays to polish the script thoroughly in stage 2.
- **A topic you haven't done before takes longer.** The agent has to write new scene-drawing code for the topic. If it resembles a topic you've already made, it goes much faster.
- **External 3D models and music come with conditions.** Record the source and license of each model you put in `assets/` in `assets/CREDITS.md`. Most models require attribution when you publish a video, and some are non-commercial only or forbid modification.
- **Translations are written by the agent.** There is no native-speaker review. Some sentences may be shorter than the Korean to fit the length of each scene.

## Folder layout

| Folder / file | Contents | Git |
|---|---|---|
| `video_harness/` | The harness itself (voice, visuals, checks, web pages) | Committed |
| `settings.json` | The settings you chose last time | Committed |
| `AGENTS.md` | The order the agent follows | Committed |
| `readme/` | Images for this document | Committed |
| `assets/` | 3D models and your notes on their sources | Ignored |
| `bgmusic/` | Background music. Only `README.md` is committed | Ignored |
| `runs/` | Per-video working folders and results | Ignored |

## More detail (for developers)

These are the commands the agent uses internally. You will rarely need to run them yourself.

```bash
python -m video_harness settings-ui                 # settings page
python -m video_harness story-ui runs/<run>         # script review page
python -m video_harness voice runs/<run>/script.json
python -m video_harness preview runs/<run>          # plan checks → key-frame render → preview page
python -m video_harness preview-ui runs/<run>       # reopen the preview page only
python -m video_harness produce runs/<run> --quality draft
python -m video_harness produce runs/<run> --quality final
python -m video_harness validate runs/<run>
```

After the final video passes its checks, the same command also makes one vertical short per language (`shorts/shorts-<lang>.mp4`, only the scenes the script marks for the short, at most 3 minutes) and `upload.md`: copy-ready titles and descriptions per language with the 3D model, music and voice credits. The finished-video page shows them with copy buttons.

The documents below are written in Korean.

- Full workflow and approval rules: [video_harness/agent/WORKFLOW.md](video_harness/agent/WORKFLOW.md)
- Default direction for scripts and visuals: [video_harness/agent/DIRECTION.md](video_harness/agent/DIRECTION.md)
- Harness architecture: [video_harness/docs/architecture.md](video_harness/docs/architecture.md)
- How to add a Blender scene: [video_harness/docs/blender-rendering.md](video_harness/docs/blender-rendering.md)
- Question-chain and visual continuity checks: [video_harness/docs/creative-gates.md](video_harness/docs/creative-gates.md)
- Scene transition principles: [video_harness/docs/continuous-transitions.md](video_harness/docs/continuous-transitions.md)
- Voice acting and pauses: [video_harness/docs/voice-acting.md](video_harness/docs/voice-acting.md)

The tests run without an API key or model downloads.

```bash
python -m pytest -q -p no:cacheprovider
```

The extra installation below is only needed if you use the Three.js renderer or run the browser tests for the web pages. It isn't needed if you render with Blender only.

```bash
cd video_harness/science_renderer
npm ci
npx playwright install chromium --only-shell
```

## License

[MIT](LICENSE). This covers the code in this repository. 3D models, music, and voice models that you add or download keep their own licenses.
