export default defineNuxtConfig({
  modules: [
    '@nuxt/ui',
    '@nuxt/eslint',
    'nuxt-auth-utils',
  ],

  components: [
    { path: '~/components/observatory', pathPrefix: false },
    '~/components',
  ],

  ssr: true,

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
    public: {
      apiBase: '/api',
    },
  },

  nitro: {
    esbuild: {
      options: {
        target: 'esnext',
      },
    },
    routeRules: {
      '/api/**': {
        proxy: { to: 'http://127.0.0.1:8000/**', streamRequest: true },
      },
    },
  },

  eslint: {
    config: {
      standalone: false,
    },
  },
})
