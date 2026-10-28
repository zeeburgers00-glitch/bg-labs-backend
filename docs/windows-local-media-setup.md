# Windows local media setup for ViMax

This setup enables the existing local CPU workflow: Piper narration, SRT/VTT subtitles, FFmpeg MP4 rendering, thumbnail output, visual scene-cut estimates and bounded scene-clip export. It does not install the separate short-video-maker, OpenMontage, ComfyUI, Kokoro, faster-whisper, Google OAuth or an autonomous publisher.

## Requirements

- Windows 10/11 x64; PowerShell; Python 3.11 x64; Node.js 22+; Git.
- 8 GB RAM can run the existing basic CPU slideshow/Piper workflow, though longer renders may be slow. Do not expect fast generative video or large local LLMs on an integrated GPU.
- A Piper voice model `.onnx` and matching `.onnx.json` obtained from a source whose license you accept. The installer deliberately does not download voice/model files or execute third-party repositories.

## Install

From the repository root, run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-windows-media.ps1
```

The script creates `skills\.venv`, installs the pinned packages in `skills\requirements.txt`, and verifies imports and FFmpeg. It does not change the hosted deployment, upload media, configure OAuth or set API keys.

If FFmpeg is not on PATH but you have a local executable, set `$env:VIMAX_FFMPEG` to its full path. Configure Piper using `VIMAX_PIPER_MODEL` (absolute path to the .onnx file) and `VIMAX_PIPER_LANGUAGE` (the voice's language tag); the matching JSON must sit beside the model. Do not commit model files.

## Verify

```powershell
skills\.venv\Scripts\python.exe -c "import fastapi, pydantic, scenedetect, cv2, numpy; print('local media imports OK')"
ffmpeg -version
```

Then follow the root README's local companion instructions for the pinned ViMax checkout. Keep all local services bound to loopback; never expose their ports to a LAN or public Internet.

## Still requires separate implementation/setup

- Pexels stock-footage download/assembly: `PEXELS_API_KEY`, download limits, asset attribution/rights and a tested renderer adapter.
- Faster Whisper: vetted model and usable transcription-quality tests; prior isolated sample was unusable.
- Kokoro: model/voice weights and memory/language tests; Piper remains the default.
- Short-video-maker, OpenMontage, Shotcraft and ComfyUI: separate runtimes, model/assets, license and security review.
- YouTube marketing MCP / Google API client: preserve ViMax's owner-isolated OAuth path; do not copy third-party plaintext token storage or broad write scopes.
- Search/research agent: resolve license uncertainty and require real sources/citations; never present demo fallback data as research.
- Desktop creator daemon: separate Windows process, permission model and explicit approval gates.
- Publishing, public posting and destructive file operations must require clear user approval.
