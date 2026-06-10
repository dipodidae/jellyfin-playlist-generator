<script setup lang="ts">
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart, HeatmapChart } from 'echarts/charts'
import {
  TooltipComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  VisualMapComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  HeatmapChart,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  VisualMapComponent,
  DataZoomComponent,
])

interface EvalRun {
  id: string
  timestamp: string
  means: Record<string, number>
  raw: Record<string, number[]>
  per_prompt_weighted: number[]
  prompt_results: Record<string, {
    scores: Record<string, number>
    weighted_score: number
    playlist_title: string
    prompt: string
  }>
  diagnosis_summary: string | null
  systemic_issues: Array<{
    category: string
    severity: string
    description: string
  }>
}

const colorMode = useColorMode()
const loading = ref(true)
const error = ref<string | null>(null)
const runs = ref<EvalRun[]>([])
const selectedRun = ref<EvalRun | null>(null)

async function fetchRuns() {
  loading.value = true
  error.value = null
  try {
    const data = await $fetch<{ runs: EvalRun[]; total: number }>('/api/eval-runs')
    runs.value = data.runs
  } catch (e: any) {
    error.value = e?.message || 'Failed to load eval runs'
  } finally {
    loading.value = false
  }
}

onMounted(() => fetchRuns())

// Prompt display names
const promptLabels: Record<string, string> = {
  ambient_doom_arc: 'Ambient Doom',
  thrash_energy: 'Thrash Energy',
  darkwave_steady: 'Darkwave Steady',
  doom_journey: 'Doom Journey',
  black_metal_raw: 'Black Metal',
  industrial_ritual: 'Industrial Ritual',
  post_punk_goth: 'Post-Punk Goth',
  jazz_nocturnal: 'Jazz Nocturnal',
  shoegaze_dreampop: 'Shoegaze Dream',
}

const promptKeys = [
  'ambient_doom_arc', 'thrash_energy', 'darkwave_steady',
  'doom_journey', 'black_metal_raw', 'industrial_ritual',
  'post_punk_goth', 'jazz_nocturnal', 'shoegaze_dreampop',
]

const dimensionColors: Record<string, string> = {
  arc: '#f59e0b',
  genre: '#10b981',
  transition: '#6366f1',
  fidelity: '#ec4899',
  curation: '#8b5cf6',
  overall: '#ef4444',
}

const dimensionLabels: Record<string, string> = {
  arc: 'Arc',
  genre: 'Genre',
  transition: 'Transitions',
  fidelity: 'Fidelity',
  curation: 'Curation',
  overall: 'Overall',
}

// Format timestamp for display
function formatTs(ts: string): string {
  const d = new Date(ts)
  return `${(d.getMonth() + 1).toString().padStart(2, '0')}/${d.getDate().toString().padStart(2, '0')} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

// Short label for x-axis
function shortLabel(idx: number): string {
  return `#${idx + 1}`
}

// ===== Chart 1: Overall Score Progression =====
const overallOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  const overallScores = runs.value.map(r => r.means.overall ?? 0)
  const labels = runs.value.map((_, i) => shortLabel(i))

  const best = Math.max(...overallScores)
  const bestIdx = overallScores.indexOf(best)

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: isDark ? '#1f2937' : '#fff',
      borderColor: isDark ? '#374151' : '#e5e7eb',
      textStyle: { color: isDark ? '#e5e7eb' : '#1f2937' },
      formatter: (params: any[]) => {
        const p = params[0]
        const run = runs.value[p.dataIndex]
        const ts = formatTs(run.timestamp)
        return `<b>Run ${p.dataIndex + 1}</b> (${ts})<br/>Overall: <b>${p.value.toFixed(2)}</b>`
      },
    },
    grid: { left: 50, right: 30, top: 40, bottom: 50 },
    xAxis: {
      type: 'category' as const,
      data: labels,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 11 },
      axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
    },
    yAxis: {
      type: 'value' as const,
      min: 3,
      max: 8,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280' },
      splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
    },
    series: [
      {
        type: 'line',
        data: overallScores,
        smooth: true,
        symbol: 'circle',
        symbolSize: (value: number, params: any) => params.dataIndex === bestIdx ? 14 : 8,
        lineStyle: {
          color: '#ef4444',
          width: 3,
        },
        itemStyle: {
          color: (params: any) => params.dataIndex === bestIdx ? '#22c55e' : '#ef4444',
          borderColor: isDark ? '#111827' : '#fff',
          borderWidth: 2,
        },
        areaStyle: {
          color: {
            type: 'linear' as const,
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: isDark ? 'rgba(239,68,68,0.25)' : 'rgba(239,68,68,0.15)' },
              { offset: 1, color: 'rgba(239,68,68,0)' },
            ],
          },
        },
        markLine: {
          silent: true,
          data: [
            {
              yAxis: best,
              label: {
                formatter: `Best: ${best.toFixed(2)}`,
                color: '#22c55e',
                fontSize: 11,
              },
              lineStyle: { color: '#22c55e', type: 'dashed' as const, width: 1 },
            },
          ],
        },
      },
    ],
  }
})

