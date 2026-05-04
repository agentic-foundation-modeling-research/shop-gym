import {useEffect, useRef, useState} from 'react';
import {type FetcherWithComponents} from 'react-router';
import {CartForm, type OptimisticCartLineInput} from '@shopify/hydrogen';

export function AddToCartButton({
  analytics,
  children,
  disabled,
  lines,
  onClick,
}: {
  analytics?: unknown;
  children: React.ReactNode;
  disabled?: boolean;
  lines: Array<OptimisticCartLineInput>;
  onClick?: () => void;
}) {
  return (
    <CartForm route="/cart" inputs={{lines}} action={CartForm.ACTIONS.LinesAdd}>
      {(fetcher: FetcherWithComponents<any>) => (
        <AddToCartInner
          fetcher={fetcher}
          analytics={analytics}
          disabled={disabled}
          onClick={onClick}
        >
          {children}
        </AddToCartInner>
      )}
    </CartForm>
  );
}

function AddToCartInner({
  fetcher,
  analytics,
  disabled,
  onClick,
  children,
}: {
  fetcher: FetcherWithComponents<any>;
  analytics?: unknown;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  const [showAdded, setShowAdded] = useState(false);
  const wasSubmitting = useRef(false);

  useEffect(() => {
    if (fetcher.state !== 'idle') {
      wasSubmitting.current = true;
    } else if (wasSubmitting.current) {
      wasSubmitting.current = false;
      setShowAdded(true);
      const timer = setTimeout(() => setShowAdded(false), 1800);
      return () => clearTimeout(timer);
    }
  }, [fetcher.state]);

  const isLoading = fetcher.state !== 'idle';
  const isDisabled = disabled ?? isLoading;

  return (
    <>
      <input
        name="analytics"
        type="hidden"
        value={JSON.stringify(analytics)}
      />
      <button
        type="submit"
        className={`add-to-cart-button${showAdded ? ' is-added' : ''}${
          isLoading ? ' is-loading' : ''
        }`}
        onClick={onClick}
        disabled={isDisabled}
        aria-live="polite"
      >
        <span className="add-to-cart-default">{children}</span>
        <span className="add-to-cart-added" aria-hidden={!showAdded}>
          Added to cart
        </span>
      </button>
    </>
  );
}
