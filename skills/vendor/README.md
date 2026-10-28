# Vendored creator tools

These unmodified source files are limited to reviewed, dependency-free heuristics; they are not the entire upstream projects. Their MIT notices are retained in each vendor folder.

- `youtube-agent-skill`: commit `a2feb2104981a375ffd4f87ee04f4f5344ac43c6` from https://github.com/Jakeschincariol/youtube-agent-skill.
- `youtube-agent-pro`: commit `45e8e2603d4bf8e17c1147ba870a4ea00eaecbc5` from https://github.com/ahmedsakri/youtube-agent-pro. The existing idea heuristic and newly vendored `yt-analytics/funnel.py` are independent of its agent host.
- `youtube-skills`: `lib/url_parser.py` from commit `73cd16a05b589d755bf2eef3e4ee9db9e2df5494` of https://github.com/sergebulaev/youtube-skills.

The local wrappers in `vimax_skills` bound inputs and correct or reject known
upstream parsing issues. The tools analyze supplied text/metrics, do not promise
engagement, and do not fetch YouTube, verify ownership or publish. No upstream
network client or credential handling was installed.
