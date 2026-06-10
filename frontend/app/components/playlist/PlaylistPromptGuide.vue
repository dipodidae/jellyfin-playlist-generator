<script setup lang="ts">
const isOpen = ref(false)
</script>

<template>
  <div class="glass rounded-xl border border-(--ui-border) overflow-hidden">
    <button
      class="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-(--ui-text-muted) hover:text-white transition-colors cursor-pointer"
      @click="isOpen = !isOpen"
    >
      <span class="flex items-center gap-2">
        <UIcon name="i-lucide-lightbulb" class="size-4 text-acid-400" />
        How prompts work
      </span>
      <UIcon
        name="i-lucide-chevron-down"
        class="size-4 transition-transform duration-200"
        :class="{ 'rotate-180': isOpen }"
      />
    </button>

    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      leave-active-class="transition-all duration-150 ease-in"
      enter-from-class="opacity-0 max-h-0"
      enter-to-class="opacity-100 max-h-[2000px]"
      leave-from-class="opacity-100 max-h-[2000px]"
      leave-to-class="opacity-0 max-h-0"
    >
      <div v-show="isOpen" class="overflow-hidden border-t border-(--ui-border)">
        <div class="px-4 pb-5 pt-4 space-y-5 text-sm text-(--ui-text-muted)">
          <!-- How it works -->
          <div>
            <h4 class="font-display font-semibold text-white mb-1.5">What happens with your prompt</h4>
            <p class="leading-relaxed">
              Your text is analyzed to extract <strong class="text-acid-300">genres</strong>,
              <strong class="text-acid-300">moods</strong>,
              <strong class="text-acid-300">energy shape</strong>, and
              <strong class="text-acid-300">era</strong>.
              Tracks are then scored on 4 dimensions &mdash; energy, tempo, darkness, and texture &mdash;
              and sequenced so consecutive tracks transition smoothly.
            </p>
          </div>

          <!-- What to include -->
          <div>
            <h4 class="font-display font-semibold text-white mb-2">What the engine picks up on</h4>
            <ul class="space-y-2 ml-0.5">
              <li class="flex gap-2.5">
                <UIcon name="i-lucide-music" class="size-3.5 text-acid-400 shrink-0 mt-0.5" />
                <span><strong class="text-white">Genres &amp; subgenres</strong> &mdash; be specific. "melodic death metal" targets better than "metal". Sibling genres are included automatically (e.g. "coldwave" also pulls darkwave, post-punk, synth-pop).</span>
              </li>
              <li class="flex gap-2.5">
                <UIcon name="i-lucide-activity" class="size-3.5 text-acid-400 shrink-0 mt-0.5" />
                <span><strong class="text-white">Energy words</strong> shape the trajectory. Words like "build", "crescendo", "pump up" create a rising arc. "Wind down", "chill", "sleep" create a falling arc. "Party", "peak", "rave" build to a climax then resolve.</span>
              </li>
              <li class="flex gap-2.5">
                <UIcon name="i-lucide-palette" class="size-3.5 text-acid-400 shrink-0 mt-0.5" />
                <span><strong class="text-white">Mood &amp; atmosphere</strong> &mdash; dark, melancholic, ethereal, aggressive, triumphant, hypnotic, dreamy, raw, etc. These directly influence which dimensions get weighted more.</span>
              </li>
              <li class="flex gap-2.5">
                <UIcon name="i-lucide-calendar" class="size-3.5 text-acid-400 shrink-0 mt-0.5" />
                <span><strong class="text-white">Decades or year ranges</strong> &mdash; "80s", "1990-1999", "from 2015". Tracks near the target era get a scoring bonus; distant ones get a soft penalty.</span>
              </li>
              <li class="flex gap-2.5">
                <UIcon name="i-lucide-user" class="size-3.5 text-acid-400 shrink-0 mt-0.5" />
                <span><strong class="text-white">Artist references</strong> &mdash; "like Darkthrone", "similar to Cocteau Twins". Helps anchor the semantic search.</span>
              </li>
              <li class="flex gap-2.5">
                <UIcon name="i-lucide-ban" class="size-3.5 text-acid-400 shrink-0 mt-0.5" />
                <span><strong class="text-white">Exclusions</strong> &mdash; "no clean vocals", "avoid synths", "without blast beats". These are passed to the AI parser to filter results.</span>
              </li>
            </ul>
          </div>

          <!-- Arc types -->
          <div>
            <h4 class="font-display font-semibold text-white mb-2">Energy arc types</h4>
            <p class="mb-3 leading-relaxed">The playlist isn't just a shuffled bag of tracks. It follows an energy curve from start to finish. The shape is detected from your prompt:</p>
            <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <div
                v-for="arc in [
                  { name: 'Rise', desc: 'Builds energy. “workout”, “morning”, “crescendo”' },
                  { name: 'Fall', desc: 'Winds down. “relax”, “sleep”, “unwind”' },
                  { name: 'Peak', desc: 'Builds, climaxes, resolves. “party”, “rave”, “club”' },
                  { name: 'Valley', desc: 'Dips then returns. “introspective”, “meditation”, “focus”' },
                  { name: 'Wave', desc: 'Oscillates. “varied”, “eclectic”, “adventure”' },
                  { name: 'Journey', desc: 'Narrative arc with intro, build, climax, denouement. Default for genre-only prompts.' },
                ]"
                :key="arc.name"
                class="rounded-lg bg-(--ui-bg-elevated) border border-(--ui-border) px-3 py-2.5"
              >
                <span class="font-semibold text-acid-300 text-xs uppercase tracking-wide">{{ arc.name }}</span>
                <p class="text-xs mt-1 leading-snug">{{ arc.desc }}</p>
              </div>
            </div>
          </div>

          <!-- Do's and Don'ts -->
          <div class="grid sm:grid-cols-2 gap-4">
            <div>
              <h4 class="font-display font-semibold text-xs uppercase tracking-wider text-success mb-2 flex items-center gap-1.5">
                <UIcon name="i-lucide-check-circle" class="size-3.5" />
                Good prompts
              </h4>
              <ul class="space-y-1.5 text-xs leading-relaxed">
                <li>"<em>atmospheric black metal that builds from ambient intros to tremolo-picked walls of sound</em>" &mdash; specific genre + clear arc + texture description</li>
                <li>"<em>melancholic 80s darkwave and coldwave, like Clan of Xymox</em>" &mdash; genre + mood + era + artist reference</li>
                <li>"<em>workout thrash: start moderate, build to relentless speed</em>" &mdash; genre + explicit energy arc</li>
                <li>"<em>nocturnal ambient and dark folk for focus, no harsh vocals</em>" &mdash; mood + genres + activity + exclusion</li>
              </ul>
            </div>
            <div>
              <h4 class="font-display font-semibold text-xs uppercase tracking-wider text-error mb-2 flex items-center gap-1.5">
                <UIcon name="i-lucide-x-circle" class="size-3.5" />
                Too vague
              </h4>
              <ul class="space-y-1.5 text-xs leading-relaxed">
                <li>"<em>good music</em>" &mdash; too vague, no genre/mood signal for the engine to work with</li>
                <li>"<em>metal</em>" &mdash; overly broad. The genre "metal" covers everything from power metal to grindcore. Be specific.</li>
                <li>"<em>play track #4523</em>" &mdash; this is a prompt-driven search, not a track ID lookup</li>
                <li>"<em>something for a tuesday</em>" &mdash; day-of-week doesn't map to any musical dimension. Describe the mood or activity instead.</li>
              </ul>
            </div>
          </div>

          <!-- What to expect -->
          <div>
            <h4 class="font-display font-semibold text-white mb-2">What to expect</h4>
            <ul class="space-y-1.5 text-xs leading-relaxed">
              <li class="flex gap-2"><span class="text-acid-500 shrink-0">&bull;</span>Tracks are sequenced for smooth transitions &mdash; energy, tempo, genre overlap, and even duration ratios are considered between consecutive tracks.</li>
              <li class="flex gap-2"><span class="text-acid-500 shrink-0">&bull;</span>The same artist won't appear back-to-back (minimum 4 tracks apart), and no single style dominates the entire list.</li>
              <li class="flex gap-2"><span class="text-acid-500 shrink-0">&bull;</span>Tracks you've heard in recent playlists are deprioritized &mdash; generating the same prompt twice won't give identical results.</li>
              <li class="flex gap-2"><span class="text-acid-500 shrink-0">&bull;</span>Genre-focused prompts weight genre matching heavily (35%). Arc-focused prompts weight trajectory fit more (40%). Mixed prompts balance both.</li>
              <li class="flex gap-2"><span class="text-acid-500 shrink-0">&bull;</span>Longer playlists (50+ tracks) may pull from a broader pool and relax style constraints to fill positions.</li>
            </ul>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
