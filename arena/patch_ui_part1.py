"""One-shot patch: AI Agents page + YouTube 'Continue with Google' UI into index.html."""
from pathlib import Path

path = Path("index.html")
html = path.read_text(encoding="utf-8")
results = []


def sub(label, old, new, required=True):
    global html
    if old not in html:
        results.append(("MISS", label))
        if required:
            raise SystemExit(f"anchor not found: {label}")
        return
    html = html.replace(old, new, 1)
    results.append(("ok", label))


# ---------------------------------------------------------------- 1. sidebar
sub("sidebar: AI Agents item", """                <div class="sidebar-item px-4 py-3 rounded-lg cursor-pointer flex items-center gap-3 text-gray-300 hover:bg-gray-800" onclick="navigate('youtube')">
                    <i class="fa-brands fa-youtube w-5 text-center"></i>
                    <span>YouTube Automation</span>
                </div>""", """                <div class="sidebar-item px-4 py-3 rounded-lg cursor-pointer flex items-center gap-3 text-gray-300 hover:bg-gray-800" onclick="navigate('agents')">
                    <i class="fa-solid fa-robot w-5 text-center"></i>
                    <span>AI Agents</span>
                    <span class="ml-auto text-[10px] font-bold px-1.5 py-0.5 rounded bg-gradient-to-r from-indigo-500 to-purple-600 text-white">NEW</span>
                </div>

                <div class="sidebar-item px-4 py-3 rounded-lg cursor-pointer flex items-center gap-3 text-gray-300 hover:bg-gray-800" onclick="navigate('youtube')">
                    <i class="fa-brands fa-youtube w-5 text-center"></i>
                    <span>YouTube Automation</span>
                </div>""")

# ------------------------------------------------------------- 2. navigate()
sub("navigate: agents case", """                case 'youtube': renderYouTube(); break;""",
    """                case 'agents': renderAgents(); break;
                case 'youtube': renderYouTube(); break;""")

# ------------------------------------------------------------- 3. renderApp()
sub("renderApp: youtube oauth return", """        navigate('dashboard');
    }""", """        navigate(window.location.search.indexOf('yt=') !== -1 ? 'youtube' : 'dashboard');
        handleYouTubeReturn();
    }""")

