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
const lastfmTracks = useEnrichmentStream({ onCompleted })
const embeddings = useEnrichmentStream({ onCompleted })
const profiles = useEnrichmentStream({ onCompleted })
const clusters = useEnrichmentStream({ onCompleted })
const audio = useEnrichmentStream({ onCompleted })
const genreManifold = useEnrichmentStream({ onCompleted })
const metalArchives = useEnrichmentStream({ onCompleted })
const musicbrainz = useEnrichmentStream({ onCompleted })
const rym = useEnrichmentStream({ onCompleted })

const anyRunning = computed(() =>
  lastfm.isRunning.value || lastfmTracks.isRunning.value || embeddings.isRunning.value
  || profiles.isRunning.value || clusters.isRunning.value || audio.isRunning.value
  || genreManifold.isRunning.value || metalArchives.isRunning.value
  || musicbrainz.isRunning.value || rym.isRunning.value,
)

function coveragePct(done: number | undefined, total: number): number {
  if (!total || !done) return 0
  return Math.round((done / total) * 100)
}

const embeddingPct = computed(() => coveragePct(props.stats.tracks_with_embeddings, props.stats.tracks))
const profilePct = computed(() => coveragePct(props.stats.tracks_with_profiles, props.stats.tracks))
const lastfmPct = computed(() => coveragePct(props.stats.artists_with_tags, props.stats.artists))
const lastfmTracksPct = computed(() => coveragePct(props.stats.tracks_with_lastfm_stats, props.stats.tracks))
const clusterPct = computed(() => coveragePct(props.stats.artists_clustered, props.stats.artists))
const audioPct = computed(() => coveragePct(props.stats.tracks_with_audio_features, props.stats.tracks))
const genreManifoldPct = computed(() => coveragePct(props.stats.tracks_with_genre_probs, props.stats.tracks))
const metalArchivesPct = computed(() => coveragePct(props.stats.albums_with_legitimacy, props.stats.albums))
const mbArtistPct = computed(() => coveragePct(props.stats.artists_with_mbid, props.stats.artists))
const mbAlbumPct = computed(() => coveragePct(props.stats.albums_with_mbid, props.stats.albums))
const rymPct = computed(() => coveragePct(props.stats.albums_with_rym, props.stats.albums))

type CoverageLevel = 'high' | 'mid' | 'low'

function coverageLevel(pct: number): CoverageLevel {
  if (pct >= 80) return 'high'
  if (pct >= 40) return 'mid'
  return 'low'
}

const coverageTextClass: Record<CoverageLevel, string> = {
  high: 'text-acid-400',
  mid: 'text-yellow-400',
  low: 'text-red-400',
}

const activeJob = computed(() => {
  if (musicbrainz.isRunning.value) return musicbrainz
  if (lastfm.isRunning.value) return lastfm
  if (lastfmTracks.isRunning.value) return lastfmTracks
  if (embeddings.isRunning.value) return embeddings
  if (profiles.isRunning.value) return profiles
  if (clusters.isRunning.value) return clusters
  if (audio.isRunning.value) return audio
  if (genreManifold.isRunning.value) return genreManifold
  if (metalArchives.isRunning.value) return metalArchives
  if (rym.isRunning.value) return rym
  return null
})

