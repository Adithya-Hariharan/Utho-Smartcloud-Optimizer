/** @type {import('tailwindcss').Config} */
// Every colour comes from CSS variables in src/theme.css (generated from DESIGN.md), as r g b channels.
const c = (name) => `rgb(var(--c-${name}) / <alpha-value>)`
const scale = (name, keys) => Object.fromEntries(keys.map((k) => [k, c(`${name}-${k}`)]))

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)'],
        mono: ['var(--font-mono)'],
      },
      colors: {
        slate: scale('slate', ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900']),
        canvas: c('canvas'),
        surface: c('surface'),
        'on-brand': c('on-brand'),
        ring: c('ring'),
        brand: { DEFAULT: c('brand-DEFAULT'), deep: c('brand-deep'), press: c('brand-press'), 900: c('brand-900'), 950: c('brand-950') },
        sky: scale('sky', ['50', '100', '400', '500', '700']),
        // verdict + risk semantics; every colour is always paired with a word in the UI
        save: scale('save', ['50', '100', '300', '600', '700']),
        kept: scale('kept', ['50', '100', '600', '700']),
        review: scale('review', ['50', '100', '600', '700']),
        healthy: scale('healthy', ['50', '100', '600', '700']),
        upsize: scale('upsize', ['50', '100', '300', '600', '700']),
        danger: scale('danger', ['50', '100', '600', '700']),
      },
      borderRadius: { sm: 'var(--r-sm)', md: 'var(--r-md)', lg: 'var(--r-lg)', xl: 'var(--r-xl)' },
      fontSize: { '2xs': ['0.6875rem', '1rem'] },
      boxShadow: { card: 'var(--shadow-card)', pop: 'var(--shadow-pop)' },
      transitionTimingFunction: { out: 'cubic-bezier(0.16, 1, 0.3, 1)' },
      keyframes: {
        'rise-in': { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'none' } },
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-in': { from: { transform: 'translateX(24px)', opacity: '0' }, to: { transform: 'none', opacity: '1' } },
        shimmer: { from: { backgroundPosition: '200% 0' }, to: { backgroundPosition: '-200% 0' } },
      },
      animation: {
        'rise-in': 'rise-in 260ms cubic-bezier(0.16, 1, 0.3, 1) both',
        'fade-in': 'fade-in 160ms ease-out both',
        'slide-in': 'slide-in 240ms cubic-bezier(0.16, 1, 0.3, 1) both',
        shimmer: 'shimmer 1.6s linear infinite',
      },
    },
  },
  plugins: [],
}
