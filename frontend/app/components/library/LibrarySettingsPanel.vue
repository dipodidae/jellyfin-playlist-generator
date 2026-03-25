<script setup lang="ts">
import { computed } from 'vue'
import type { LibraryStats } from '~/types/library'

const props = defineProps<{
  stats: LibraryStats
  isSyncing: boolean
}>()

const emit = defineEmits<{
  'full-sync': []
  'refresh-stats': []
}>()

const onCompleted = () => emit('refresh-stats')

const lastfm = useEnrichmentStream({ onCompleted })
const embeddings = useEnrichmentStream({ onCompleted })
const profiles = useEnrichmentStream({ onCompleted })
const clusters = useEnrichmentStream({ onCompleted })
const audio = useEnrichmentStream({ onCompleted })
const genreManifold = useEnrichmentStream({ onCompleted })
const metalArchives = useEnrichmentStream({ onCompleted })

const anyRunning = computed(() =>
  lastfm.isRunning.value || embeddings.isRunning.value
  || profiles.isRunning.value || clusters.isRunning.value || audio.isRunning.value
  || genreManifold.isRunning.value || metalArchives.isRunning.value,
)

function coveragePct(done: number | undefined, total: number): number {
  if (!total || !done) return 0
  return Math.round((done / total) * 100)
}

const embeddingPct = computed(() => coveragePct(props.stats.tracks_with_embeddings, props.stats.tracks))
const profilePct = computed(() => coveragePct(props.stats.tracks_with_profiles, props.stats.tracks))
const lastfmPct = computed(() => coveragePct(props.stats.artists_with_tags, props.stats.artists))
const clusterPct = computed(() => coveragePct(props.stats.artists_clustered, props.stats.artists))
const audioPct = computed(() => coveragePct(props.stats.tracks_with_audio_features, props.stats.tracks))
const genreManifoldPct = computed(() => coveragePct(props.stats.tracks_with_genre_probs, props.stats.tracks))
const metalArchivesPct = computed(() => coveragePct(props.stats.albums_with_legitimacy, props.stats.albums))

function coverageColor(pct: number): string {
  if (pct >= 80) return 'text-green-600 dark:text-green-400'
  if (pct >= 40) return 'text-yellow-600 dark:text-yellow-400'
  return 'text-red-500 dark:text-red-400'
}

const activeJob = computed(() => {
  if (lastfm.isRunning.value) return lastfm
  if (embeddings.isRunning.value) return embeddings
  if (profiles.isRunning.value) return profiles
  if (clusters.isRunning.value) return clusters
  if (audio.isRunning.value) return audio
  if (genreManifold.isRunning.value) return genreManifold
  if (metalArchives.isRunning.value) return metalArchives
  return null
})

const latestOutcome = computed(() => {
  const jobs = [lastfm, embeddings, profiles, clusters, audio, genreManifold, metalArchives]
  const failedJob = jobs.find(job => job.status.value === 'error' && job.error.value)
  if (failedJob) {
    return {
      tone: 'error' as const,
      title: `${failedJob.operationLabel.value} failed`,
      message: failedJob.error.value ?? '',
    }
  }

  const successfulJob = jobs.find(job => job.status.value === 'success' && job.lastFinishedMessage.value)
  if (successfulJob) {
    return {
      tone: 'success' as const,
      title: `${successfulJob.operationLabel.value} finished`,
      message: successfulJob.lastFinishedMessage.value,
    }
  }

  return null
})
</script>

