export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  
  const response = await fetch(`${config.musicServiceUrl}/sync/status`)
  
  if (!response.ok) {
    throw createError({
      statusCode: response.status,
      statusMessage: response.statusText,
    })
  }
  
  return response.json()
})
