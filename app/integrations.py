"""Registry of repositories requested for BG Labs and their real deployment mode."""
from __future__ import annotations

# status: active = executable in this deploy; adapter = API wiring exists and needs key/URL;
# ported = useful pure-Python logic incorporated; reference = docs/examples used, not executed.
# Vercel cannot run GPU repos or desktop/browser binaries, so those are adapters to a GPU worker.
RAW = [
# YouTube automation / skills
("youtube-automation-agent","https://github.com/darkzOGx/youtube-automation-agent","youtube","reference","Agent patterns mapped to BG Labs agents and YouTube APIs"),
("AI-Content-Studio","https://github.com/naqashafzal/AI-Content-Studio","youtube","reference","Content studio UX/reference"),
("tube-assistant","https://github.com/metiutek/tube-assistant","youtube","reference","Analytics and assistant patterns"),
("gemini-youtube-automation","https://github.com/ChaitanyaEswarRajeshJakki/gemini-youtube-automation","youtube","reference","Gemini YouTube workflow reference"),
("youtube-skills-zero","https://github.com/ZeroPointRepo/youtube-skills","skills","ported","Skills inspected and exposed through Skills Hub"),
("youtube-skills-artem","https://github.com/artemchuikin/youtube-skills","skills","reference","Additional YouTube skill recipes"),
("youtube-agent-skill","https://github.com/Jakeschincariol/chatgpt-youtube-agent-skill","skills","active","11 skills, 21 hooks and six tools installed"),
("skillforge","https://github.com/koren-source/skillforge","skills","reference","Skill authoring patterns"),
("youtube-api-samples","https://github.com/youtube/api-samples","youtube","active","Official OAuth, channels, comments, analytics and resumable upload patterns"),
# Browser / research
("BrowserSkill","https://github.com/Tencent/BrowserSkill","browser","ported","Vercel-safe snapshot/search/research layer; desktop browser requires worker"),
("browsing-skills","https://github.com/browsing-skills/browsing-skills","browser","ported","Research skill patterns"),
("FSB","https://github.com/fullselfbrowsing/FSB","browser","adapter","Full browser agent needs external Playwright worker"),
# Agent frameworks / assistants
("PersonalJarvis","https://github.com/tbckdev/PersonalJarvis","agents","reference","Personal assistant patterns"),
("jarvis","https://github.com/Danush-Aries/jarvis","agents","reference","Assistant patterns"),
("OpenJarvis","https://github.com/open-jarvis/OpenJarvis","agents","reference","Open agent runtime patterns"),
("open-jarvis-tokenarc","https://github.com/tokenarc/open-jarvis","agents","reference","Open Jarvis patterns"),
("crewAI","https://github.com/crewAIInc/crewAI","agents","ported","Multi-agent role/handoff behavior implemented without heavy dependency"),
("LangGraph","https://github.com/langchain-ai/langgraph","agents","ported","Stateful graph pattern implemented with persisted project jobs"),
("Microsoft Agent Framework","https://github.com/microsoft/agent-framework","agents","reference","Framework interoperability reference"),
("anycode","https://github.com/Quantlix/anycode","agents","reference","Coding-agent reference"),
("awesome-jarvis","https://github.com/csells/awesome-jarvis","agents","reference","Curated assistant ecosystem"),
("OpenDots","https://github.com/CopilotKit/OpenDots","agents","reference","Agent UI/reference"),
("mongodb-ai-agents-lab","https://github.com/mongodb-developer/ai-agents-lab","agents","reference","Agent examples"),
("agents-lab","https://github.com/Vincent-Maladiere/agents-lab","agents","reference","Agent examples"),
# LLM routing / Groq
("LiteLLM","https://github.com/BerriAI/litellm","routing","adapter","OpenAI-compatible proxy entry in model hub"),
("otari","https://github.com/mozilla-ai/otari","routing","reference","Model routing reference"),
("llmgateway","https://github.com/theopenco/llmgateway","routing","adapter","OpenAI-compatible gateway entry"),
("yolorouter","https://github.com/yolorouter/yolorouter","routing","adapter","OpenAI-compatible route"),
("black-vault","https://github.com/venkat22022202/black-vault","security","reference","Key management reference"),
("llm-apikey-manager","https://github.com/bejo6/llm-apikey-manager","security","reference","Key management reference; per-user vault implemented"),
("groq-python","https://github.com/groq/groq-python","groq","adapter","Groq chat and Whisper routes"),
("groq-typescript","https://github.com/groq/groq-typescript","groq","reference","Frontend examples"),
("groq-api-cookbook","https://github.com/groq/groq-api-cookbook","groq","reference","API recipes"),
("groq-mcp-server","https://github.com/groq/groq-mcp-server","groq","adapter","Can be connected through external MCP worker"),
("groq-desktop-beta","https://github.com/groq/groq-desktop-beta","groq","reference","Desktop-only"),
("groq-aisdk-chatbot","https://github.com/groq/groq-aisdk-chatbot","groq","reference","Chat UI patterns"),
("groq-gradio","https://github.com/groq/groq-gradio","groq","reference","Gradio patterns"),
("groq-chatbot","https://github.com/rabilrbl/groq-chatbot","groq","reference","Chatbot patterns"),
("AI-Telegram-Bot","https://github.com/OggyBoi08/AI-Telegram-Bot","bots","adapter","Requires Telegram bot token/webhook"),
("cervum-ai-client","https://github.com/agungjsp/cervum-ai-client","agents","reference","Client patterns"),
# Video production
("ViMax","https://github.com/HKUDS/ViMax","video","active","Agentic idea/script/novel-to-video pipeline ported"),
("FFmpeg","https://github.com/FFmpeg/FFmpeg","render","adapter","Commands emitted; binary runs on render worker, not Vercel"),
("moviepy","https://github.com/Zulko/moviepy","render","adapter","Executable Python render recipe emitted"),
("Remotion","https://github.com/remotion-dev/remotion","render","adapter","Composition props emitted for render worker"),
("OpenMontage","https://github.com/calesthio/OpenMontage","render","adapter","Shot manifest emitted"),
("Whisper","https://github.com/openai/whisper","transcribe","adapter","Groq/OpenAI/Replicate/HF routes"),
("yt-dlp","https://github.com/yt-dlp/yt-dlp","youtube","reference","Not run server-side; downloading third-party media has rights/ToS implications"),
("Stable-Video-Infinity","https://github.com/vita-epfl/Stable-Video-Infinity","video","adapter","Replicate slug or own GPU endpoint"),
("Helios","https://github.com/PKU-YuanGroup/Helios","video","adapter","Replicate slug or own GPU endpoint"),
("awesome-ai-video-tools","https://github.com/Thedurancode/awesome-ai-video-tools","video","reference","Discovery list"),
# Voice
("VoiceStudio","https://github.com/debpalash/VoiceStudio","voice","reference","Voice studio UX/reference"),
("GPT-SoVITS","https://github.com/RVC-Boss/GPT-SoVITS","voice","adapter","HF Space/self-hosted route"),
("F5-TTS","https://github.com/SWivid/F5-TTS","voice","adapter","HF Space, Replicate and self-hosted routes"),
("OpenVoice","https://github.com/myshell-ai/OpenVoice","voice","adapter","Self-hosted route"),
("Chatterbox","https://github.com/resemble-ai/chatterbox","voice","adapter","Self-hosted route"),
("Qwen3-TTS","https://github.com/QwenLM/Qwen3-TTS","voice","adapter","Self-hosted route"),
("Coqui TTS","https://github.com/coqui-ai/TTS","voice","adapter","Replicate XTTS and self-hosted routes"),
("fish-speech","https://github.com/fishaudio/fish-speech","voice","adapter","Self-hosted route"),
("ChatTTS","https://github.com/2noise/ChatTTS","voice","adapter","HF Space route"),
("Kokoro","https://github.com/hexgrad/kokoro","voice","adapter","HF Space and self-hosted routes"),
# Avatars
("LiveTalking","https://github.com/lipku/LiveTalking","avatar","adapter","External WebRTC/GPU server route"),
("MuseTalk","https://github.com/TMElyralab/MuseTalk","avatar","adapter","External GPU route"),
("SadTalker","https://github.com/OpenTalker/SadTalker","avatar","adapter","Replicate/fal/self-hosted routes"),
("LivePortrait","https://github.com/KlingAI/LivePortrait","avatar","adapter","fal/self-hosted route"),
# Images
("ComfyUI","https://github.com/comfyanonymous/ComfyUI","image","adapter","Full workflow queue/poll API implemented"),
("stable-diffusion-webui","https://github.com/AUTOMATIC1111/stable-diffusion-webui","image","adapter","txt2img/img2img API implemented"),
("Fooocus","https://github.com/lllyasviel/Fooocus","image","adapter","Self-hosted JSON route"),
("diffusers","https://github.com/huggingface/diffusers","image","adapter","HF Inference route"),
("InvokeAI","https://github.com/invoke-ai/InvokeAI","image","adapter","Self-hosted JSON route"),
("stable-diffusion","https://github.com/CompVis/stable-diffusion","image","adapter","fal/self-hosted route"),
("FLUX","https://github.com/black-forest-labs/flux","image","active","Free Pollinations plus fal/Replicate/HF routes"),
("FastSD CPU","https://github.com/rupeshs/fastsdcpu","image","adapter","Self-hosted CPU endpoint"),
("ControlNet","https://github.com/lllyasviel/ControlNet","image","adapter","SD-WebUI/ComfyUI workflow support"),
("Real-ESRGAN","https://github.com/xinntao/Real-ESRGAN","upscale","adapter","fal/Replicate/self-hosted routes"),
]


def catalog(category=None):
    rows=[{"id":i,"url":u,"category":c,"status":s,"integration":n} for i,u,c,s,n in RAW]
    if category: rows=[r for r in rows if r["category"]==category]
    return rows

def summary():
    rows=catalog(); cats=sorted({r["category"] for r in rows})
    return {"total":len(rows),"categories":cats,"by_status":{s:sum(r["status"]==s for r in rows)
            for s in ("active","ported","adapter","reference")}}

__all__=["catalog","summary"]
