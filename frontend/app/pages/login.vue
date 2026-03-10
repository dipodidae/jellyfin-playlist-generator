<script setup lang="ts">
const { loggedIn, fetch: fetchSession } = useUserSession()
const router = useRouter()

const username = ref('')
const password = ref('')
const error = ref('')
const isLoading = ref(false)

// Redirect if already logged in
watch(loggedIn, (value) => {
  if (value) {
    router.push('/')
  }
}, { immediate: true })

async function login() {
  if (isLoading.value) return

  isLoading.value = true
  error.value = ''

  try {
    await $fetch('/api/auth/login', {
      method: 'POST',
      body: { username: username.value, password: password.value },
    })
    await fetchSession()
    router.push('/')
  }
  catch (e: any) {
    error.value = e.data?.statusMessage || 'Login failed'
  }
  finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950">
    <div class="w-full max-w-sm p-6 bg-white dark:bg-gray-900 rounded-lg shadow-lg">
      <h1 class="text-2xl font-bold text-center text-gray-900 dark:text-white mb-6">
        Playlist Generator
      </h1>

      <form class="space-y-4" @submit.prevent="login">
        <div>
          <UInput
            v-model="username"
            placeholder="Username"
            size="lg"
            :disabled="isLoading"
          />
        </div>

        <div>
          <UInput
            v-model="password"
            type="password"
            placeholder="Password"
            size="lg"
            :disabled="isLoading"
          />
        </div>

        <div v-if="error" class="text-red-500 text-sm text-center">
          {{ error }}
        </div>

        <UButton
          type="submit"
          block
          size="lg"
          :loading="isLoading"
          :disabled="!username || !password"
        >
          Login
        </UButton>
      </form>
    </div>
  </div>
</template>
