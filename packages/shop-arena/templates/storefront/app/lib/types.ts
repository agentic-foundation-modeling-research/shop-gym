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

/** LINE_ITEM for a percent or fixed code, SHIPPING_LINE for a free-shipping code. */
export type DiscountTargetType = 'LINE_ITEM' | 'SHIPPING_LINE';

export interface CartDiscountAllocation {
  readonly code: string;
  readonly discountedAmount: Money;
  readonly targetType: DiscountTargetType;
}

export interface Cart {
  readonly id: string;
  readonly checkoutUrl: string;
  readonly totalQuantity: number;
  readonly cost: {
    readonly subtotalAmount: Money;
    readonly totalAmount: Money;
    readonly totalTaxAmount: Money | null;
  };
  readonly lines: {
    readonly nodes: readonly CartLine[];
  };
  readonly discountCodes: readonly CartDiscountCode[];
  readonly discountAllocations: readonly CartDiscountAllocation[];
}

export interface MailingAddress {
  readonly id: string;
  readonly firstName: string | null;
  readonly lastName: string | null;
  readonly company: string | null;
  readonly address1: string | null;
  readonly address2: string | null;
  readonly city: string | null;
  readonly province: string | null;
  readonly country: string | null;
  readonly zip: string | null;
  readonly phone: string | null;
  readonly formatted: readonly string[];
}

export interface OrderLineItem {
  readonly title: string;
  readonly quantity: number;
  readonly variant: (ProductVariant & { readonly sku: string | null }) | null;
  readonly originalTotalPrice: Money;
}

export interface OrderSummary {
  readonly id: string;
  readonly name: string;
  readonly orderNumber: number;
  readonly processedAt: string;
  readonly financialStatus: string | null;
  readonly fulfillmentStatus: string;
  readonly totalPrice: Money;
}

/** A Discount code that applies to a cart or an order. */
export interface AppliedDiscount {
  readonly code: string;
  readonly targetType: DiscountTargetType;
  /**
   * Merchandise discount. For a free-shipping code, the waived shipping
   * charge on an order, and 0.00 on a cart, which has no shipping charge yet.
   */
  readonly amount: Money;
}

export interface OrderDetail extends OrderSummary {
  readonly email: string | null;
  readonly subtotalPrice: Money | null;
  readonly totalShippingPrice: Money;
  readonly totalTax: Money | null;
  readonly shippingAddress: MailingAddress | null;
  readonly shippingMethod: string | null;
  readonly paymentMethod: string | null;
  readonly discountCode: AppliedDiscount | null;
  readonly lineItems: {
    readonly nodes: readonly OrderLineItem[];
  };
}

export interface Customer {
  readonly id: string;
  readonly email: string | null;
  readonly firstName: string | null;
  readonly lastName: string | null;
  readonly displayName: string;
  readonly phone: string | null;
  readonly defaultAddress: MailingAddress | null;
}

export interface CustomerUserError {
  readonly code: string | null;
  readonly field: readonly string[] | null;
  readonly message: string;
}

export interface ShippingMethod {
  readonly handle: string;
  readonly title: string;
  readonly price: Money;
}

export interface PaymentMethod {
  readonly handle: string;
  readonly title: string;
}

export interface CommerceSettings {
  readonly currencyCode: string;
  readonly taxRate: number;
  readonly freeShippingThreshold: Money | null;
  readonly shippingMethods: readonly ShippingMethod[];
  readonly paymentMethods: readonly PaymentMethod[];
}

export interface CheckoutUserError {
  readonly code: string | null;
  readonly field: readonly string[] | null;
  readonly message: string;
}
