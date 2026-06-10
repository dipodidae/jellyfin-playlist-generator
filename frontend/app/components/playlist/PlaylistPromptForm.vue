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
  <div class="space-y-5">
    <PlaylistPromptGuide />

    <!-- Hero prompt input -->
    <div class="relative">
      <UTextarea
        :model-value="modelValue"
        placeholder="driving through fog at 3am"
        :rows="4"
        size="xl"
        autofocus
        class="w-full font-display text-base"
        :ui="{
          base: 'resize-none transition-shadow duration-200 focus:ring-2 focus:ring-acid-400/40',
        }"
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
      <div
        v-if="enhanceResult"
        class="glass rounded-xl border border-acid-500/30 bg-acid-400/5 p-4 space-y-3"
      >
        <div class="flex items-start justify-between gap-2">
          <h4 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <UIcon name="i-lucide-sparkles" class="size-4 text-acid-400" />
            Enhanced prompt
          </h4>
          <UButton
            variant="ghost"
            color="neutral"
            size="xs"
            icon="i-lucide-x"
            @click="dismissEnhancement"
          />
        </div>

        <div class="rounded-lg bg-(--ui-bg-elevated) border border-(--ui-border) px-3.5 py-2.5 text-sm text-white leading-relaxed">
          {{ enhanceResult.improved_prompt }}
        </div>

        <!-- Diff pills -->
        <div class="flex flex-wrap gap-1.5">
          <template v-for="(meta, category) in diffCategoryLabels" :key="category">
            <UBadge
              v-for="item in enhanceResult.diff[category]"
              :key="`${category}-${item}`"
              variant="soft"
              size="sm"
              :class="meta.color"
            >
              <span class="opacity-60 mr-0.5">{{ meta.label }}:</span>{{ item }}
            </UBadge>
          </template>
        </div>

        <p class="text-xs text-(--ui-text-muted) leading-relaxed">
          {{ enhanceResult.explanation }}
        </p>

        <div class="flex gap-2">
          <UButton size="sm" color="primary" icon="i-lucide-check" @click="applyEnhancement">
            Apply
          </UButton>
          <UButton size="sm" variant="ghost" color="neutral" @click="dismissEnhancement">
            Dismiss
          </UButton>
        </div>
      </div>
    </Transition>

    <!-- Enhance error -->
    <UAlert
      v-if="enhanceError"
      color="error"
      variant="soft"
      icon="i-lucide-alert-circle"
      :description="enhanceError"
      :close-button="{ icon: 'i-lucide-x', color: 'neutral', variant: 'ghost', size: 'xs' }"
      @close="enhanceError = null"
    />

    <!-- Enhance controls row -->
    <div class="flex flex-wrap items-center gap-2">
      <!-- Mode toggle via UButtonGroup -->
      <UButtonGroup size="sm">
        <UButton
          v-for="m in modes"
          :key="m.value"
          :variant="enhanceMode === m.value ? 'solid' : 'soft'"
          :color="enhanceMode === m.value ? 'primary' : 'neutral'"
          @click="enhanceMode = m.value"
        >
          {{ m.label }}
        </UButton>
      </UButtonGroup>

      <UButton
        size="sm"
        variant="soft"
        color="neutral"
        icon="i-lucide-sparkles"
        :loading="isEnhancing"
        :disabled="!modelValue.trim() || isEnhancing"
        @click="enhancePrompt"
      >
        Enhance
      </UButton>
    </div>

    <!-- Playlist size row -->
    <div class="flex items-center gap-4">
      <span class="text-sm text-(--ui-text-muted) whitespace-nowrap shrink-0">
        Playlist size
      </span>
      <USlider
        :model-value="playlistSize"
        :min="10"
        :max="100"
        :step="5"
        color="primary"
        class="flex-1"
        @update:model-value="emit('update:playlistSize', $event)"
      />
      <span class="tabular text-sm font-semibold text-white w-20 text-right shrink-0">
        {{ playlistSize }} tracks
      </span>
    </div>

    <!-- Generate CTA -->
    <UButton
      size="xl"
      color="primary"
      :disabled="!canGenerate || !hasLibraryData"
      class="w-full justify-center font-display font-semibold tracking-tight glow-acid"
      icon="i-lucide-wand-2"
      @click="emit('submit', { prompt: modelValue, size: playlistSize })"
    >
      Generate Playlist
    </UButton>
  </div>
</template>
