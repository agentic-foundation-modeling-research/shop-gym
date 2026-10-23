/** `synth_navigation`: main menu (linking every collection) and footer. */

import * as path from 'node:path';

import { z } from 'zod';

import { readJsonFile } from '../io.js';
import { completeStructured } from '../llm.js';
import { type SynthContext, cached, pretty, synthPrompt } from './context.js';
import {
  type CollectionDraft,
  type NavigationDraft,
  type NavigationItem,
  type PageDraft,
  navigationDraftSchema,
} from './schemas.js';

function walk(items: readonly NavigationItem[]): { url: string; type: string }[] {
  return items.flatMap((item) => [{ url: item.url, type: item.type }, ...walk(item.children)]);
}

export function synthNavigation(
  sc: SynthContext,
  collections: readonly CollectionDraft[],
  pages: readonly PageDraft[],
  policies: readonly PageDraft[],
): Promise<NavigationDraft> {
  return cached(sc, 'navigation.json', navigationDraftSchema, async () => {
    const capabilities = await readJsonFile(
      path.join(sc.manualDir, 'capabilities.json'),
      z.unknown(),
    );
    const collectionUrls = new Set(collections.map((c) => `/collections/${c.handle}`));
    const pageUrls = new Set([...pages, ...policies].map((p) => `/pages/${p.handle}`));
    return completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_navigation', {
        collections: pretty(collections.map((c) => ({ title: c.title, handle: c.handle }))),
        pages: pretty([...pages, ...policies].map((p) => ({ title: p.title, handle: p.handle }))),
        capabilities: pretty(capabilities),
      }),
      navigationDraftSchema,
      (nav) => {
        const main = walk(nav['main-menu']);
        const linked = new Set(main.filter((e) => e.type === 'COLLECTION').map((e) => e.url));
        const missing = [...collectionUrls].filter((u) => !linked.has(u));
        if (missing.length > 0) return `main-menu does not link collections: ${missing.join(', ')}`;
        for (const entry of [...main, ...walk(nav.footer)]) {
          if (entry.type === 'COLLECTION' && !collectionUrls.has(entry.url))
            return `unknown collection url ${entry.url}`;
          if (entry.type === 'PAGE' && !pageUrls.has(entry.url))
            return `unknown page url ${entry.url}`;
          if (entry.type === 'HTTP' && entry.url !== '/' && !entry.url.startsWith('/')) {
            return `HTTP links must be site-relative: ${entry.url}`;
          }
        }
        return undefined;
      },
    );
  });
}
