// Local preview uses the development API. Deployed frontends (including
// Netlify) call the public Django API on PythonAnywhere.
const localHosts = new Set(['localhost', '127.0.0.1']);
const isLocal = localHosts.has(window.location.hostname);
window.GPMS_API_BASE_URL = isLocal
  ? `${window.location.protocol}//${window.location.hostname}${window.location.port === '8000' ? ':8001' : ''}/api/v1`
  : 'https://mjdkhaled1.pythonanywhere.com/api/v1';
