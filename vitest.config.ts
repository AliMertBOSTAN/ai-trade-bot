import { resolve } from 'path'
import { defineConfig } from 'vitest/config'

// Renderer/shared saf mantık testleri (Vitest). Node ortamı yeterli —
// DOM gereken testler için environment'ı 'jsdom' yapıp jsdom ekleyebilirsin.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    globals: false
  },
  resolve: {
    alias: {
      '@shared': resolve(__dirname, 'src/shared'),
      '@renderer': resolve(__dirname, 'src/renderer/src')
    }
  }
})
