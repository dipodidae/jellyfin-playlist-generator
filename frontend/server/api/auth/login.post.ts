export default defineEventHandler(async (event) => {
  const { username, password } = await readBody(event)
  const config = useRuntimeConfig()

  if (username === config.authUsername && password === config.authPassword) {
    await setUserSession(event, {
      user: {
        username,
      },
      loggedInAt: new Date(),
    })
    return { success: true }
  }

  throw createError({
    statusCode: 401,
    statusMessage: 'Invalid credentials',
  })
})
