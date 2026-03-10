export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const body = await readBody(event)

  const response = await fetch(`${config.musicServiceUrl}/generate-playlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    throw createError({
      statusCode: response.status,
      statusMessage: await response.text(),
    })
  }

  return response.json()
})
