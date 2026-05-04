import {useEffect, useState, useCallback} from 'react';
import {Image} from '@shopify/hydrogen';
import type {ProductVariantFragment} from 'storefrontapi.generated';

type GalleryImage = NonNullable<ProductVariantFragment['image']>;

const GRADIENT_PALETTES = [
  {bg: 'linear-gradient(135deg, #efe6d6 0%, #c5a47e 100%)', accent: '#a08665'},
  {bg: 'linear-gradient(160deg, #d8c19a 0%, #6e553f 100%)', accent: '#3d2c1e'},
  {bg: 'linear-gradient(150deg, #f0e6d2 0%, #d8c19a 60%, #b89a78 100%)', accent: '#7a5638'},
  {bg: 'linear-gradient(180deg, #e8e2d8 0%, #b8a888 100%)', accent: '#705844'},
  {bg: 'linear-gradient(135deg, #f5ede0 0%, #c0a07c 50%, #5b4838 100%)', accent: '#2a201c'},
];

export function ProductImage({
  image,
  productTitle,
  productHandle,
}: {
  image?: GalleryImage | null;
  productTitle: string;
  productHandle: string;
}) {
  const galleryImages: Array<GalleryImage | null> = image
    ? [image, image, image, image]
    : [null, null, null, null];

  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [mobileIndex, setMobileIndex] = useState(0);

  const closeLightbox = useCallback(() => setLightboxIndex(null), []);
  const showPrev = useCallback(() => {
    setLightboxIndex((i) =>
      i === null ? null : (i - 1 + galleryImages.length) % galleryImages.length,
    );
  }, [galleryImages.length]);
  const showNext = useCallback(() => {
    setLightboxIndex((i) =>
      i === null ? null : (i + 1) % galleryImages.length,
    );
  }, [galleryImages.length]);

  useEffect(() => {
    if (lightboxIndex === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeLightbox();
      if (e.key === 'ArrowLeft') showPrev();
      if (e.key === 'ArrowRight') showNext();
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [lightboxIndex, closeLightbox, showPrev, showNext]);

  return (
    <div className="pdp-gallery">
      <div className="pdp-gallery-desktop">
        {galleryImages.map((img, idx) => (
          <button
            type="button"
            key={`desktop-${idx}`}
            className="pdp-gallery-tile"
            onClick={() => setLightboxIndex(idx)}
            aria-label={`Open image ${idx + 1} in lightbox`}
          >
            <GalleryTile
              image={img}
              alt={img?.altText || productTitle}
              variantSeed={`${productHandle}-${idx}`}
              showModelOverlay={idx === 1}
              isVideoTile={idx === 2}
              loading={idx === 0 ? 'eager' : 'lazy'}
            />
          </button>
        ))}
      </div>

      <div className="pdp-gallery-mobile" role="region" aria-label="Product images">
        <div className="pdp-gallery-mobile-track">
          {galleryImages.map((img, idx) => (
            <button
              type="button"
              key={`mobile-${idx}`}
              className={`pdp-gallery-mobile-slide${
                idx === mobileIndex ? ' is-active' : ''
              }`}
              onClick={() => setLightboxIndex(idx)}
              aria-label={`Open image ${idx + 1} in lightbox`}
            >
              <GalleryTile
                image={img}
                alt={img?.altText || productTitle}
                variantSeed={`${productHandle}-${idx}`}
                showModelOverlay={idx === 1}
                isVideoTile={idx === 2}
                loading={idx === 0 ? 'eager' : 'lazy'}
              />
            </button>
          ))}
        </div>
        <div className="pdp-gallery-mobile-dots" aria-hidden="true">
          {galleryImages.map((_, idx) => (
            <button
              key={`dot-${idx}`}
              type="button"
              className={`pdp-gallery-mobile-dot${
                idx === mobileIndex ? ' is-active' : ''
              }`}
              onClick={() => setMobileIndex(idx)}
              aria-label={`Go to image ${idx + 1}`}
            />
          ))}
        </div>
      </div>

      {lightboxIndex !== null ? (
        <div
          className="pdp-lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="Product image viewer"
          onClick={closeLightbox}
        >
          <button
            type="button"
            className="pdp-lightbox-close"
            onClick={closeLightbox}
            aria-label="Close image viewer"
          >
            ×
          </button>
          <button
            type="button"
            className="pdp-lightbox-nav pdp-lightbox-nav-prev"
            onClick={(e) => {
              e.stopPropagation();
              showPrev();
            }}
            aria-label="Previous image"
          >
            ‹
          </button>
          <div
            className="pdp-lightbox-stage"
            onClick={(e) => e.stopPropagation()}
            role="presentation"
          >
            <GalleryTile
              image={galleryImages[lightboxIndex]}
              alt={galleryImages[lightboxIndex]?.altText || productTitle}
              variantSeed={`${productHandle}-${lightboxIndex}-zoom`}
              showModelOverlay={false}
              isVideoTile={false}
              loading="eager"
              fullSize
            />
          </div>
          <button
            type="button"
            className="pdp-lightbox-nav pdp-lightbox-nav-next"
            onClick={(e) => {
              e.stopPropagation();
              showNext();
            }}
            aria-label="Next image"
          >
            ›
          </button>
          <div className="pdp-lightbox-counter" aria-live="polite">
            {lightboxIndex + 1} / {galleryImages.length}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function GalleryTile({
  image,
  alt,
  variantSeed,
  showModelOverlay,
  isVideoTile,
  loading,
  fullSize,
}: {
  image?: GalleryImage | null;
  alt: string;
  variantSeed: string;
  showModelOverlay: boolean;
  isVideoTile: boolean;
  loading: 'eager' | 'lazy';
  fullSize?: boolean;
}) {
  const palette = pickPalette(variantSeed);
  return (
    <div
      className={`pdp-gallery-frame${fullSize ? ' is-fullsize' : ''}`}
      style={{background: palette.bg}}
    >
      {image ? (
        <Image
          alt={alt}
          aspectRatio={fullSize ? undefined : '4/5'}
          data={image}
          loading={loading}
          sizes={
            fullSize
              ? '90vw'
              : '(min-width: 60em) 50vw, 100vw'
          }
          className="pdp-gallery-img"
        />
      ) : (
        <PlaceholderArt accent={palette.accent} variantSeed={variantSeed} />
      )}
      {isVideoTile ? (
        <span className="pdp-gallery-play" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <path d="M7 5l10 6-10 6V5z" fill="currentColor" />
          </svg>
        </span>
      ) : null}
      {showModelOverlay ? (
        <div className="pdp-gallery-model-tag" aria-hidden="true">
          Model is 5′9″ wearing size S
        </div>
      ) : null}
    </div>
  );
}

function PlaceholderArt({
  accent,
  variantSeed,
}: {
  accent: string;
  variantSeed: string;
}) {
  const seed = hashString(variantSeed);
  const variant = seed % 4;
  return (
    <svg
      className="pdp-gallery-placeholder-art"
      viewBox="0 0 400 500"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <g opacity="0.9" fill={accent}>
        {variant === 0 ? (
          <>
            <ellipse cx="200" cy="180" rx="56" ry="62" />
            <path d="M120 290 q40 -50 80 -50 q40 0 80 50 q-10 130 -80 150 q-70 -20 -80 -150z" />
          </>
        ) : variant === 1 ? (
          <>
            <rect x="150" y="120" width="100" height="280" rx="24" />
            <circle cx="200" cy="160" r="20" fill="rgba(255,255,255,0.4)" />
          </>
        ) : variant === 2 ? (
          <>
            <path d="M100 250 q100 -110 200 0 q-100 110 -200 0z" />
            <circle cx="200" cy="250" r="12" fill="rgba(255,255,255,0.6)" />
          </>
        ) : (
          <>
            <path d="M140 100 l60 60 l60 -60 v280 q-60 60 -120 0z" />
            <circle cx="200" cy="160" r="8" fill="rgba(255,255,255,0.55)" />
          </>
        )}
      </g>
      <g opacity="0.18" stroke={accent} strokeWidth="1.4" fill="none">
        <path d="M20 60 q120 -30 360 30" />
        <path d="M20 460 q140 30 360 -30" />
      </g>
    </svg>
  );
}

const PALETTE_FALLBACK = GRADIENT_PALETTES[0];
function pickPalette(seed: string) {
  const idx = hashString(seed) % GRADIENT_PALETTES.length;
  return GRADIENT_PALETTES[idx] ?? PALETTE_FALLBACK;
}

function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}
