/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'Consolas', 'monospace'],
      },
      colors: {
        // DESIGN.md (Stripe-inspired): navy-tinted ink and neutrals instead of Tailwind's grey slate
        slate: { 50: '#f6f9fc', 100: '#eef2f8', 200: '#e3e8ee', 300: '#cdd6e1', 400: '#8898aa', 500: '#64748d', 600: '#425466', 700: '#273951', 800: '#1a2f47', 900: '#0d253d' },
        // brand indigo replaces the sky accent (focus rings, links, active states)
        sky: { 50: '#f1f0ff', 100: '#e4e2ff', 400: '#8f86ff', 500: '#665efd', 700: '#4434d4' },
        brand: { DEFAULT: '#533afd', deep: '#4434d4', press: '#2e2b8c', 900: '#1c1e54', 950: '#15173f' },
        // verdict + risk semantics; every colour is always paired with a word in the UI
        save: { 50: '#ecfdf5', 100: '#d1fae5', 600: '#059669', 700: '#047857' },
        kept: { 50: '#eef2ff', 100: '#e0e7ff', 600: '#4f46e5', 700: '#4338ca' },
        review: { 50: '#fffbeb', 100: '#fef3c7', 600: '#d97706', 700: '#b45309' },
        healthy: { 50: '#f0fdfa', 100: '#ccfbf1', 600: '#0d9488', 700: '#0f766e' },
        upsize: { 50: '#fff7ed', 100: '#ffedd5', 600: '#ea580c', 700: '#c2410c' },
        danger: { 50: '#fff1f2', 100: '#ffe4e6', 600: '#e11d48', 700: '#be123c' },
      },
      fontSize: { '2xs': ['0.6875rem', '1rem'] },
      // soft, blue-tinted depth (offset + blur), never a hard edge
      boxShadow: {
        card: '0 1px 1px rgba(13,37,61,0.04), 0 2px 6px -1px rgba(50,50,93,0.07)',
        pop: '0 13px 27px -5px rgba(50,50,93,0.20), 0 8px 16px -8px rgba(0,0,0,0.12)',
      },
    },
  },
  plugins: [],
}
