"""Bounded local adapters for two vendored, dependency-free creator tools.

The fixed handlers only inspect user-supplied values: they never fetch a URL,
load a model, access a channel, or write anything. The original upstream sources
are kept unchanged under skills/vendor with their MIT notices.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

_VENDOR = Path(__file__).resolve().parents[1] / 'vendor'


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load bundled skill {name}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_funnel = _load(_VENDOR / 'youtube-agent-pro' / 'yt-analytics' / 'funnel.py', 'vimax_vendored_funnel')
_youtube = _load(_VENDOR / 'youtube-skills' / 'url_parser.py', 'vimax_vendored_url_parser')
_VIDEO = re.compile(r'[A-Za-z0-9_-]{11}\Z')
_CHANNEL = re.compile(r'UC[A-Za-z0-9_-]{22}\Z')
_HANDLE = re.compile(r'[A-Za-z0-9_.-]{3,30}\Z')
_LEGACY = re.compile(r'[A-Za-z0-9_-]{1,100}\Z')


def parse_youtube_reference(value: object) -> dict:
    """Parse a strictly validated YouTube reference without network access.

    The upstream parser uses unanchored regex search; passing it only a freshly
    constructed canonical URL prevents spoofed hosts and partial video IDs. Its
    /user/ canonicalization is repaired, preserving that path's identity.
    """
    if not isinstance(value, str) or not value or len(value) > 2048 or value != value.strip():
        raise ValueError('Provide a YouTube URL or an 11-character video ID.')
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise ValueError('Reference contains whitespace or control characters.')
    kind = ''
    if _VIDEO.fullmatch(value):
        canonical, kind = f'https://www.youtube.com/watch?v={value}', 'video'
    else:
        try:
            parts = urlsplit(value)
            host = parts.hostname
            # Explicit ports and userinfo are not accepted, even for valid hosts.
            if parts.scheme != 'https' or not host or parts.username is not None or parts.password is not None or parts.port is not None:
                raise ValueError('Expected an HTTPS YouTube URL without user info or a port.')
            if parts.netloc.lower() != host or host not in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtu.be'}:
                raise ValueError('Unrecognized YouTube host.')
            if '%' in parts.path or '\\' in parts.path or '//' in parts.path:
                raise ValueError('Encoded or ambiguous paths are not supported.')
            path = parts.path.rstrip('/')
            segments = path.split('/')[1:]
            query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=30)
            if host in {'youtu.be', 'www.youtu.be'} and len(segments) == 1 and _VIDEO.fullmatch(segments[0]):
                canonical, kind = f'https://www.youtube.com/watch?v={segments[0]}', 'video'
            elif path == '/watch' and host not in {'youtu.be', 'www.youtu.be'}:
                videos = query.get('v', [])
                if len(videos) != 1 or not _VIDEO.fullmatch(videos[0]):
                    raise ValueError('Watch URL must contain exactly one complete video ID.')
                canonical, kind = f'https://www.youtube.com/watch?v={videos[0]}', 'video'
            elif host not in {'youtu.be', 'www.youtu.be'} and len(segments) == 2 and segments[0] in {'shorts', 'embed', 'live', 'v'} and _VIDEO.fullmatch(segments[1]):
                canonical, kind = f'https://www.youtube.com/watch?v={segments[1]}', 'shorts' if segments[0] == 'shorts' else 'video'
            elif host not in {'youtu.be', 'www.youtu.be'} and len(segments) == 1 and segments[0].startswith('@') and _HANDLE.fullmatch(segments[0][1:]):
                canonical, kind = f'https://www.youtube.com/{segments[0]}', 'handle'
            elif host not in {'youtu.be', 'www.youtu.be'} and len(segments) == 2 and segments[0] == 'channel' and _CHANNEL.fullmatch(segments[1]):
                canonical, kind = f'https://www.youtube.com/channel/{segments[1]}', 'channel'
            elif host not in {'youtu.be', 'www.youtu.be'} and len(segments) == 2 and segments[0] in {'c', 'user'} and _LEGACY.fullmatch(segments[1]):
                canonical, kind = f'https://www.youtube.com/{segments[0]}/{segments[1]}', segments[0]
            else:
                raise ValueError('Unsupported or malformed YouTube reference.')
        except ValueError as exc:
            raise ValueError('Invalid or unsupported YouTube reference.') from exc
    parsed = _youtube.parse_youtube_url(canonical)
    if parsed is None:
        raise ValueError('Could not parse the YouTube reference.')
    parsed['canonical_url'] = canonical  # Fix upstream /user/ -> /c/ rewrite.
    parsed['is_short'] = kind == 'shorts'
    parsed['reference_kind'] = kind
    parsed['notice'] = 'Parsed locally; this does not fetch the URL or verify a channel, owner, or video.'
    return parsed


_METRICS = {'impressions', 'views', 'ctr', 'avd_seconds', 'length_seconds'}


def analyze_funnel(data: object) -> dict:
    """Review manually supplied, bounded metrics with heuristic thresholds."""
    if not isinstance(data, dict) or set(data) - {'format', 'metrics'}:
        raise ValueError('Provide format and a metrics object.')
    form = data.get('format', 'long')
    metrics = data.get('metrics')
    if not isinstance(form, str) or form not in {'long', 'shorts'}:
        raise ValueError('Invalid video format.')
    if not isinstance(metrics, dict) or not metrics or set(metrics) - _METRICS:
        raise ValueError('Provide one or more supported numeric metrics.')
    clean = {}
    for name, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 1_000_000_000_000 or not math.isfinite(value):
            raise ValueError(f'Invalid metric: {name}.')
        if name in {'impressions', 'views'} and not isinstance(value, int):
            raise ValueError(f'{name} must be a whole number.')
        if name == 'ctr' and value > 100:
            raise ValueError(f'{name} must be a percentage from 0 to 100.')
        if name in {'avd_seconds', 'length_seconds'} and value > 86400:
            raise ValueError(f'{name} exceeds the supported duration.')
        if name == 'length_seconds' and value < 0.001:
            raise ValueError('Video length must be at least 0.001 seconds.')
        clean[name] = value
    # Average view duration can exceed video length when viewers replay it.
    # Shorts are not an impressions/CTR funnel; avoid the upstream calculation
    # of an impression-derived views estimate before its Shorts branch.
    impr = clean.get('impressions') if form == 'long' else None
    ctr = clean.get('ctr') if form == 'long' else None
    result = _funnel.diagnose(impr, ctr, clean.get('avd_seconds'),
                              clean.get('length_seconds'), clean.get('views'), form)
    if form == 'shorts' and ('impressions' in clean or 'ctr' in clean):
        result['warnings'].append('Impressions and CTR were ignored for Shorts; they do not describe the Shorts-feed funnel.')
    if form == 'long' and result['estimated_views_from_impressions'] is not None and clean.get('views') is not None:
        result['warnings'].append('Impressions × CTR estimates only views from counted impressions, not total video views.')
    result['notice'] = ('Heuristic suggestions based only on supplied metrics; no YouTube data was fetched. '
                        'Thresholds are not a causal diagnosis, forecast, or guarantee.')
    return result


def run_local_skill(skill: str, data: object) -> dict:
    if skill == 'youtube_url_parser':
        if not isinstance(data, dict) or set(data) != {'reference'}:
            raise ValueError('Provide one reference string.')
        return parse_youtube_reference(data['reference'])
    if skill == 'funnel_heuristic':
        return analyze_funnel(data)
    raise LookupError('That skill is not available in the local companion.')
