import {useEffect, useState} from 'react';
import {Money} from '@shopify/hydrogen';
import type {ProductFragment} from 'storefrontapi.generated';
import {AddToCartButton} from './AddToCartButton';
import {useAside} from './Aside';

export function PdpStickyBar({
  productTitle,
  selectedVariant,
}: {
  productTitle: string;
  selectedVariant: ProductFragment['selectedOrFirstAvailableVariant'];
}) {
  const [visible, setVisible] = useState(false);
  const {open} = useAside();

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 600);
    onScroll();
    window.addEventListener('scroll', onScroll, {passive: true});
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  if (!selectedVariant) return null;

  return (
    <div
      className={`pdp-sticky-bar${visible ? ' is-visible' : ''}`}
      aria-hidden={!visible}
    >
      <div className="pdp-sticky-bar-info">
        <span className="pdp-sticky-bar-title">{productTitle}</span>
        <span className="pdp-sticky-bar-price">
          {selectedVariant.price ? <Money data={selectedVariant.price} /> : null}
        </span>
      </div>
      <AddToCartButton
        disabled={!selectedVariant.availableForSale}
        onClick={() => open('cart')}
        lines={[
          {
            merchandiseId: selectedVariant.id,
            quantity: 1,
            selectedVariant,
          },
        ]}
      >
        <span className="pdp-sticky-bar-cta">
          {selectedVariant.availableForSale ? 'Add to Bag' : 'Sold Out'}
        </span>
      </AddToCartButton>
    </div>
  );
}