<template>
  <div class="pt-3 border-t border-gray-200 dark:border-gray-800 space-y-3">
    <details class="rounded border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 px-3 py-2">
      <summary class="cursor-pointer text-sm font-medium text-gray-900 dark:text-white">
        How it works &amp; what each metric means
      </summary>
      <div class="mt-3 space-y-3 text-xs text-gray-600 dark:text-gray-300">
        <div>
          <div class="font-medium text-gray-900 dark:text-white">Recommended order</div>
          <div>1. Run <code>Full Sync</code> if the library is missing tracks or paths changed.</div>
          <div>2. Run <code>Last.fm</code> to fetch artist tags and similarities.</div>
          <div>3. Run <code>Embeddings</code> to build semantic search vectors.</div>
          <div>4. Run <code>Profiles</code> to generate trajectory-ready track features.</div>
          <div>5. Run <code>Rebuild Clusters</code> after embeddings exist.</div>
          <div>6. Run <code>Audio Analysis</code> if you want BPM and loudness features.</div>
          <div>7. Run <code>Genre Manifold</code> after embeddings and clusters exist — required for genre fidelity constraints.</div>
          <div>8. Run <code>Metal Archives</code> to scrape album ratings — feeds into album legitimacy scoring.</div>
        </div>
        <div>
          <div class="font-medium text-gray-900 dark:text-white">What to expect</div>
          <div>Only one long-running job should be active at a time.</div>
          <div>A running job shows progress here. When it finishes, you should see either a success or failure message.</div>
          <div>If a job ends unexpectedly, the UI now reports that instead of silently stopping.</div>
        </div>
        <div>
          <div class="font-medium text-gray-900 dark:text-white">When to use each button</div>
          <div><code>Full Sync</code> rescans files and metadata from disk.</div>
          <div><code>Last.fm</code> enriches artist metadata and can take a while on large libraries.</div>
          <div><code>Embeddings</code> and <code>Profiles</code> improve prompt matching and trajectory quality.</div>
          <div><code>Rebuild Clusters</code> depends on embeddings.</div>
          <div><code>Refresh</code> only reloads counters; it does not start work.</div>
        </div>
        <div>
          <div class="font-medium text-gray-900 dark:text-white">What each metric means</div>
          <div class="mt-1 space-y-1">
            <div><span class="text-gray-900 dark:text-white font-medium">Embeddings</span> — Semantic vectors computed for each track. The generator queries these to find candidates matching your prompt. Without them, playlist generation won't work.</div>
            <div><span class="text-gray-900 dark:text-white font-medium">Profiles</span> — Per-track scores across four dimensions: energy, darkness, tempo, and texture (0–1 each). These power the trajectory engine — they're what shapes how mood and intensity evolve across a playlist.</div>
            <div><span class="text-gray-900 dark:text-white font-medium">Last.fm Artists</span> — Genre tags and artist similarity data fetched from Last.fm. Used to enrich scoring and improve stylistic coherence between tracks.</div>
            <div><span class="text-gray-900 dark:text-white font-medium">Scene Clusters</span> — Artists grouped into stylistic scenes using embedding similarity. The engine uses these to ensure variety and smooth transitions between musical zones. The count shown is the number of distinct scenes.</div>
            <div><span class="text-gray-900 dark:text-white font-medium">Audio Features</span> — Acoustic measurements (BPM, loudness, brightness) extracted directly from audio files. Optional — profiles already cover the same dimensions via semantic analysis, but audio features can sharpen accuracy.</div>
            <div><span class="text-gray-900 dark:text-white font-medium">Genre Manifold</span> — Probabilistic genre identity vectors per track, built from kNN neighborhood votes, Last.fm tags, and cluster membership. Powers strict genre filtering and prevents adjacent-genre drift (e.g. thrash staying thrash, not bleeding into NWOBHM).</div>
            <div><span class="text-gray-900 dark:text-white font-medium">Metal Archives</span> — Album ratings and review counts scraped from Encyclopaedia Metallum. Matched to local albums via fuzzy title + year comparison. Feeds into a curation score that gently favours well-reviewed releases.</div>
          </div>
        </div>
      </div>
    </details>

    <!-- Coverage grid -->
    <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
      <!-- Embeddings -->
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <span class="text-gray-500 dark:text-gray-400 text-xs" title="Semantic vectors used to match tracks to your prompt. Required for generation.">Embeddings</span>
          <span :class="coverageColor(embeddingPct)" class="text-xs font-semibold">
            {{ embeddingPct }}%
          </span>
        </div>
        <div class="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            class="h-full bg-blue-500 rounded-full transition-all duration-500"
            :style="{ width: `${embeddingPct}%` }"
          />
        </div>
        <div class="text-xs text-gray-400">
          {{ (stats.tracks_with_embeddings ?? 0).toLocaleString() }} / {{ stats.tracks.toLocaleString() }} tracks
        </div>
      </div>

      <!-- Profiles -->
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <span class="text-gray-500 dark:text-gray-400 text-xs" title="4D scores (energy, darkness, tempo, texture) that drive the trajectory engine.">Profiles</span>
          <span :class="coverageColor(profilePct)" class="text-xs font-semibold">
            {{ profilePct }}%
          </span>
        </div>
        <div class="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            class="h-full bg-purple-500 rounded-full transition-all duration-500"
            :style="{ width: `${profilePct}%` }"
          />
        </div>
        <div class="text-xs text-gray-400">
          {{ (stats.tracks_with_profiles ?? 0).toLocaleString() }} / {{ stats.tracks.toLocaleString() }} tracks
        </div>
      </div>

      <!-- Last.fm -->
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <span class="text-gray-500 dark:text-gray-400 text-xs" title="Artists enriched with genre tags and similarity data from Last.fm.">Last.fm Artists</span>
          <span :class="coverageColor(lastfmPct)" class="text-xs font-semibold">
            {{ lastfmPct }}%
          </span>
        </div>
        <div class="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            class="h-full bg-red-500 rounded-full transition-all duration-500"
            :style="{ width: `${lastfmPct}%` }"
          />
        </div>
        <div class="text-xs text-gray-400">
          {{ (stats.artists_with_tags ?? 0).toLocaleString() }} / {{ stats.artists.toLocaleString() }} artists
        </div>
      </div>

      <!-- Clusters -->
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <span class="text-gray-500 dark:text-gray-400 text-xs" title="Artists grouped into stylistic scenes. Used for variety and smooth transitions.">Scene Clusters</span>
          <span :class="coverageColor(clusterPct)" class="text-xs font-semibold">
            {{ (stats.scene_clusters ?? 0) }} clusters
          </span>
        </div>
        <div class="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            class="h-full bg-amber-500 rounded-full transition-all duration-500"
            :style="{ width: `${clusterPct}%` }"
          />
        </div>
        <div class="text-xs text-gray-400">
          {{ (stats.artists_clustered ?? 0).toLocaleString() }} / {{ stats.artists.toLocaleString() }} artists
          <span v-if="stats.vector_index_built" class="ml-1 text-green-500">· index ✓</span>
        </div>
      </div>

      <!-- Audio Features -->
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <span class="text-gray-500 dark:text-gray-400 text-xs" title="BPM, loudness, and brightness extracted from audio files. Optional — profiles cover similar ground semantically.">Audio Features</span>
          <span :class="coverageColor(audioPct)" class="text-xs font-semibold">
            {{ audioPct }}%
          </span>
        </div>
        <div class="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            class="h-full bg-teal-500 rounded-full transition-all duration-500"
            :style="{ width: `${audioPct}%` }"
            :class="{ 'animate-pulse': audio.isRunning.value }"
          />
        </div>
        <div class="text-xs text-gray-400">
          {{ (stats.tracks_with_audio_features ?? 0).toLocaleString() }} / {{ stats.tracks.toLocaleString() }} tracks
        </div>
      </div>

      <!-- Genre Manifold -->
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <span class="text-gray-500 dark:text-gray-400 text-xs" title="Probabilistic genre identity vectors. Used for hard/soft genre constraints and drift prevention.">Genre Manifold</span>
          <span :class="coverageColor(genreManifoldPct)" class="text-xs font-semibold">
            {{ genreManifoldPct }}%
          </span>
        </div>
        <div class="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            class="h-full bg-indigo-500 rounded-full transition-all duration-500"
            :style="{ width: `${genreManifoldPct}%` }"
            :class="{ 'animate-pulse': genreManifold.isRunning.value }"
          />
        </div>
        <div class="text-xs text-gray-400">
          {{ (stats.tracks_with_genre_probs ?? 0).toLocaleString() }} / {{ stats.tracks.toLocaleString() }} tracks
        </div>
      </div>

      <!-- Metal Archives -->
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <span class="text-gray-500 dark:text-gray-400 text-xs" title="Album ratings and review counts scraped from Metal Archives. Used for album legitimacy scoring.">Metal Archives</span>
          <span :class="coverageColor(metalArchivesPct)" class="text-xs font-semibold">
            {{ metalArchivesPct }}%
          </span>
        </div>
        <div class="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            class="h-full bg-orange-500 rounded-full transition-all duration-500"
            :style="{ width: `${metalArchivesPct}%` }"
            :class="{ 'animate-pulse': metalArchives.isRunning.value }"
          />
        </div>
        <div class="text-xs text-gray-400">
          {{ (stats.albums_with_legitimacy ?? 0).toLocaleString() }} / {{ stats.albums.toLocaleString() }} albums
        </div>
      </div>
    </div>

    <!-- Active enrichment progress -->
    <div
      v-if="activeJob"
      class="rounded bg-gray-50 dark:bg-gray-800 px-3 py-2 text-xs space-y-1"
    >
      <div class="flex items-center justify-between text-gray-600 dark:text-gray-300">
        <span class="truncate">{{ activeJob.operationLabel.value }} · {{ activeJob.message.value || 'Running…' }}</span>
        <span class="shrink-0 ml-2 font-mono">{{ activeJob.progress.value }}%</span>
      </div>
      <div class="h-1 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          class="h-full bg-blue-500 rounded-full transition-all duration-300"
          :style="{ width: `${activeJob.progress.value}%` }"
        />
      </div>
    </div>

    <div
      v-if="latestOutcome"
      class="rounded px-3 py-2 text-xs"
      :class="latestOutcome.tone === 'error'
        ? 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300'
        : 'bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300'"
    >
      <div class="font-medium">{{ latestOutcome.title }}</div>
      <div class="mt-1">{{ latestOutcome.message }}</div>
    </div>

    <div class="flex flex-wrap gap-2 pt-1">
      <UButton
        :loading="isSyncing"
        :disabled="isSyncing || anyRunning"
        variant="outline"
        size="xs"
        @click="emit('full-sync')"
      >
        Full Sync
      </UButton>
      <UButton
        :loading="lastfm.isRunning.value"
        :disabled="anyRunning"
        variant="outline"
        size="xs"
        @click="lastfm.run('/api/enrich/lastfm/stream', 'Last.fm enrichment')"
      >
        Last.fm
      </UButton>
      <UButton
        :loading="embeddings.isRunning.value"
        :disabled="anyRunning"
        variant="outline"
        size="xs"
        @click="embeddings.run('/api/enrich/embeddings/stream', 'Embedding generation')"
      >
        Embeddings
      </UButton>
      <UButton
        :loading="profiles.isRunning.value"
        :disabled="anyRunning"
        variant="outline"
        size="xs"
        @click="profiles.run('/api/enrich/profiles/stream', 'Profile generation')"
      >
        Profiles
      </UButton>
      <UButton
        :loading="clusters.isRunning.value"
        :disabled="anyRunning"
        variant="outline"
        size="xs"
        @click="clusters.run('/api/enrich/clusters/stream', 'Scene clustering')"
      >
        Rebuild Clusters
      </UButton>
      <UButton
        :loading="audio.isRunning.value"
        :disabled="anyRunning"
        variant="outline"
        size="xs"
        @click="audio.run('/api/enrich/audio/stream', 'Audio analysis')"
      >
        Audio Analysis
      </UButton>
      <UButton
        :loading="genreManifold.isRunning.value"
        :disabled="anyRunning"
        variant="outline"
        size="xs"
        @click="genreManifold.run('/api/enrich/genre-manifold/stream', 'Genre manifold build')"
      >
        Genre Manifold
      </UButton>
      <UButton
        :loading="metalArchives.isRunning.value"
        :disabled="anyRunning"
        variant="outline"
        size="xs"
        @click="metalArchives.run('/api/enrich/metal-archives/stream', 'Metal Archives enrichment')"
      >
        Metal Archives
      </UButton>
      <UButton
        variant="ghost"
        size="xs"
        :disabled="anyRunning"
        @click="emit('refresh-stats')"
      >
        Refresh
      </UButton>
    </div>
  </div>
</template>
