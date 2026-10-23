// Production serves the frontend and API from one origin. For local static
// preview on port 8000, the Django development API uses port 8001.
const localApiPort = window.location.port === '8000' ? ':8001' : '';
window.GPMS_API_BASE_URL = `${window.location.protocol}//${window.location.hostname}${localApiPort}/api/v1`;
