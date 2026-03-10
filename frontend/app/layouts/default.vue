<script setup lang="ts">
const { loggedIn, clear } = useUserSession()
const router = useRouter()

async function logout() {
  await clear()
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-950">
    <header class="border-b border-gray-200 dark:border-gray-800">
      <div class="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
        <h1 class="text-xl font-semibold text-gray-900 dark:text-white">
          Playlist Generator
        </h1>
        <UButton
          v-if="loggedIn"
          variant="ghost"
          size="sm"
          icon="i-heroicons-arrow-right-on-rectangle"
          @click="logout"
        >
          Logout
        </UButton>
      </div>
    </header>
    <main class="max-w-4xl mx-auto px-4 py-8">
      <slot />
    </main>
  </div>
</template>