# --------------------------------------------- 4. YouTube connect panel (top)
sub("youtube: connect panel", """                <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                    <div class="lg:col-span-2 space-y-6">
                        <div id="ytFullPanel" class="glass-panel p-6 rounded-xl">""",
    """                <!-- Connected YouTube channels -->
                <div id="ytConnectPanel" class="glass-panel p-6 rounded-xl mb-8">
                    <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
                        <div>
                            <h3 class="text-lg font-semibold text-white flex items-center gap-2">
                                <i class="fa-brands fa-youtube text-red-500"></i> YouTube Channels
                            </h3>
                            <p class="text-sm text-gray-400" id="ytConnectHint">Connect your Google account to publish, read analytics and reply to comments. Multiple channels are supported.</p>
                        </div>
                        <div class="flex items-center gap-3">
                            <button onclick="connectGoogle()" id="googleConnectBtn" class="flex items-center gap-3 bg-white hover:bg-gray-100 text-gray-800 font-medium px-5 py-3 rounded-lg transition shadow-lg">
                                <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.1 29.4 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 18.9 12 24 12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.1 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C36.9 40.2 44 35 44 24c0-1.3-.1-2.6-.4-3.9z"/></svg>
                                <span id="googleConnectLabel">Continue with Google</span>
                            </button>
                            <button onclick="loadYouTubeChannels()" class="text-gray-400 hover:text-white transition px-3 py-3" title="Refresh channels">
                                <i class="fa-solid fa-rotate"></i>
                            </button>
                        </div>
                    </div>

                    <div id="ytSetupNotice" class="hidden mb-4 p-4 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-sm text-yellow-200"></div>

                    <div id="ytChannelList" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                        <div class="text-sm text-gray-500 py-4">Loading channels...</div>
                    </div>

                    <div id="ytChannelTools" class="hidden mt-6 pt-6 border-t border-gray-700/60 grid grid-cols-1 lg:grid-cols-2 gap-6">
                        <div>
                            <div class="flex items-center justify-between mb-3">
                                <h4 class="text-sm font-semibold text-white uppercase tracking-wider">Recent uploads</h4>
                                <button onclick="loadYtVideos()" class="text-xs text-indigo-400 hover:text-indigo-300"><i class="fa-solid fa-rotate mr-1"></i>Refresh</button>
                            </div>
                            <div id="ytVideoList" class="space-y-2 max-h-72 overflow-y-auto custom-scrollbar text-sm text-gray-500">Select a channel to load its videos.</div>
                        </div>
                        <div>
                            <div class="flex items-center justify-between mb-3">
                                <h4 class="text-sm font-semibold text-white uppercase tracking-wider">Publish a video</h4>
                                <button onclick="aiFillMetadata()" class="text-xs text-purple-400 hover:text-purple-300"><i class="fa-solid fa-wand-magic-sparkles mr-1"></i>Fill with AI</button>
                            </div>
                            <div class="space-y-3">
                                <input type="file" id="ytUploadFile" accept="video/*" class="w-full text-sm text-gray-400 file:mr-3 file:px-4 file:py-2 file:rounded-lg file:border-0 file:bg-indigo-600 file:text-white file:cursor-pointer">
                                <input type="text" id="ytUploadTitle" placeholder="Video title" class="w-full bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-indigo-500">
                                <textarea id="ytUploadDesc" rows="3" placeholder="Description" class="w-full bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-indigo-500"></textarea>
                                <input type="text" id="ytUploadTags" placeholder="Tags (comma separated)" class="w-full bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-indigo-500">
                                <div class="grid grid-cols-2 gap-3">
                                    <select id="ytUploadPrivacy" class="bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm">
                                        <option value="private">Private</option>
                                        <option value="unlisted">Unlisted</option>
                                        <option value="public">Public</option>
                                    </select>
                                    <select id="ytUploadChannel" class="bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm"></select>
                                </div>
                                <input type="datetime-local" id="ytUploadSchedule" class="w-full bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm" title="Optional: schedule the release">
                                <div class="w-full bg-gray-700 h-2 rounded-full overflow-hidden hidden" id="ytUploadBarWrap">
                                    <div class="bg-indigo-500 h-full transition-all" id="ytUploadBar" style="width:0%"></div>
                                </div>
                                <button onclick="publishToYouTube()" id="ytPublishBtn" class="w-full btn-primary px-4 py-3 rounded-lg text-white font-medium">
                                    <i class="fa-solid fa-cloud-arrow-up mr-2"></i>Upload to YouTube
                                </button>
                                <p class="text-xs text-gray-500">The file uploads straight from your browser to Google - it never passes through our server, so large videos are fine.</p>
                            </div>
                        </div>
                    </div>

                    <div id="ytCommentTools" class="hidden mt-6 pt-6 border-t border-gray-700/60">
                        <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
                            <h4 class="text-sm font-semibold text-white uppercase tracking-wider">Comments <span id="ytCommentVideoTitle" class="text-gray-500 normal-case font-normal"></span></h4>
                            <div class="flex items-center gap-2">
                                <button onclick="aiReplyAll()" class="text-xs bg-purple-600 hover:bg-purple-500 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-robot mr-1"></i>AI replies for all</button>
                                <button onclick="document.getElementById('ytCommentTools').classList.add('hidden')" class="text-xs text-gray-400 hover:text-white px-2 py-2">Close</button>
                            </div>
                        </div>
                        <div id="ytCommentList" class="space-y-3 max-h-96 overflow-y-auto custom-scrollbar"></div>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                    <div class="lg:col-span-2 space-y-6">
                        <div id="ytFullPanel" class="glass-panel p-6 rounded-xl">""")

# ------------------------------------------------- 5. load channels on render
sub("youtube: load channels call", """        loadYouTubeProjects();
    }

    async function createYTAutomation() {""", """        loadYouTubeProjects();
        loadYouTubeChannels();
    }

    async function createYTAutomation() {""")

path.write_text(html, encoding="utf-8")
for status, label in results:
    print(f"{status:5s} {label}")
print("bytes:", len(html))
