import {defineConfig} from 'vite';
import {hydrogen} from '@shopify/hydrogen/vite';
import {reactRouter} from '@react-router/dev/vite';
import tsconfigPaths from 'vite-tsconfig-paths';

export default defineConfig({
  plugins: [hydrogen(), reactRouter(), tsconfigPaths()],
  build: {
    assetsInlineLimit: 0,
    target: 'esnext',
  },
  ssr: {
    external: ['fs', 'path', 'stream', 'crypto', 'util'],
    optimizeDeps: {
      include: ['@react-router/node', '@react-router/express'],
    },
  },
});