const latestOutcome = computed(() => {
  const jobs = [musicbrainz, lastfm, lastfmTracks, embeddings, profiles, clusters, audio, genreManifold, metalArchives, rym]
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

// Coverage metrics list for the grid
const metrics = computed(() => [
  {
    label: 'Embeddings',
    title: 'Semantic vectors used to match tracks to your prompt. Required for generation.',
    pct: embeddingPct.value,
    countLabel: `${(props.stats.tracks_with_embeddings ?? 0).toLocaleString()} / ${props.stats.tracks.toLocaleString()} tracks`,
    isRunning: embeddings.isRunning.value,
  },
  {
    label: 'Profiles',
    title: '4D scores (energy, darkness, tempo, texture) that drive the trajectory engine.',
    pct: profilePct.value,
    countLabel: `${(props.stats.tracks_with_profiles ?? 0).toLocaleString()} / ${props.stats.tracks.toLocaleString()} tracks`,
    isRunning: profiles.isRunning.value,
  },
  {
    label: 'Last.fm Artists',
    title: 'Artists enriched with genre tags and similarity data from Last.fm.',
    pct: lastfmPct.value,
    countLabel: `${(props.stats.artists_with_tags ?? 0).toLocaleString()} / ${props.stats.artists.toLocaleString()} artists`,
    isRunning: lastfm.isRunning.value,
  },
  {
    label: 'Last.fm Tracks',
    title: 'Per-track playcount and listener stats from Last.fm. Powers banger detection.',
    pct: lastfmTracksPct.value,
    countLabel: `${(props.stats.tracks_with_lastfm_stats ?? 0).toLocaleString()} / ${props.stats.tracks.toLocaleString()} tracks`,
    isRunning: lastfmTracks.isRunning.value,
  },
  {
    label: 'Scene Clusters',
    title: 'Artists grouped into stylistic scenes. Used for variety and smooth transitions.',
    pct: clusterPct.value,
    countLabel: `${(props.stats.artists_clustered ?? 0).toLocaleString()} / ${props.stats.artists.toLocaleString()} artists`,
    extra: props.stats.vector_index_built ? '· index ✓' : '',
    badge: `${(props.stats.scene_clusters ?? 0)} clusters`,
    isRunning: clusters.isRunning.value,
  },
  {
    label: 'Audio Features',
    title: 'BPM, loudness, and brightness extracted from audio files. Optional — profiles cover similar ground semantically.',
    pct: audioPct.value,
    countLabel: `${(props.stats.tracks_with_audio_features ?? 0).toLocaleString()} / ${props.stats.tracks.toLocaleString()} tracks`,
    isRunning: audio.isRunning.value,
  },
  {
    label: 'Genre Manifold',
    title: 'Probabilistic genre identity vectors. Used for hard/soft genre constraints and drift prevention.',
    pct: genreManifoldPct.value,
    countLabel: `${(props.stats.tracks_with_genre_probs ?? 0).toLocaleString()} / ${props.stats.tracks.toLocaleString()} tracks`,
    isRunning: genreManifold.isRunning.value,
  },
  {
    label: 'Metal Archives',
    title: 'Album ratings and review counts scraped from Metal Archives. Used for album legitimacy scoring.',
    pct: metalArchivesPct.value,
    countLabel: `${(props.stats.albums_with_legitimacy ?? 0).toLocaleString()} / ${props.stats.albums.toLocaleString()} albums`,
    isRunning: metalArchives.isRunning.value,
  },
  {
    label: 'MusicBrainz',
    title: 'MusicBrainz IDs resolved for artists and albums. Used as canonical join keys for RYM and other external data.',
    pct: mbArtistPct.value,
    countLabel: `${(props.stats.artists_with_mbid ?? 0).toLocaleString()} / ${props.stats.artists.toLocaleString()} artists · ${(props.stats.albums_with_mbid ?? 0).toLocaleString()} albums`,
    isRunning: musicbrainz.isRunning.value,
  },
  {
    label: 'RateYourMusic',
    title: 'Album ratings, genres, and descriptors from RateYourMusic. Enriches curation scoring, genre identity, and album adjacency transitions.',
    pct: rymPct.value,
    countLabel: `${(props.stats.albums_with_rym ?? 0).toLocaleString()} / ${props.stats.albums.toLocaleString()} albums`,
    extra: (props.stats.rym_adjacency_pairs ?? 0) > 0 ? `· ${(props.stats.rym_adjacency_pairs ?? 0).toLocaleString()} adjacency pairs` : '',
    isRunning: rym.isRunning.value,
  },
])
</script>

<template>
  <div class="pt-3 border-t border-(--ui-border) space-y-4">
    <!-- How it works collapsible -->
    <UCollapsible>
      <UButton
        variant="ghost"
        color="neutral"
        size="sm"
        icon="i-lucide-info"
        trailing-icon="i-lucide-chevron-down"
        class="w-full justify-between text-(--ui-text-muted) hover:text-white"
      >
        How it works &amp; what each metric means
      </UButton>

      <template #content>
        <div class="mt-3 rounded-xl border border-(--ui-border) bg-(--ui-bg-elevated)/40 p-4 space-y-4 text-xs text-(--ui-text-muted)">
          <div>
            <div class="font-semibold text-white mb-1">Recommended order</div>
            <div>1. Run <code class="font-mono text-acid-300">Full Sync</code> if the library is missing tracks or paths changed.</div>
            <div>2. Run <code class="font-mono text-acid-300">MusicBrainz</code> to resolve canonical IDs for artists and albums.</div>
            <div>3. Run <code class="font-mono text-acid-300">Last.fm</code> to fetch artist tags and similarities.</div>
            <div>3b. Run <code class="font-mono text-acid-300">Last.fm Tracks</code> to fetch per-track playcount and listener stats (feeds banger detection).</div>
            <div>4. Run <code class="font-mono text-acid-300">Embeddings</code> to build semantic search vectors.</div>
            <div>5. Run <code class="font-mono text-acid-300">Profiles</code> to generate trajectory-ready track features.</div>
            <div>6. Run <code class="font-mono text-acid-300">Rebuild Clusters</code> after embeddings exist.</div>
            <div>7. Run <code class="font-mono text-acid-300">Audio Analysis</code> if you want BPM and loudness features.</div>
            <div>8. Run <code class="font-mono text-acid-300">Genre Manifold</code> after embeddings and clusters exist — required for genre fidelity constraints.</div>
            <div>9. Run <code class="font-mono text-acid-300">Metal Archives</code> to scrape album ratings — feeds into album legitimacy scoring.</div>
            <div>10. Run <code class="font-mono text-acid-300">RYM</code> after MusicBrainz — scrapes album ratings, genres, and descriptors from RateYourMusic.</div>
          </div>
          <div>
            <div class="font-semibold text-white mb-1">What to expect</div>
            <div>Only one long-running job should be active at a time.</div>
            <div>A running job shows progress here. When it finishes, you should see either a success or failure message.</div>
            <div>If a job ends unexpectedly, the UI now reports that instead of silently stopping.</div>
          </div>
          <div>
            <div class="font-semibold text-white mb-1">When to use each button</div>
            <div><code class="font-mono text-acid-300">Full Sync</code> rescans files and metadata from disk.</div>
            <div><code class="font-mono text-acid-300">MusicBrainz</code> resolves canonical IDs — run before RYM or other external lookups.</div>
            <div><code class="font-mono text-acid-300">Last.fm</code> enriches artist metadata and can take a while on large libraries.</div>
            <div><code class="font-mono text-acid-300">Embeddings</code> and <code class="font-mono text-acid-300">Profiles</code> improve prompt matching and trajectory quality.</div>
            <div><code class="font-mono text-acid-300">Rebuild Clusters</code> depends on embeddings.</div>
            <div><code class="font-mono text-acid-300">RYM</code> scrapes album data from RateYourMusic — requires MusicBrainz IDs.</div>
            <div><code class="font-mono text-acid-300">Refresh</code> only reloads counters; it does not start work.</div>
          </div>
          <div>
            <div class="font-semibold text-white mb-1">What each metric means</div>
            <div class="mt-1 space-y-1.5">
              <div><span class="text-white font-medium">Embeddings</span> — Semantic vectors computed for each track. The generator queries these to find candidates matching your prompt. Without them, playlist generation won't work.</div>
              <div><span class="text-white font-medium">Profiles</span> — Per-track scores across four dimensions: energy, darkness, tempo, and texture (0–1 each). These power the trajectory engine — they're what shapes how mood and intensity evolve across a playlist.</div>
              <div><span class="text-white font-medium">Last.fm Artists</span> — Genre tags and artist similarity data fetched from Last.fm. Used to enrich scoring and improve stylistic coherence between tracks.</div>
              <div><span class="text-white font-medium">Last.fm Tracks</span> — Per-track playcount and listener counts from Last.fm. Powers banger detection — identifying standout tracks within each artist's catalog and across the library.</div>
              <div><span class="text-white font-medium">Scene Clusters</span> — Artists grouped into stylistic scenes using embedding similarity. The engine uses these to ensure variety and smooth transitions between musical zones. The count shown is the number of distinct scenes.</div>
              <div><span class="text-white font-medium">Audio Features</span> — Acoustic measurements (BPM, loudness, brightness) extracted directly from audio files. Optional — profiles already cover the same dimensions via semantic analysis, but audio features can sharpen accuracy.</div>
              <div><span class="text-white font-medium">Genre Manifold</span> — Probabilistic genre identity vectors per track, built from kNN neighborhood votes, Last.fm tags, and cluster membership. Powers strict genre filtering and prevents adjacent-genre drift (e.g. thrash staying thrash, not bleeding into NWOBHM).</div>
              <div><span class="text-white font-medium">Metal Archives</span> — Album ratings and review counts scraped from Encyclopaedia Metallum. Matched to local albums via fuzzy title + year comparison. Feeds into a curation score that gently favours well-reviewed releases.</div>
              <div><span class="text-white font-medium">MusicBrainz</span> — Canonical artist and album IDs resolved from the MusicBrainz database. These serve as join keys for external data sources like RateYourMusic.</div>
              <div><span class="text-white font-medium">RateYourMusic</span> — Album ratings, vote counts, genres, and descriptors scraped from RYM. Enriches curation scoring, embedding text, and builds an album adjacency graph used for transition bonuses during sequencing.</div>
            </div>
          </div>
        </div>
      </template>
    </UCollapsible>

    <!-- Coverage grid -->
    <div class="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
      <div
        v-for="metric in metrics"
        :key="metric.label"
        class="rounded-xl border border-(--ui-border) bg-(--ui-bg-elevated)/40 p-2.5 space-y-1.5"
        :class="{ 'ring-1 ring-acid-400/25': metric.isRunning }"
      >
        <!-- Label row -->
        <div class="flex items-center justify-between gap-1">
          <span
            class="text-[11px] font-medium text-(--ui-text-muted) truncate"
            :title="metric.title"
          >
            {{ metric.label }}
          </span>
          <span
            class="text-[11px] font-semibold tabular shrink-0"
            :class="coverageTextClass[coverageLevel(metric.pct)]"
          >
            {{ metric.badge ?? `${metric.pct}%` }}
          </span>
        </div>

        <!-- Progress bar -->
        <UProgress
          :model-value="metric.pct"
          :max="100"
          size="2xs"
          color="primary"
          :animation="metric.isRunning ? 'elastic' : undefined"
          :ui="{ base: 'bg-(--ui-bg-accented)' }"
        />

        <!-- Count label -->
        <div class="text-[11px] text-(--ui-text-dimmed) tabular leading-tight">
          {{ metric.countLabel }}
          <span v-if="metric.extra" class="ml-1 text-acid-400/70">{{ metric.extra }}</span>
        </div>
      </div>
    </div>

    <!-- Active enrichment console panel -->
    <div
      v-if="activeJob"
      class="glass rounded-xl p-3 space-y-2"
    >
      <div class="flex items-center justify-between gap-2 text-xs">
        <div class="flex items-center gap-2 min-w-0">
          <span class="inline-flex size-1.5 rounded-full bg-acid-400 animate-pulse shrink-0" />
          <span class="font-medium text-white truncate">{{ activeJob.operationLabel.value }}</span>
          <span class="text-(--ui-text-muted) truncate">{{ activeJob.message.value || 'Running…' }}</span>
        </div>
        <span class="tabular font-semibold text-acid-300 shrink-0">{{ activeJob.progress.value }}%</span>
      </div>
      <UProgress
        :model-value="activeJob.progress.value"
        :max="100"
        size="xs"
        color="primary"
        :ui="{ base: 'bg-(--ui-bg-accented)' }"
      />
    </div>

    <!-- Outcome alert -->
    <UAlert
      v-if="latestOutcome"
      :color="latestOutcome.tone === 'error' ? 'error' : 'success'"
      variant="subtle"
      :icon="latestOutcome.tone === 'error' ? 'i-lucide-circle-x' : 'i-lucide-circle-check'"
      :title="latestOutcome.title"
      :description="latestOutcome.message"
    />

    <!-- Action buttons -->
    <div class="flex flex-wrap gap-2 pt-1">
      <UButton
        :loading="isSyncing"
        :disabled="isSyncing || anyRunning"
        color="primary"
        variant="soft"
        size="xs"
        icon="i-lucide-refresh-cw"
        @click="emit('full-sync')"
      >
        Full Sync
      </UButton>
      <UButton
        :loading="lastfm.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="lastfm.run('/api/enrich/lastfm/stream', 'Last.fm enrichment')"
      >
        Last.fm
      </UButton>
      <UButton
        :loading="lastfmTracks.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="lastfmTracks.run('/api/enrich/lastfm-tracks/stream', 'Last.fm track enrichment')"
      >
        Last.fm Tracks
      </UButton>
      <UButton
        :loading="embeddings.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="embeddings.run('/api/enrich/embeddings/stream', 'Embedding generation')"
      >
        Embeddings
      </UButton>
      <UButton
        :loading="profiles.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="profiles.run('/api/enrich/profiles/stream', 'Profile generation')"
      >
        Profiles
      </UButton>
      <UButton
        :loading="clusters.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="clusters.run('/api/enrich/clusters/stream', 'Scene clustering')"
      >
        Rebuild Clusters
      </UButton>
      <UButton
        :loading="audio.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="audio.run('/api/enrich/audio/stream', 'Audio analysis')"
      >
        Audio Analysis
      </UButton>
      <UButton
        :loading="genreManifold.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="genreManifold.run('/api/enrich/genre-manifold/stream', 'Genre manifold build')"
      >
        Genre Manifold
      </UButton>
      <UButton
        :loading="metalArchives.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="metalArchives.run('/api/enrich/metal-archives/stream', 'Metal Archives enrichment')"
      >
        Metal Archives
      </UButton>
      <UButton
        :loading="musicbrainz.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="musicbrainz.run('/api/enrich/musicbrainz/stream', 'MusicBrainz resolution')"
      >
        MusicBrainz
      </UButton>
      <UButton
        :loading="rym.isRunning.value"
        :disabled="anyRunning"
        color="neutral"
        variant="outline"
        size="xs"
        @click="rym.run('/api/enrich/rym/stream', 'RYM enrichment')"
      >
        RYM
      </UButton>
      <UButton
        variant="ghost"
        color="neutral"
        size="xs"
        :disabled="anyRunning"
        icon="i-lucide-rotate-ccw"
        @click="emit('refresh-stats')"
      >
        Refresh
      </UButton>
    </div>
  </div>
</template>
