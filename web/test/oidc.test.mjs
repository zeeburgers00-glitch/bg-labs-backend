import {test} from 'node:test';
import assert from 'node:assert/strict';
import {getVercelOidcTokenSync} from '@vercel/oidc';
import {parseAuthConfig, parseGlobalConfig} from '@vercel/cli-config';

// No network or real token: exercise the official request-context integration
// and the patched Zod override against the cli-config validation surface.
test('OIDC helper resolves the current platform request context, not a cached token', () => {
  const symbol = Symbol.for('@vercel/request-context');
  const oldContext = globalThis[symbol], oldEnv = process.env.VERCEL_OIDC_TOKEN;
  let token = 'request.token.one';
  try {
    delete process.env.VERCEL_OIDC_TOKEN;
    globalThis[symbol] = {get:() => ({headers:{'x-vercel-oidc-token':token}})};
    assert.equal(getVercelOidcTokenSync(), 'request.token.one');
    token = 'request.token.two';
    assert.equal(getVercelOidcTokenSync(), 'request.token.two');
    globalThis[symbol] = {get:() => ({headers:{}})};
    assert.throws(() => getVercelOidcTokenSync(), /missing/);
  } finally {
    if (oldContext === undefined) delete globalThis[symbol]; else globalThis[symbol] = oldContext;
    if (oldEnv === undefined) delete process.env.VERCEL_OIDC_TOKEN; else process.env.VERCEL_OIDC_TOKEN = oldEnv;
  }
});

test('patched cli-config validation accepts valid configuration and rejects invalid values', () => {
  assert.deepEqual(parseGlobalConfig({credStorage:'file', usedBefore:true}), {credStorage:'file', usedBefore:true});
  assert.deepEqual(parseAuthConfig({token:'fake-token', expiresAt:123}), {token:'fake-token', expiresAt:123});
  assert.throws(() => parseGlobalConfig({credStorage:'not-valid'}));
  assert.throws(() => parseAuthConfig({expiresAt:'not-a-number'}));
});

test('deployed wrapper runs the canonical bridge with the official per-request token resolver', async () => {
  const symbol = Symbol.for('@vercel/request-context');
  const oldContext = globalThis[symbol], oldFetch = globalThis.fetch;
  const keys = ['SUPABASE_URL','SUPABASE_PUBLISHABLE_KEY','VIMAX_GATEWAY_FREE_ENABLED','VERCEL_OIDC_TOKEN','GROQ_API_KEY','OPENAI_API_KEY','GEMINI_API_KEY','MISTRAL_API_KEY','ZAI_API_KEY','OPENROUTER_API_KEY','HF_TOKEN','OPENCODE_API_KEY'];
  const previous = Object.fromEntries(keys.map(key => [key,process.env[key]]));
  try {
    for (const key of keys) delete process.env[key];
    Object.assign(process.env, {SUPABASE_URL:'https://example.supabase.co', SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test', VIMAX_GATEWAY_FREE_ENABLED:'true'});
    globalThis.fetch = async url => {
      const path = new URL(url).pathname;
      if (path === '/auth/v1/health') return Response.json({status:'ok'});
      if (path === '/rest/v1/rpc/vimax_cloud_health') return Response.json(true);
      throw new Error('Unexpected network request in test');
    };
    globalThis[symbol] = {get:() => ({headers:{'x-vercel-oidc-token':'only.for.this.request'}})};
    const {default:deployed} = await import('../api/bridge.mjs');
    const first = await deployed.fetch(new Request('https://app.example/api/health'));
    assert.equal(first.status, 200);
    const payload = await first.json();
    assert.equal(payload.text_chat, 'configured_unverified');
    assert.doesNotMatch(JSON.stringify(payload), /only\.for\.this\.request/);
    globalThis[symbol] = {get:() => ({headers:{}})};
    const second = await deployed.fetch(new Request('https://app.example/api/health'));
    assert.equal((await second.json()).text_chat, 'unconfigured');
  } finally {
    globalThis.fetch = oldFetch;
    if (oldContext === undefined) delete globalThis[symbol]; else globalThis[symbol] = oldContext;
    for (const key of keys) if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key];
  }
});
