// Tiny fetch helper shared by all React feature panels.
export async function getJson(path, options) {
  const response = await fetch(path, { cache: "no-store", ...options });
  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = payload.message || payload.error || "";
    } catch {
      // Use the HTTP status when the backend did not return JSON.
    }
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}
