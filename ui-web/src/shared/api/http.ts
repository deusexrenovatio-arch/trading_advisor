export type JsonResponse<T> = Promise<T>

export type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  cache?: RequestCache
}

const isJsonResponse = (response: Response) => {
  const contentType = response.headers.get('content-type') ?? ''
  return contentType.includes('application/json')
}

export const requestJson = async <T>(
  url: string,
  options: RequestOptions = {},
): JsonResponse<T> => {
  const { body, headers, ...rest } = options
  const response = await fetch(url, {
    ...rest,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(headers ?? {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    const fallback = `HTTP ${response.status}`
    if (!isJsonResponse(response)) {
      throw new Error(fallback)
    }
    const payload = await response.json().catch(() => null)
    if (!payload || typeof payload !== 'object') {
      throw new Error(fallback)
    }
    const record = payload as Record<string, unknown>
    const messageKey = ['detail', 'message', 'last_error', 'error'].find(
      (key) => typeof record[key] === 'string' && String(record[key]).trim().length > 0,
    )
    const message = messageKey ? String(record[messageKey]) : fallback
    throw new Error(message)
  }

  if (!isJsonResponse(response)) {
    throw new Error('Expected JSON response')
  }
  return response.json() as Promise<T>
}
