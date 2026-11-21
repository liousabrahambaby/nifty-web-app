import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { existsSync, copyFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

const root = fileURLToPath(new URL('.', import.meta.url))

// analyze.py writes data.json to the project root. The dev server already serves it
// from there; this copies it into dist/ so the built site has it too.
function copyDataJson() {
  let outDir
  return {
    name: 'copy-data-json',
    apply: 'build',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir)
    },
    closeBundle() {
      const file = resolve(root, 'data.json')
      if (existsSync(file)) copyFileSync(file, resolve(outDir, 'data.json'))
      else console.warn('\n[copy-data-json] No data.json yet. Run `python analyze.py` (or `--demo`) first.')
    },
  }
}

export default defineConfig({
  // Relative paths, so the site works at https://<user>.github.io/<repo>/ without hard-coding the repo name.
  base: './',
  plugins: [react(), copyDataJson()],
  build: {
    // Plotly is ~3.5 MB on its own; that's expected.
    chunkSizeWarningLimit: 5000,
    rollupOptions: {
      // Three separate pages, so the existing URLs (login.html, kite.html) keep working,
      // including the Kite redirect URL.
      input: {
        main: resolve(root, 'index.html'),
        login: resolve(root, 'login.html'),
        kite: resolve(root, 'kite.html'),
      },
    },
  },
})
