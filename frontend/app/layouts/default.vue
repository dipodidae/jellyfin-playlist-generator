<script setup lang="ts">
const route = useRoute()

const activeNav = computed(() => {
  if (route.path === '/observatory') return 'observatory'
  if (route.path === '/eval') return 'eval'
  return 'generator'
})

const navItems = [
  { to: '/', key: 'generator', label: 'Generator' },
  { to: '/observatory', key: 'observatory', label: 'Observatory' },
  { to: '/eval', key: 'eval', label: 'Eval' },
]

const widePages = computed(() => activeNav.value === 'observatory' || activeNav.value === 'eval')
</script>

<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-950">
    <header class="border-b border-gray-200 dark:border-gray-800">
      <div class="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
        <div class="flex items-center gap-6">
          <NuxtLink
            to="/"
            class="text-xl font-semibold text-gray-900 dark:text-white hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
          >
            Playlist Generator
          </NuxtLink>
          <nav class="flex items-center gap-1">
            <NuxtLink
              v-for="item in navItems"
              :key="item.key"
              :to="item.to"
              class="px-3 py-1.5 text-sm font-medium rounded-md transition-colors"
              :class="activeNav === item.key
                ? 'bg-gray-200 dark:bg-gray-800 text-gray-900 dark:text-white'
                : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800/50'"
            >
              {{ item.label }}
            </NuxtLink>
          </nav>
        </div>
      </div>
    </header>
    <main
      class="mx-auto px-4 py-8"
      :class="widePages ? 'max-w-6xl' : 'max-w-4xl'"
    >
      <slot />
    </main>
  </div>
</template>
