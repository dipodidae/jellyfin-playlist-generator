<script setup lang="ts">
const route = useRoute()
const mobileOpen = ref(false)

const navItems = [
  { to: '/', key: 'generator', label: 'Generator', icon: 'i-lucide-sparkles' },
  { to: '/observatory', key: 'observatory', label: 'Observatory', icon: 'i-lucide-telescope' },
  { to: '/eval', key: 'eval', label: 'Eval', icon: 'i-lucide-flask-conical' },
  { to: '/settings', key: 'settings', label: 'Settings', icon: 'i-lucide-settings-2' },
  { to: '/tools', key: 'tools', label: 'Tools', icon: 'i-lucide-wrench' },
]

const activeKey = computed(() => {
  const found = navItems.find(i => i.to !== '/' && route.path.startsWith(i.to))
  return found?.key ?? 'generator'
})

const widePages = computed(() => activeKey.value === 'observatory' || activeKey.value === 'eval')

// close the mobile drawer on navigation
watch(() => route.path, () => { mobileOpen.value = false })
</script>

<template>
  <div class="min-h-screen">
    <header class="sticky top-0 z-50 glass border-x-0 border-t-0">
      <div class="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <!-- Brand -->
        <NuxtLink to="/" class="group flex items-center gap-3">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-acid-400/10 ring-1 ring-acid-400/30 transition group-hover:ring-acid-400/60">
            <span class="flex h-4 items-end gap-[3px]">
              <span class="eq-bar h-full w-[3px] rounded-full bg-acid-400" style="animation-delay:0ms" />
              <span class="eq-bar h-full w-[3px] rounded-full bg-acid-300" style="animation-delay:160ms" />
              <span class="eq-bar h-full w-[3px] rounded-full bg-acid-500" style="animation-delay:320ms" />
            </span>
          </span>
          <span class="flex flex-col leading-none">
            <span class="font-display text-base font-semibold tracking-tight text-white">Playlist<span class="text-gradient-acid">Engine</span></span>
            <span class="hidden text-[10px] font-medium uppercase tracking-[0.2em] text-(--ui-text-dimmed) sm:block">music intelligence</span>
          </span>
        </NuxtLink>

        <!-- Desktop nav -->
        <nav class="hidden items-center gap-1 md:flex">
          <NuxtLink
            v-for="item in navItems"
            :key="item.key"
            :to="item.to"
            class="group relative flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-medium transition-colors"
            :class="activeKey === item.key
              ? 'text-acid-300'
              : 'text-(--ui-text-muted) hover:text-white'"
          >
            <span
              v-if="activeKey === item.key"
              class="absolute inset-0 rounded-full bg-acid-400/10 ring-1 ring-acid-400/25"
            />
            <UIcon :name="item.icon" class="relative size-4" />
            <span class="relative">{{ item.label }}</span>
          </NuxtLink>
        </nav>

        <!-- Mobile trigger -->
        <UButton
          icon="i-lucide-menu"
          color="neutral"
          variant="ghost"
          size="lg"
          class="md:hidden"
          aria-label="Open menu"
          @click="mobileOpen = true"
        />
      </div>
    </header>

    <!-- Mobile drawer -->
    <USlideover v-model:open="mobileOpen" title="Navigate" side="right">
      <template #body>
        <nav class="flex flex-col gap-1">
          <NuxtLink
            v-for="item in navItems"
            :key="item.key"
            :to="item.to"
            class="flex items-center gap-3 rounded-xl px-4 py-3 text-base font-medium transition-colors"
            :class="activeKey === item.key
              ? 'bg-acid-400/10 text-acid-300 ring-1 ring-acid-400/25'
              : 'text-(--ui-text-muted) hover:bg-(--ui-bg-elevated) hover:text-white'"
          >
            <UIcon :name="item.icon" class="size-5" />
            {{ item.label }}
          </NuxtLink>
        </nav>
      </template>
    </USlideover>

    <main
      class="mx-auto px-4 py-8 sm:px-6 sm:py-10"
      :class="widePages ? 'max-w-7xl' : 'max-w-5xl'"
    >
      <div class="rise-in">
        <slot />
      </div>
    </main>
  </div>
</template>