// ===== Chart 2: Dimension Scores Over Time =====
const dimensionOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  const dims = ['arc', 'genre', 'transition', 'fidelity', 'curation']
  const labels = runs.value.map((_, i) => shortLabel(i))

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: isDark ? '#1f2937' : '#fff',
      borderColor: isDark ? '#374151' : '#e5e7eb',
      textStyle: { color: isDark ? '#e5e7eb' : '#1f2937' },
      formatter: (params: any[]) => {
        const run = runs.value[params[0].dataIndex]
        const ts = formatTs(run.timestamp)
        let html = `<b>Run ${params[0].dataIndex + 1}</b> (${ts})<br/>`
        for (const p of params) {
          html += `${p.marker} ${p.seriesName}: <b>${p.value.toFixed(2)}</b><br/>`
        }
        return html
      },
    },
    legend: {
      data: dims.map(d => dimensionLabels[d]),
      textStyle: { color: isDark ? '#9ca3af' : '#4b5563', fontSize: 12 },
      top: 0,
    },
    grid: { left: 50, right: 30, top: 40, bottom: 50 },
    xAxis: {
      type: 'category' as const,
      data: labels,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 11 },
      axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
    },
    yAxis: {
      type: 'value' as const,
      min: 3,
      max: 8,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280' },
      splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
    },
    series: dims.map(dim => ({
      name: dimensionLabels[dim],
      type: 'line' as const,
      data: runs.value.map(r => r.means[dim] ?? 0),
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { color: dimensionColors[dim], width: 2 },
      itemStyle: { color: dimensionColors[dim] },
    })),
  }
})

// ===== Chart 3: Per-Prompt Heatmap =====
const heatmapOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  const runLabels = runs.value.map((_, i) => shortLabel(i))

  // Build heatmap data: [runIndex, promptIndex, score]
  const data: [number, number, number][] = []
  runs.value.forEach((run, ri) => {
    promptKeys.forEach((pk, pi) => {
      const score = run.prompt_results[pk]?.weighted_score ?? 0
      data.push([ri, pi, score])
    })
  })

  return {
    tooltip: {
      formatter: (params: any) => {
        const [ri, pi, score] = params.data
        const run = runs.value[ri]
        const ts = formatTs(run.timestamp)
        const prompt = promptLabels[promptKeys[pi]]
        const title = run.prompt_results[promptKeys[pi]]?.playlist_title || ''
        return `<b>${prompt}</b><br/>Run ${ri + 1} (${ts})<br/>Score: <b>${score.toFixed(1)}</b>${title ? `<br/><i>${title}</i>` : ''}`
      },
    },
    grid: { left: 120, right: 60, top: 10, bottom: 50 },
    xAxis: {
      type: 'category' as const,
      data: runLabels,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 11 },
      axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
      splitArea: { show: false },
    },
    yAxis: {
      type: 'category' as const,
      data: promptKeys.map(k => promptLabels[k]),
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 12 },
      axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
      splitArea: { show: false },
    },
    visualMap: {
      min: 2,
      max: 8,
      calculable: true,
      orient: 'vertical' as const,
      right: 0,
      top: 'center',
      textStyle: { color: isDark ? '#9ca3af' : '#6b7280' },
      inRange: {
        color: isDark
          ? ['#450a0a', '#991b1b', '#b45309', '#ca8a04', '#65a30d', '#16a34a', '#059669']
          : ['#fef2f2', '#fecaca', '#fed7aa', '#fef08a', '#bbf7d0', '#86efac', '#34d399'],
      },
    },
    series: [{
      type: 'heatmap',
      data,
      label: {
        show: true,
        color: isDark ? '#e5e7eb' : '#1f2937',
        fontSize: 10,
        formatter: (params: any) => params.data[2].toFixed(1),
      },
      itemStyle: {
        borderColor: isDark ? '#111827' : '#fff',
        borderWidth: 2,
        borderRadius: 3,
      },
    }],
  }
})

