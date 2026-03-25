/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: { 900: '#0F172A', 800: '#1E293B', 700: '#334155' },
      },
    },
  },
  plugins: [],
}
