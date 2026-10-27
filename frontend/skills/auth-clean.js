// Supabase confirmation redirects can carry short-lived tokens in a URL fragment.
// We require a fresh sign-in instead and remove the fragment immediately.
if (/(?:^#|&)(?:access_token|refresh_token|error_description)=/.test(location.hash)) {
  const wasSuccess = /(?:^#|&)access_token=/.test(location.hash);
  history.replaceState(null, '', location.pathname + location.search);
  try { sessionStorage.setItem('vimax-email-confirmed', wasSuccess ? 'yes' : 'no'); } catch {}
}
