export default defineNuxtConfig({
  modules: [
    '@nuxt/ui',
    '@nuxt/eslint',
    'nuxt-auth-utils',
  ],

  css: ['~/assets/css/main.css'],

  devtools: {
    enabled: true,
  },

  app: {
    head: {
      title: 'Playlist Generator',
      meta: [
        { name: 'description', content: 'Prompt-driven playlist generation for your music library' },
      ],
    },
  },


  compatibilityDate: '2025-01-15',

  runtimeConfig: {
    musicServiceUrl: process.env.NUXT_MUSIC_SERVICE_URL || 'http://localhost:8000',
    jellyfinUrl: process.env.NUXT_JELLYFIN_URL,
    jellyfinApiKey: process.env.NUXT_JELLYFIN_API_KEY,
    jellyfinUserId: process.env.NUXT_JELLYFIN_USER_ID,
    authUsername: process.env.NUXT_AUTH_USERNAME,
    authPassword: process.env.NUXT_AUTH_PASSWORD,
  },

  nitro: {
    esbuild: {
      options: {
        target: 'esnext',
      },
    },
  },

  eslint: {
    config: {
      standalone: false,
    },
  },
})
