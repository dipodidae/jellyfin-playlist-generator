export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const query = getQuery(event)
  const full = query.full === 'true' || query.full === '1'

  const response = await fetch(`${config.musicServiceUrl}/sync/jellyfin/stream?full=${full}`, {
    method: 'POST',
  })

  if (!response.ok) {
    throw createError({
      statusCode: response.status,
      statusMessage: await response.text(),
    })
  }

  // Stream the response through
  setResponseHeader(event, 'Content-Type', 'text/event-stream')
  setResponseHeader(event, 'Cache-Control', 'no-cache')
  setResponseHeader(event, 'Connection', 'keep-alive')

  return response.body
})
