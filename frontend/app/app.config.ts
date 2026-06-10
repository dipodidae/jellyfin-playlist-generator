// Nuxt UI v4 theme — wires the chartreuse-lime "acid" ramp (defined in main.css
// @theme) as the primary accent over a warm near-black neutral.
export default defineAppConfig({
  ui: {
    colors: {
      primary: 'acid',
      neutral: 'zinc',
    },
    button: {
      defaultVariants: {
        // tactile, slightly chunky default buttons
        size: 'md',
      },
    },
  },
})
