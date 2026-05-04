import {useEffect, useState} from 'react';
import {Image} from '@shopify/hydrogen';
import {ProductPlaceholder} from '~/components/ProductPlaceholder';

export type GalleryImage = {
  id?: string | null;
  url: string;
  altText?: string | null;
  width?: number | null;
  height?: number | null;
};

export function ProductImage({
  images,
  productTitle,
}: {
  images: GalleryImage[];
  productTitle: string;
}) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    setActiveIndex(0);
  }, [images]);

  if (!images.length) {
    return (
      <div className="pdp-gallery">
        <div className="pdp-gallery-main">
          <ProductPlaceholder className="pdp-gallery-placeholder" />
        </div>
      </div>
    );
  }

  const safeIndex = Math.min(activeIndex, images.length - 1);
  const current = images[safeIndex];
  const total = images.length;

  const handlePrev = () => {
    setActiveIndex((i) => (i - 1 + total) % total);
  };
  const handleNext = () => {
    setActiveIndex((i) => (i + 1) % total);
  };

  return (
    <div className="pdp-gallery">
      <div className="pdp-gallery-rail" role="tablist" aria-label="Product images">
        {images.map((image, index) => (
          <button
            key={image.id ?? `${image.url}-${index}`}
            type="button"
            role="tab"
            aria-selected={index === safeIndex}
            aria-label={`View image ${index + 1}`}
            className={`pdp-gallery-thumb${
              index === safeIndex ? ' is-active' : ''
            }`}
            onClick={() => setActiveIndex(index)}
          >
            <Image
              alt={image.altText || `${productTitle} image ${index + 1}`}
              data={image}
              aspectRatio="1/1"
              sizes="80px"
            />
          </button>
        ))}
      </div>
      <div className="pdp-gallery-main">
        <div className="pdp-gallery-frame">
          <Image
            key={current.id ?? current.url}
            alt={current.altText || productTitle}
            data={current}
            aspectRatio="11/6"
            sizes="(min-width: 900px) 540px, 90vw"
          />
          {total > 1 && (
            <>
              <button
                type="button"
                className="pdp-gallery-arrow pdp-gallery-arrow-prev"
                aria-label="Previous image"
                onClick={handlePrev}
              >
                <Chevron direction="left" />
              </button>
              <button
                type="button"
                className="pdp-gallery-arrow pdp-gallery-arrow-next"
                aria-label="Next image"
                onClick={handleNext}
              >
                <Chevron direction="right" />
              </button>
            </>
          )}
        </div>
        {total > 1 && (
          <div className="pdp-gallery-pagination" aria-label="Image pagination">
            {images.map((_, index) => (
              <button
                key={index}
                type="button"
                className={`pdp-gallery-dot${
                  index === safeIndex ? ' is-active' : ''
                }`}
                aria-label={`Go to image ${index + 1}`}
                aria-current={index === safeIndex}
                onClick={() => setActiveIndex(index)}
              >
                {index + 1}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Chevron({direction}: {direction: 'left' | 'right'}) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {direction === 'left' ? (
        <path d="M15 6l-6 6 6 6" />
      ) : (
        <path d="M9 6l6 6-6 6" />
      )}
    </svg>
  );
}
