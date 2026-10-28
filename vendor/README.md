# Vendored hosted creator utility

`youtube-automation-agent/youtube-metadata-validator.cjs` is an unmodified copy
of `utils/youtube-metadata-validator.js` from
[darkzOGx/youtube-automation-agent](https://github.com/darkzOGx/youtube-automation-agent)
commit `e973d515aef90c467da2289144df737a3bd03859`. Only its extension changed
from `.js` to `.cjs` to preserve upstream CommonJS semantics inside this ES
module project. Its MIT license is retained in `youtube-automation-agent/LICENSE`.

`api/workforce-skills.mjs` validates inputs before calling it because the
upstream code truncates values before checking their limits and strips line
breaks. Results are explicitly a normalized, read-only preview, not upload
approval. No other upstream server, scheduler, credential manager or provider
integration is vendored.
