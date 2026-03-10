export default defineEventHandler(async () => {
  const config = useRuntimeConfig()

  const response = await fetch(`${config.musicServiceUrl}/stats`)

  if (!response.ok) {
    throw createError({
      statusCode: response.status,
      statusMessage: await response.text(),
    })
  }

  return response.json()
})