// ===== Chart 4: Per-Prompt Latest vs Best Comparison =====
const comparisonOption = computed(() => {
  const isDark = colorMode.value === 'dark'
  if (runs.value.length === 0) return null

  const latest = runs.value[runs.value.length - 1]

  // Find best overall run
  let bestRun = runs.value[0]
  for (const r of runs.value) {
    if ((r.means.overall ?? 0) > (bestRun.means.overall ?? 0)) bestRun = r
  }

  const prompts = promptKeys.map(k => promptLabels[k])
  const latestScores = promptKeys.map(k => latest.prompt_results[k]?.weighted_score ?? 0)
  const bestScores = promptKeys.map(k => bestRun.prompt_results[k]?.weighted_score ?? 0)

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: isDark ? '#1f2937' : '#fff',
      borderColor: isDark ? '#374151' : '#e5e7eb',
      textStyle: { color: isDark ? '#e5e7eb' : '#1f2937' },
    },
    legend: {
      data: ['Latest Run', 'Best Run'],
      textStyle: { color: isDark ? '#9ca3af' : '#4b5563' },
      top: 0,
    },
    grid: { left: 120, right: 30, top: 40, bottom: 20 },
    xAxis: {
      type: 'value' as const,
      min: 0,
      max: 10,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280' },
      splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
    },
    yAxis: {
      type: 'category' as const,
      data: prompts,
      axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 12 },
      axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
    },
    series: [
      {
        name: 'Latest Run',
        type: 'bar',
        data: latestScores,
        itemStyle: {
          color: isDark ? '#6366f1' : '#818cf8',
          borderRadius: [0, 4, 4, 0],
        },
        barGap: '10%',
        barMaxWidth: 20,
      },
      {
        name: 'Best Run',
        type: 'bar',
        data: bestScores,
        itemStyle: {
          color: isDark ? '#22c55e' : '#4ade80',
          borderRadius: [0, 4, 4, 0],
        },
        barMaxWidth: 20,
      },
    ],
  }
})

// ===== Stats =====
const stats = computed(() => {
  if (runs.value.length === 0) return null
  const scores = runs.value.map(r => r.means.overall ?? 0)
  const best = Math.max(...scores)
  const worst = Math.min(...scores)
  const latest = scores[scores.length - 1]
  const delta = runs.value.length > 1 ? latest - scores[0] : 0
  return { best, worst, latest, delta, total: runs.value.length }
})

// Severity badge color
function severityColor(s: string): 'error' | 'warning' | 'info' {
  if (s === 'HIGH' || s === 'CRITICAL') return 'error'
  if (s === 'MEDIUM') return 'warning'
  return 'info'
}
</script>

