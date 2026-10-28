# Windows local media setup for ViMax

This setup enables the **existing** local CPU workflow (Piper narration, SRT/VTT subtitles, FFmpeg MP4 rendering, thumbnail output, visual scene-cut estimates and bounded scene-clip export). It does not install or enable the separate short-video-maker, OpenMontage, ComfyUI, Kokoro, faster-whisper, Google OAuth or any autonomous publisher. Those need separate integration, model/credential review and tests.

## Requirements

- Windows 10/11 x64, PowerShell 7 recommended (Windows PowerShell 5.1 also works for this script).
- Python 3.11 x64; Node.js 22+; Git; FFmpeg recommended.
- 8 GB RAM can run the existing basic CPU slideshow/Piper pipeline; keep other apps closed for longer jobs. Do not expect fast generative video or large local LLMs on an integrated GPU.
- A Piper voice model `.onnx` and matching `.onnx.json` configuration obtained from a source whose license you accept. This installer deliberately does not download a voice/model or execute a third-party repository.

## Install

From a trusted local clone of this ViMax overlay, open PowerShell in the repository root and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-windows-media.ps1
```

The script creates `skills\.venv`, installs only the pinned packages in `skills\requirements.txt`, and verifies Python imports and FFmpeg availability. It does not modify the hosted deployment, upload media, configure OAuth, or set API keys.

If FFmpeg is already installed but not on PATH, set the full path before running the local companion:

```powershell
$env:VIMAX_FFMPEG = 'C:\\path\\to\\ffmpeg.exe'
```

Configure the voice by setting `VIMAX_PIPER_MODEL` to the absolute path of the voice's `.onnx` file and `VIMAX_PIPER_LANGUAGE` to the matching language tag. The corresponding `.onnx.json` must sit next to the model. Keep the model on your machine and do not commit it to Git.

## What to test

```powershell
python -c "import fastapi, pydantic, scenedetect, cv2; print('local media imports OK')"
ffmpeg -version
```

Then follow the root README's local companion setup for the pinned ViMax checkout and start the companion only on loopback. Do not expose its ports to a LAN or the public Internet.

## Remaining items that require separate work

- Pexels video download and stock-footage assembly: PEXELS_API_KEY, rights/attribution handling, download limits, and a new tested renderer adapter.
- Faster Whisper: a vetted model and CPU test with usable transcription quality; prior isolated sample was unusable.
- Kokoro: model/voice weights, language support and memory/performance test; Piper remains the default.
- Short-video-maker, OpenMontage, Shotcraft, ComfyUI: separate runtimes and dependencies; review licenses, asset rights and security before enabling.
- YouTube marketing MCP / Google API client: use ViMax's existing owner-isolated OAuth path rather than copying third-party plaintext token storage or adding duplicate broad write scopes.
- Search/research agent: license uncertainty must be resolved and real retrieved sources must be cited; demo fallback data must never be represented as real research.
- Desktop creator daemon: separate Windows process, permission model and explicit approval gates; not a hosted web feature.
- No channel publishing, public posting or destructive local action should run without a clear user approval step.
