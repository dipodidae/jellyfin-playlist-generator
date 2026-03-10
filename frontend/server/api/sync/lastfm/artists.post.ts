export default defineEventHandler(async () => {
  const config = useRuntimeConfig()
  
  const response = await fetch(`${config.serviceUrl}/sync/lastfm/artists`, {
    method: 'POST',
  })
  
  if (!response.ok) {
    throw createError({
      statusCode: response.status,
      message: 'Last.fm sync failed',
    })
  }
  
  return response.json()
})
