"""Compare the hosted JS adaptations with pinned, local Python source fixtures.

This uses only local code and does not load a model, contact a provider or fetch
URLs. It is not a substitute for real YouTube Analytics or competitor research.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from vimax_skills.analyzers import lint_title, score_hook, score_idea
from vimax_skills.workforce import analyze_funnel, parse_youtube_reference

ROOT = Path(__file__).resolve().parents[2]


def test_hosted_pure_skills_match_local_pinned_examples():
    if not shutil.which('node'):
        pytest.skip('Node is required for cross-runtime parity fixtures')
    ideas = ['How to grow 5 herbs at home', 'The ultimate guide for beginners', 'Why this latest update matters', 'A calm evening prayer', '你好世界']
    hooks = ['Why do your seedlings die after only seven days?', 'Stop wasting your time before you build!',
             'In the next 5 minutes you can learn a simple habit', 'Hello everyone', '你好吗']
    titles = [('5 ways to start a garden', 'FIRST SEEDS'), ('How to plan a long and useful video without wasting your time every day', 'PLAN YOUR VIDEO'),
              ('A calm evening prayer?', ''), ('WHY THIS IS AMAZING', 'THE ANSWER'), ('你好', '')]
    references = ['dQw4w9WgXcQ', 'https://youtube.com/@some.handle', 'https://youtube.com/user/SomeUser',
                  'https://youtube.com/shorts/dQw4w9WgXcQ', 'https://youtube.com/channel/UCabcdefghijklmnopqrstuv']
    funnels = [{'format':'long','metrics':{'impressions':4000,'ctr':2,'avd_seconds':40,'length_seconds':100,'views':90}},
               {'metrics':{'views':0}}, {'format':'shorts','metrics':{'impressions':1000,'ctr':3,'views':25,'avd_seconds':34,'length_seconds':30}},
               {'metrics':{'impressions':10000,'ctr':5,'avd_seconds':50,'length_seconds':100}}]
    cases = ([{'kind':'idea','input':{'idea':x}} for x in ideas]
             + [{'kind':'hook','input':{'hook':x}} for x in hooks]
             + [{'kind':'title','input':{'title':x,'thumbnail':y}} for x,y in titles]
             + [{'kind':'url','input':{'reference':x}} for x in references]
             + [{'kind':'funnel','input':x} for x in funnels])
    code = """import {ideaReview,hookReview,titleReview,youtubeReference,funnelReview} from './api/creator-skills.mjs';
const chunks=[]; for await (const chunk of process.stdin) chunks.push(chunk);
const cases=JSON.parse(Buffer.concat(chunks).toString('utf8'));
const fn={idea:ideaReview,hook:hookReview,title:titleReview,url:youtubeReference,funnel:funnelReview};
process.stdout.write(JSON.stringify(cases.map(c=>fn[c.kind](c.input))));"""
    completed = subprocess.run(['node','--input-type=module','-e',code], cwd=ROOT, input=json.dumps(cases),
                               text=True, capture_output=True, timeout=20, check=True)
    actual = json.loads(completed.stdout)
    expected = ([score_idea(x) for x in ideas] + [score_hook(x) for x in hooks]
                + [lint_title(x,y) for x,y in titles] + [parse_youtube_reference(x) for x in references]
                + [analyze_funnel(x) for x in funnels])
    # Python tuple pairs become JSON arrays over both HTTP interfaces.
    expected = json.loads(json.dumps(expected))
    for case, js, py in zip(cases, actual, expected, strict=True):
        assert js == py, f"hosted/local mismatch for {case['kind']}: {case['input']}"
