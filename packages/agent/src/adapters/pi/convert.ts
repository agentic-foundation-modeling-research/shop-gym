/** Conversions between ShopGym agent types and pi-ai message types. */

import type { ImageContent, Usage as PiUsage, TextContent } from '@earendil-works/pi-ai';
import type { Usage } from '@shop-gym/core';

import type { ImageAttachment, PromptContent } from '../../types.js';

/** pi's usage record reduced to ShopGym's token and cost totals. */
export function toUsage(usage: PiUsage): Usage {
  return {
    input: usage.input,
    output: usage.output,
    cacheRead: usage.cacheRead,
    cacheWrite: usage.cacheWrite,
    costUsd: usage.cost.total,
  };
}

/** Image attachments of a prompt as pi image blocks. */
export function promptImages(prompt: string | PromptContent): ImageContent[] {
  if (typeof prompt === 'string') {
    return [];
  }
  return (prompt.images ?? []).map(toImageContent);
}

function toImageContent(image: ImageAttachment): ImageContent {
  return { type: 'image', data: image.data, mimeType: image.mimeType };
}

/** Concatenated text blocks of a message's content. */
export function joinText(content: readonly { type: string }[]): string {
  return content
    .filter((part): part is TextContent => part.type === 'text')
    .map((part) => part.text)
    .join('');
}
