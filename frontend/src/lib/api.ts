// Stand-in reconstructed from component usage (see types.ts).
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, { ...init, headers: { ...(init?.headers || {}) } });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `Forespørselen feilet (${response.status}).`;
    throw new Error(detail);
  }
  return body as T;
}
