<script setup lang="ts">
defineProps<{
  prompt: string
  progress: number
  progressSteps: { message: string; done: boolean }[]
}>()
</script>

<template>
  <SectionCard>
    <div class="space-y-5 py-2">
      <!-- Animated EQ indicator + prompt -->
      <div class="flex flex-col items-center gap-3 text-center">
        <!-- Equalizer bars -->
        <div class="flex items-end gap-[3px] h-6">
          <span
            v-for="n in 5"
            :key="n"
            class="eq-bar inline-block w-1.5 rounded-sm bg-acid-400"
            :style="{ animationDelay: `${(n - 1) * 0.18}s`, height: '100%' }"
          />
        </div>

        <p class="font-display text-base font-semibold text-white leading-snug max-w-prose px-4">
          "{{ prompt }}"
        </p>
        <p class="text-xs text-(--ui-text-dimmed) tracking-wide uppercase">Generating your playlist&hellip;</p>
      </div>

      <!-- Progress bar -->
      <UProgress
        :value="progress"
        size="sm"
        color="primary"
        :ui="{
          track: 'bg-(--ui-bg-elevated)',
        }"
      />

      <!-- Stage list -->
      <ProgressStageList :steps="progressSteps" />
    </div>
  </SectionCard>
</template>
