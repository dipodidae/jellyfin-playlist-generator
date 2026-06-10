<script setup lang="ts">
import { useJellyfinTools } from '~/composables/useJellyfinTools'

const { running, progress, message, stats, error, fixReleaseDates } = useJellyfinTools()
</script>

<template>
  <div class="rise-in space-y-8 pb-16">

    <!-- Page header -->
    <div>
      <h1 class="font-display text-3xl font-bold tracking-tight text-white">
        Tools
      </h1>
      <p class="mt-1 text-sm text-(--ui-text-muted)">
        One-off maintenance operations for your library.
      </p>
    </div>

    <!-- Fix Jellyfin Release Dates tool card -->
    <SectionCard>
      <div class="space-y-5">

        <!-- Tool header -->
        <div class="flex items-start gap-3">
          <div class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-acid-400/10 ring-1 ring-acid-400/30">
            <UIcon name="i-lucide-calendar-check" class="size-5 text-acid-400" />
          </div>
          <div>
            <h2 class="font-display text-lg font-semibold tracking-tight text-white">
              Fix Jellyfin release dates
            </h2>
            <p class="mt-0.5 text-sm text-(--ui-text-muted) leading-relaxed max-w-xl">
              Pushes the app's resolved original release dates (first-pressing year from Discogs&nbsp;/&nbsp;MusicBrainz)
              onto matching Jellyfin albums, and locks the fields so Jellyfin won't revert them.
              Album-level — reissues get their original date.
            </p>
          </div>
        </div>

        <!-- CTA -->
        <UButton
          color="primary"
          size="lg"
          icon="i-lucide-play-circle"
          :loading="running"
          :disabled="running"
          class="glow-acid"
          @click="fixReleaseDates"
        >
          {{ running ? 'Fixing…' : 'Fix Jellyfin release dates' }}
        </UButton>

        <!-- Progress bar + message -->
        <Transition name="fade">
          <div v-if="running || message" class="space-y-2">
            <UProgress
              :model-value="progress"
              color="primary"
              size="sm"
              class="w-full"
            />
            <p class="text-xs text-(--ui-text-dimmed) tabular">{{ message }}</p>
          </div>
        </Transition>

        <!-- Error alert -->
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-circle-x"
          title="Operation failed"
          :description="error"
        />

        <!-- Result stats -->
        <div v-if="stats" class="space-y-3">
          <div class="h-px bg-(--ui-border)" />
          <p class="text-xs font-semibold uppercase tracking-wider text-(--ui-text-dimmed)">Results</p>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatPill label="Updated" :value="stats.updated" />
            <StatPill label="Matched" :value="stats.matched" />
            <StatPill label="Unmatched" :value="stats.skipped_no_jellyfin_match" />
            <StatPill label="Failed" :value="stats.failed" />
          </div>
        </div>

        <!-- Error list from stats -->
        <div v-if="stats && stats.errors && stats.errors.length" class="mt-1 space-y-1">
          <p class="text-xs font-semibold uppercase tracking-wider text-(--ui-text-dimmed)">Error details</p>
          <ul class="space-y-1 pl-3">
            <li
              v-for="(e, i) in stats.errors"
              :key="i"
              class="flex items-start gap-2 text-xs text-red-400"
            >
              <UIcon name="i-lucide-dot" class="mt-0.5 size-3 shrink-0" />
              {{ e }}
            </li>
          </ul>
        </div>

      </div>
    </SectionCard>

  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from,
.fade-leave-to { opacity: 0; }
</style>
