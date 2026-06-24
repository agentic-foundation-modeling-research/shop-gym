export interface Money {
  readonly amount: string;
  readonly currencyCode: string;
}

export interface Image {
  readonly id?: string | null;
  readonly url: string;
  readonly altText?: string | null;
  readonly width?: number | null;
  readonly height?: number | null;
}

export interface MenuItem {
  readonly id: string;
  readonly title: string;
  readonly url: string;
  readonly type: string;
  readonly items: readonly MenuItem[];
}

export interface Menu {
  readonly id: string;
  readonly handle: string;
  readonly title?: string;
  readonly items: readonly MenuItem[];
}

export interface Shop {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly primaryDomain: {
    readonly url: string;
  };
  readonly privacyPolicy?: Policy | null;
  readonly shippingPolicy?: Policy | null;
  readonly termsOfService?: Policy | null;
  readonly refundPolicy?: Policy | null;
  readonly subscriptionPolicy?: Policy | null;
}

export interface ProductSummary {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly vendor: string;
  readonly featuredImage: Image | null;
  readonly priceRange: {
    readonly minVariantPrice: Money;
  };
}

export interface SelectedOption {
  readonly name: string;
  readonly value: string;
}

export interface ProductVariant {
  readonly id: string;
  readonly title: string;
  readonly availableForSale: boolean;
  readonly quantityAvailable: number | null;
  readonly selectedOptions: readonly SelectedOption[];
  readonly image: Image | null;
  readonly price: Money;
  readonly compareAtPrice: Money | null;
  readonly product: {
    readonly title: string;
    readonly handle: string;
  };
}

export interface ProductDetail extends ProductSummary {
  readonly description: string;
  readonly descriptionHtml: string;
  readonly productType: string;
  readonly images: {
    readonly nodes: readonly (Image | null)[];
  };
  readonly variants: {
    readonly nodes: readonly ProductVariant[];
  };
  readonly selectedOrFirstAvailableVariant: ProductVariant | null;
}

export interface CollectionSummary {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly description: string;
  readonly image: Image | null;
}

export interface CollectionDetail extends CollectionSummary {
  readonly descriptionHtml: string;
  readonly products: {
    readonly nodes: readonly ProductSummary[];
    readonly totalCount: number | null;
  };
}

export interface Page {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly body: string;
}

export interface Policy {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly body: string;
  readonly url: string;
}

export interface CartLine {
  readonly id: string;
  readonly quantity: number;
  readonly cost: {
    readonly totalAmount: Money;
  };
  readonly merchandise: ProductVariant;
}

export interface CartDiscountCode {
  readonly code: string;
  readonly applicable: boolean;
}

export interface Cart {
  readonly id: string;
  readonly checkoutUrl: string;
  readonly totalQuantity: number;
  readonly cost: {
    readonly subtotalAmount: Money;
    readonly totalAmount: Money;
  };
  readonly lines: {
    readonly nodes: readonly CartLine[];
  };
  readonly discountCodes: readonly CartDiscountCode[];
}
