export default defineEventHandler(async () => {
  const config = useRuntimeConfig()
  
  const response = await fetch(`${config.serviceUrl}/sync/embeddings`, {
    method: 'POST',
  })
  
  if (!response.ok) {
    throw createError({
      statusCode: response.status,
      message: 'Embedding generation failed',
    })
  }
  
  return response.json()
})
