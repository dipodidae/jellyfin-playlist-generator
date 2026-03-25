<script setup lang="ts">
interface EnhanceDiff {
  added: string[]
  inferred: string[]
  clarified: string[]
}

interface EnhanceResult {
  improved_prompt: string
  explanation: string
  diff: EnhanceDiff
}

type EnhanceMode = 'light' | 'balanced' | 'aggressive'

const props = defineProps<{
  modelValue: string
  playlistSize: number
  hasLibraryData: boolean
  canGenerate: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:playlistSize': [value: number]
  submit: [payload: { prompt: string, size: number }]
}>()

const enhanceMode = ref<EnhanceMode>('balanced')
const isEnhancing = ref(false)
const enhanceResult = ref<EnhanceResult | null>(null)
const enhanceError = ref<string | null>(null)

const modes: { value: EnhanceMode, label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'aggressive', label: 'Aggressive' },
]

async function enhancePrompt() {
  if (!props.modelValue.trim() || isEnhancing.value) return

  isEnhancing.value = true
  enhanceResult.value = null
  enhanceError.value = null

  try {
    const res = await $fetch<EnhanceResult>('/api/enhance-prompt', {
      method: 'POST',
      body: { prompt: props.modelValue, mode: enhanceMode.value },
    })
    enhanceResult.value = res
  }
  catch (e: any) {
    enhanceError.value = e?.data?.detail || e?.message || 'Enhancement failed'
  }
  finally {
    isEnhancing.value = false
  }
}

function applyEnhancement() {
  if (enhanceResult.value) {
    emit('update:modelValue', enhanceResult.value.improved_prompt)
    enhanceResult.value = null
  }
}

function dismissEnhancement() {
  enhanceResult.value = null
  enhanceError.value = null
}

const diffCategoryLabels: Record<keyof EnhanceDiff, { label: string, color: string }> = {
  added: { label: 'Added', color: 'text-success' },
  inferred: { label: 'Inferred', color: 'text-info' },
  clarified: { label: 'Clarified', color: 'text-warning' },
}
</script>

<template>
  <div class="space-y-6">
    <PlaylistPromptGuide />

    <div>
      <UTextarea
        :model-value="modelValue"
        placeholder="driving through fog at 3am"
        :rows="3"
        size="xl"
        autofocus
        class="w-full"
        @update:model-value="emit('update:modelValue', $event)"
      />
    </div>

    <!-- Enhance suggestion card -->
    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      leave-active-class="transition-all duration-150 ease-in"
      enter-from-class="opacity-0 -translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 -translate-y-2"
    >
      <div v-if="enhanceResult" class="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-3">
        <div class="flex items-start justify-between gap-2">
          <h4 class="text-sm font-semibold text-default flex items-center gap-1.5">
            <UIcon name="i-lucide-sparkles" class="size-4 text-primary" />
            Enhanced prompt
          </h4>
          <button
            class="text-muted hover:text-default transition-colors cursor-pointer"
            @click="dismissEnhancement"
          >
            <UIcon name="i-lucide-x" class="size-4" />
          </button>
        </div>

        <div class="rounded-md bg-elevated px-3 py-2 text-sm text-default leading-relaxed">
          {{ enhanceResult.improved_prompt }}
        </div>

        <!-- Diff pills -->
        <div class="flex flex-wrap gap-1.5">
          <template v-for="(meta, category) in diffCategoryLabels" :key="category">
            <span
              v-for="item in enhanceResult.diff[category]"
              :key="`${category}-${item}`"
              class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-elevated"
              :class="meta.color"
            >
              <span class="opacity-60">{{ meta.label }}:</span> {{ item }}
            </span>
          </template>
        </div>

        <p class="text-xs text-muted leading-relaxed">
          {{ enhanceResult.explanation }}
        </p>

        <div class="flex gap-2">
          <UButton size="sm" @click="applyEnhancement">
            Apply
          </UButton>
          <UButton size="sm" variant="ghost" @click="dismissEnhancement">
            Dismiss
          </UButton>
        </div>
      </div>
    </Transition>

    <!-- Enhance error -->
    <div v-if="enhanceError" class="rounded-lg border border-error/30 bg-error/5 px-4 py-3 text-sm text-error flex items-center justify-between">
      <span>{{ enhanceError }}</span>
      <button class="text-error/60 hover:text-error cursor-pointer" @click="enhanceError = null">
        <UIcon name="i-lucide-x" class="size-4" />
      </button>
    </div>

    <!-- Enhance controls -->
    <div class="flex items-center gap-2">
      <div class="flex rounded-lg border border-default overflow-hidden">
        <button
          v-for="m in modes"
          :key="m.value"
          class="px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer"
          :class="enhanceMode === m.value
            ? 'bg-primary text-white'
            : 'bg-elevated text-muted hover:text-default'"
          @click="enhanceMode = m.value"
        >
          {{ m.label }}
        </button>
      </div>
      <UButton
        size="sm"
        variant="soft"
        icon="i-lucide-sparkles"
        :loading="isEnhancing"
        :disabled="!modelValue.trim() || isEnhancing"
        @click="enhancePrompt"
      >
        Enhance
      </UButton>
    </div>

    <div class="flex items-center gap-4">
      <label class="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
        Playlist size:
      </label>
      <USlider
        :model-value="playlistSize"
        :min="10"
        :max="100"
        :step="5"
        class="flex-1"
        @update:model-value="emit('update:playlistSize', $event)"
      />
      <span class="text-sm font-medium text-gray-900 dark:text-white w-16 text-right">
        {{ playlistSize }} tracks
      </span>
    </div>

    <UButton
      size="lg"
      :disabled="!canGenerate || !hasLibraryData"
      class="w-full justify-center"
      @click="emit('submit', { prompt: modelValue, size: playlistSize })"
    >
      Generate Playlist
    </UButton>
  </div>
</template>
