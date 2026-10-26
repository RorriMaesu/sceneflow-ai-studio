import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins: [react()], base: './', build: { outDir: 'dist', sourcemap: false,rollupOptions:{output:{manualChunks(id){if(id.includes('/node_modules/zod/'))return 'validation';if(id.includes('/node_modules/motion')||id.includes('/node_modules/framer-motion'))return 'motion';if(id.includes('/node_modules/react')||id.includes('/node_modules/scheduler/'))return 'react'}}} }, server: { port: 5173, strictPort: true } })