<template>
  <div class="rise-in pb-16">

    <!-- Loading -->
    <div v-if="loading" class="flex flex-col items-center justify-center py-24 gap-4">
      <div class="relative size-12">
        <div class="absolute inset-0 rounded-full border-2 border-acid-400/20" />
        <div class="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-acid-400" />
      </div>
      <p class="text-sm text-(--ui-text-muted)">Loading eval runs…</p>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="flex flex-col items-center justify-center py-24 gap-5">
      <UIcon name="i-lucide-circle-x" class="size-12 text-red-400" />
      <div class="text-center">
        <p class="font-display text-lg font-semibold text-white">Failed to load data</p>
        <p class="mt-1 text-sm text-(--ui-text-muted)">{{ error }}</p>
      </div>
      <UButton variant="soft" icon="i-lucide-refresh-cw" @click="fetchRuns()">
        Retry
      </UButton>
    </div>

    <!-- Data -->
    <div v-else class="space-y-6">

      <!-- Page header -->
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 class="font-display text-3xl font-bold tracking-tight text-white">
            Eval Runs
          </h1>
          <p class="mt-1 text-sm text-(--ui-text-muted)">
            {{ runs.length }} evaluation run{{ runs.length === 1 ? '' : 's' }}
            &middot; GPT-4o scored &middot; 9 prompts each
          </p>
        </div>
        <UButton
          variant="ghost"
          size="sm"
          icon="i-lucide-refresh-cw"
          :loading="loading"
          @click="fetchRuns()"
        >
          Refresh
        </UButton>
      </div>

      <!-- KPI stat pills -->
      <div v-if="stats" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div class="glass rounded-2xl px-4 py-3.5">
          <p class="text-[11px] font-medium uppercase tracking-wider text-(--ui-text-dimmed)">Latest</p>
          <p class="tabular mt-1 font-display text-2xl font-bold text-white">{{ stats.latest.toFixed(2) }}</p>
        </div>
        <div class="glass rounded-2xl px-4 py-3.5">
          <p class="text-[11px] font-medium uppercase tracking-wider text-(--ui-text-dimmed)">Best</p>
          <p class="tabular mt-1 font-display text-2xl font-bold text-acid-400">{{ stats.best.toFixed(2) }}</p>
        </div>
        <div class="glass rounded-2xl px-4 py-3.5">
          <p class="text-[11px] font-medium uppercase tracking-wider text-(--ui-text-dimmed)">Worst</p>
          <p class="tabular mt-1 font-display text-2xl font-bold text-red-400">{{ stats.worst.toFixed(2) }}</p>
        </div>
        <div class="glass rounded-2xl px-4 py-3.5">
          <p class="text-[11px] font-medium uppercase tracking-wider text-(--ui-text-dimmed)">Trend</p>
          <p
            class="tabular mt-1 font-display text-2xl font-bold"
            :class="stats.delta >= 0 ? 'text-acid-400' : 'text-red-400'"
          >
            {{ stats.delta >= 0 ? '+' : '' }}{{ stats.delta.toFixed(2) }}
          </p>
        </div>
      </div>

      <!-- Score Progression chart -->
      <SectionCard title="Score Progression">
        <p class="text-sm text-(--ui-text-muted)">
          Overall weighted score across all 9 prompts per run. Green dot marks the best run.
        </p>
        <VChart :option="overallOption" style="height: 300px" autoresize />
      </SectionCard>

      <!-- Dimension Breakdown chart -->
      <SectionCard title="Dimension Breakdown">
        <p class="text-sm text-(--ui-text-muted)">
          How each scoring dimension evolved across runs.
        </p>
        <VChart :option="dimensionOption" style="height: 350px" autoresize />
      </SectionCard>

      <!-- Per-Prompt Heatmap -->
      <SectionCard title="Per-Prompt Heatmap">
        <p class="text-sm text-(--ui-text-muted)">
          Weighted score per prompt across all runs. Hover for playlist titles.
        </p>
        <VChart :option="heatmapOption" style="height: 400px" autoresize />
      </SectionCard>

      <!-- Latest vs Best Comparison -->
      <SectionCard v-if="comparisonOption" title="Latest vs Best">
        <p class="text-sm text-(--ui-text-muted)">
          Per-prompt comparison between the most recent run and the best overall run.
        </p>
        <VChart :option="comparisonOption" style="height: 400px" autoresize />
      </SectionCard>

      <!-- Run History -->
      <SectionCard title="Run History">
        <div class="space-y-2">
          <button
            v-for="(run, idx) in [...runs].reverse()"
            :key="run.id"
            class="w-full rounded-xl border px-4 py-3 text-left transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-acid-400/50"
            :class="selectedRun?.id === run.id
              ? 'border-acid-400/40 bg-acid-400/8'
              : 'border-(--ui-border) hover:border-acid-400/20 hover:bg-(--ui-bg-elevated)'"
            @click="selectedRun = selectedRun?.id === run.id ? null : run"
          >
            <!-- Run summary row -->
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <span class="tabular w-8 text-xs font-mono text-(--ui-text-dimmed)">#{{ runs.length - idx }}</span>
                <span class="text-sm text-(--ui-text-muted)">{{ formatTs(run.timestamp) }}</span>
              </div>
              <div class="flex items-center gap-4">
                <span
                  class="tabular text-sm font-semibold"
                  :class="run.means.overall === stats?.best ? 'text-acid-400' : 'text-white'"
                >
                  {{ run.means.overall?.toFixed(2) }}
                </span>
                <span
                  v-if="idx < runs.length - 1"
                  class="tabular text-xs font-mono"
                  :class="(run.means.overall ?? 0) - (runs[runs.length - idx - 2]?.means?.overall ?? 0) >= 0 ? 'text-acid-400' : 'text-red-400'"
                >
                  {{ ((run.means.overall ?? 0) - (runs[runs.length - idx - 2]?.means?.overall ?? 0)) >= 0 ? '+' : '' }}{{ ((run.means.overall ?? 0) - (runs[runs.length - idx - 2]?.means?.overall ?? 0)).toFixed(2) }}
                </span>
                <UIcon
                  :name="selectedRun?.id === run.id ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
                  class="size-3.5 text-(--ui-text-dimmed)"
                />
              </div>
            </div>

            <!-- Expanded details -->
            <div v-if="selectedRun?.id === run.id" class="mt-4 space-y-4" @click.stop>

              <!-- Dimension scores -->
              <div class="grid grid-cols-3 gap-2 sm:grid-cols-5">
                <div
                  v-for="dim in ['arc', 'genre', 'transition', 'fidelity', 'curation']"
                  :key="dim"
                  class="rounded-xl border border-(--ui-border) bg-(--ui-bg-elevated)/40 px-2 py-2 text-center"
                >
                  <p class="text-[10px] uppercase tracking-wider text-(--ui-text-dimmed)">{{ dimensionLabels[dim] }}</p>
                  <p class="tabular mt-0.5 font-display text-lg font-bold" :style="{ color: dimensionColors[dim] }">
                    {{ run.means[dim]?.toFixed(1) }}
                  </p>
                </div>
              </div>

              <!-- Per-prompt scores -->
              <div class="space-y-0.5 overflow-hidden rounded-xl border border-(--ui-border)">
                <div
                  v-for="pk in promptKeys"
                  :key="pk"
                  class="flex items-center justify-between px-3 py-2 text-sm odd:bg-(--ui-bg-elevated)/40"
                  :class="(run.prompt_results[pk]?.weighted_score ?? 0) >= 6 ? 'bg-acid-400/5!' : (run.prompt_results[pk]?.weighted_score ?? 0) < 4 ? 'bg-red-500/5!' : ''"
                >
                  <span class="text-(--ui-text-muted)">{{ promptLabels[pk] }}</span>
                  <div class="flex items-center gap-3">
                    <span class="max-w-48 truncate text-xs text-(--ui-text-dimmed)">
                      {{ run.prompt_results[pk]?.playlist_title }}
                    </span>
                    <span
                      class="tabular font-mono font-bold"
                      :class="(run.prompt_results[pk]?.weighted_score ?? 0) >= 6 ? 'text-acid-400' : (run.prompt_results[pk]?.weighted_score ?? 0) < 4 ? 'text-red-400' : 'text-white'"
                    >
                      {{ run.prompt_results[pk]?.weighted_score?.toFixed(1) }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- Diagnosis -->
              <div v-if="run.diagnosis_summary" class="rounded-xl border border-(--ui-border) bg-(--ui-bg-elevated)/40 p-4">
                <p class="mb-1 text-xs font-semibold uppercase tracking-wider text-(--ui-text-dimmed)">Diagnosis</p>
                <p class="text-sm text-(--ui-text-muted)">{{ run.diagnosis_summary }}</p>
              </div>

              <!-- Systemic Issues -->
              <div v-if="run.systemic_issues.length > 0" class="space-y-2">
                <p class="text-xs font-semibold uppercase tracking-wider text-(--ui-text-dimmed)">Issues Found</p>
                <div
                  v-for="(issue, ii) in run.systemic_issues"
                  :key="ii"
                  class="flex items-start gap-2"
                >
                  <UBadge :color="severityColor(issue.severity)" size="xs" variant="subtle">
                    {{ issue.severity }}
                  </UBadge>
                  <span class="text-sm text-(--ui-text-muted)">{{ issue.description }}</span>
                </div>
              </div>

            </div>
          </button>
        </div>
      </SectionCard>

    </div>
  </div>
</template>
