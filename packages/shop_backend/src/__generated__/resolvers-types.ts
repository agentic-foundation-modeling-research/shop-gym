import type { GraphQLResolveInfo } from 'graphql';
import type { ResolverContext } from '../resolvers/index.js';
export type Maybe<T> = T | null;
export type InputMaybe<T> = Maybe<T>;
export type Exact<T extends { [key: string]: unknown }> = { [K in keyof T]: T[K] };
export type MakeOptional<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]?: Maybe<T[SubKey]> };
export type MakeMaybe<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]: Maybe<T[SubKey]> };
export type MakeEmpty<T extends { [key: string]: unknown }, K extends keyof T> = { [_ in K]?: never };
export type Incremental<T> = T | { [P in keyof T]?: P extends ' $fragmentName' | '__typename' ? T[P] : never };
export type Omit<T, K extends keyof T> = Pick<T, Exclude<keyof T, K>>;
export type RequireFields<T, K extends keyof T> = Omit<T, K> & { [P in K]-?: NonNullable<T[P]> };
/** All built-in and custom scalars, mapped to their actual values */
export type Scalars = {
  ID: { input: string; output: string; }
  String: { input: string; output: string; }
  Boolean: { input: boolean; output: boolean; }
  Int: { input: number; output: number; }
  Float: { input: number; output: number; }
};

export type AppliedGiftCard = {
  readonly __typename?: 'AppliedGiftCard';
  readonly amountUsed: Maybe<MoneyV2>;
  readonly id: Scalars['ID']['output'];
  readonly lastCharacters: Maybe<Scalars['String']['output']>;
};

export type Article = {
  readonly __typename?: 'Article';
  readonly author: Maybe<ArticleAuthor>;
  readonly blog: BlogRef;
  readonly contentHtml: Scalars['String']['output'];
  readonly handle: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly image: Maybe<Image>;
  readonly publishedAt: Maybe<Scalars['String']['output']>;
  readonly seo: Maybe<Seo>;
  readonly title: Scalars['String']['output'];
  readonly trackingParameters: Maybe<Scalars['String']['output']>;
};

export type ArticleAuthor = {
  readonly __typename?: 'ArticleAuthor';
  readonly name: Scalars['String']['output'];
};

export type ArticleConnection = {
  readonly __typename?: 'ArticleConnection';
  readonly edges: ReadonlyArray<ArticleEdge>;
  readonly nodes: ReadonlyArray<Article>;
  readonly pageInfo: PageInfo;
  readonly totalCount: Maybe<Scalars['Int']['output']>;
};

export type ArticleEdge = {
  readonly __typename?: 'ArticleEdge';
  readonly cursor: Scalars['String']['output'];
  readonly node: Article;
};

export type Attribute = {
  readonly __typename?: 'Attribute';
  readonly key: Scalars['String']['output'];
  readonly value: Scalars['String']['output'];
};

export type AttributeInput = {
  readonly key: Scalars['String']['input'];
  readonly value: Scalars['String']['input'];
};

export type BaseCartLine = CartLine | ComponentizableCartLine;

export type Blog = {
  readonly __typename?: 'Blog';
  readonly articleByHandle: Maybe<Article>;
  readonly articles: ArticleConnection;
  readonly handle: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly seo: Seo;
  readonly title: Scalars['String']['output'];
};


export type BlogArticleByHandleArgs = {
  handle: Scalars['String']['input'];
};


export type BlogArticlesArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  before: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
  last: InputMaybe<Scalars['Int']['input']>;
};

export type BlogConnection = {
  readonly __typename?: 'BlogConnection';
  readonly edges: ReadonlyArray<BlogEdge>;
  readonly nodes: ReadonlyArray<Blog>;
  readonly pageInfo: PageInfo;
};

export type BlogEdge = {
  readonly __typename?: 'BlogEdge';
  readonly cursor: Scalars['String']['output'];
  readonly node: Blog;
};

export type BlogRef = {
  readonly __typename?: 'BlogRef';
  readonly handle: Scalars['String']['output'];
};

export type Brand = {
  readonly __typename?: 'Brand';
  readonly colors: Maybe<BrandColors>;
  readonly coverImage: Maybe<MediaImage>;
  readonly logo: Maybe<MediaImage>;
  readonly shortDescription: Maybe<Scalars['String']['output']>;
};

export type BrandColorGroup = {
  readonly __typename?: 'BrandColorGroup';
  readonly background: Maybe<Scalars['String']['output']>;
  readonly foreground: Maybe<Scalars['String']['output']>;
};

export type BrandColors = {
  readonly __typename?: 'BrandColors';
  readonly primary: Maybe<ReadonlyArray<BrandColorGroup>>;
};

export type Cart = {
  readonly __typename?: 'Cart';
  readonly appliedGiftCards: ReadonlyArray<AppliedGiftCard>;
  readonly attributes: ReadonlyArray<Attribute>;
  readonly buyerIdentity: CartBuyerIdentity;
  readonly checkoutUrl: Scalars['String']['output'];
  readonly cost: CartCost;
  readonly discountAllocations: ReadonlyArray<CartDiscountAllocation>;
  readonly discountCodes: ReadonlyArray<CartDiscountCode>;
  readonly id: Scalars['ID']['output'];
  readonly lines: CartLineConnection;
  readonly note: Scalars['String']['output'];
  readonly totalQuantity: Scalars['Int']['output'];
  readonly updatedAt: Scalars['String']['output'];
};


export type CartLinesArgs = {
  first: InputMaybe<Scalars['Int']['input']>;
};

export type CartAttributesUpdatePayload = {
  readonly __typename?: 'CartAttributesUpdatePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartBuyerIdentity = {
  readonly __typename?: 'CartBuyerIdentity';
  readonly countryCode: Maybe<Scalars['String']['output']>;
  readonly customer: Maybe<Customer>;
  readonly email: Maybe<Scalars['String']['output']>;
  readonly phone: Maybe<Scalars['String']['output']>;
};

export type CartBuyerIdentityInput = {
  readonly countryCode?: InputMaybe<CountryCode>;
  readonly customerAccessToken?: InputMaybe<Scalars['String']['input']>;
  readonly email?: InputMaybe<Scalars['String']['input']>;
  readonly phone?: InputMaybe<Scalars['String']['input']>;
};

export type CartBuyerIdentityUpdatePayload = {
  readonly __typename?: 'CartBuyerIdentityUpdatePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartCodeDiscountAllocation = CartDiscountAllocation & {
  readonly __typename?: 'CartCodeDiscountAllocation';
  readonly code: Scalars['String']['output'];
  readonly discountedAmount: MoneyV2;
  readonly targetType: DiscountApplicationTargetType;
};

export type CartCost = {
  readonly __typename?: 'CartCost';
  readonly subtotalAmount: MoneyV2;
  readonly totalAmount: MoneyV2;
  readonly totalDutyAmount: Maybe<MoneyV2>;
  readonly totalTaxAmount: Maybe<MoneyV2>;
};

export type CartCreatePayload = {
  readonly __typename?: 'CartCreatePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartDiscountAllocation = {
  readonly discountedAmount: MoneyV2;
  readonly targetType: DiscountApplicationTargetType;
};

export type CartDiscountCode = {
  readonly __typename?: 'CartDiscountCode';
  readonly applicable: Scalars['Boolean']['output'];
  readonly code: Scalars['String']['output'];
};

export type CartDiscountCodesUpdatePayload = {
  readonly __typename?: 'CartDiscountCodesUpdatePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartGiftCardCodesAddPayload = {
  readonly __typename?: 'CartGiftCardCodesAddPayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartGiftCardCodesRemovePayload = {
  readonly __typename?: 'CartGiftCardCodesRemovePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartGiftCardCodesUpdatePayload = {
  readonly __typename?: 'CartGiftCardCodesUpdatePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartInput = {
  readonly attributes?: InputMaybe<ReadonlyArray<AttributeInput>>;
  readonly buyerIdentity?: InputMaybe<CartBuyerIdentityInput>;
  readonly discountCodes?: InputMaybe<ReadonlyArray<Scalars['String']['input']>>;
  readonly giftCardCodes?: InputMaybe<ReadonlyArray<Scalars['String']['input']>>;
  readonly lines?: InputMaybe<ReadonlyArray<CartLineInput>>;
  readonly note?: InputMaybe<Scalars['String']['input']>;
};

export type CartLine = {
  readonly __typename?: 'CartLine';
  readonly attributes: ReadonlyArray<Attribute>;
  readonly cost: CartLineCost;
  readonly id: Scalars['ID']['output'];
  readonly merchandise: Merchandise;
  readonly parentRelationship: Maybe<CartLineParentRelationship>;
  readonly quantity: Scalars['Int']['output'];
};

export type CartLineConnection = {
  readonly __typename?: 'CartLineConnection';
  readonly edges: ReadonlyArray<CartLineEdge>;
  readonly nodes: ReadonlyArray<BaseCartLine>;
};

export type CartLineCost = {
  readonly __typename?: 'CartLineCost';
  readonly amountPerQuantity: MoneyV2;
  readonly compareAtAmountPerQuantity: Maybe<MoneyV2>;
  readonly subtotalAmount: MoneyV2;
  readonly totalAmount: MoneyV2;
};

export type CartLineEdge = {
  readonly __typename?: 'CartLineEdge';
  readonly node: BaseCartLine;
};

export type CartLineInput = {
  readonly attributes?: InputMaybe<ReadonlyArray<AttributeInput>>;
  readonly merchandiseId: Scalars['ID']['input'];
  readonly quantity?: InputMaybe<Scalars['Int']['input']>;
  readonly sellingPlanId?: InputMaybe<Scalars['ID']['input']>;
};

export type CartLineParent = {
  readonly __typename?: 'CartLineParent';
  readonly id: Scalars['ID']['output'];
};

export type CartLineParentRelationship = {
  readonly __typename?: 'CartLineParentRelationship';
  readonly parent: Maybe<CartLineParent>;
};

export type CartLineUpdateInput = {
  readonly attributes?: InputMaybe<ReadonlyArray<AttributeInput>>;
  readonly id: Scalars['ID']['input'];
  readonly merchandiseId?: InputMaybe<Scalars['ID']['input']>;
  readonly quantity?: InputMaybe<Scalars['Int']['input']>;
  readonly sellingPlanId?: InputMaybe<Scalars['ID']['input']>;
};

export type CartLinesAddPayload = {
  readonly __typename?: 'CartLinesAddPayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartLinesRemovePayload = {
  readonly __typename?: 'CartLinesRemovePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartLinesUpdatePayload = {
  readonly __typename?: 'CartLinesUpdatePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartNoteUpdatePayload = {
  readonly __typename?: 'CartNoteUpdatePayload';
  readonly cart: Maybe<Cart>;
  readonly userErrors: ReadonlyArray<CartUserError>;
  readonly warnings: ReadonlyArray<CartWarning>;
};

export type CartUserError = {
  readonly __typename?: 'CartUserError';
  readonly code: Maybe<Scalars['String']['output']>;
  readonly field: Maybe<ReadonlyArray<Scalars['String']['output']>>;
  readonly message: Scalars['String']['output'];
};

export type CartWarning = {
  readonly __typename?: 'CartWarning';
  readonly code: Scalars['String']['output'];
  readonly message: Scalars['String']['output'];
  readonly target: Maybe<Scalars['String']['output']>;
};

export type CheckoutCompleteInput = {
  /** Contact email; defaults to the cart's buyer identity email. */
  readonly email?: InputMaybe<Scalars['String']['input']>;
  /** Handle of a commerce.json payment method; defaults to the first one. */
  readonly paymentMethodHandle?: InputMaybe<Scalars['String']['input']>;
  readonly shippingAddress: MailingAddressInput;
  /** Handle of a commerce.json shipping method; defaults to the first one. */
  readonly shippingMethodHandle?: InputMaybe<Scalars['String']['input']>;
};

export type CheckoutCompletePayload = {
  readonly __typename?: 'CheckoutCompletePayload';
  readonly order: Maybe<Order>;
  readonly userErrors: ReadonlyArray<CheckoutUserError>;
};

export type CheckoutUserError = {
  readonly __typename?: 'CheckoutUserError';
  readonly code: Maybe<Scalars['String']['output']>;
  readonly field: Maybe<ReadonlyArray<Scalars['String']['output']>>;
  readonly message: Scalars['String']['output'];
};

export type Collection = {
  readonly __typename?: 'Collection';
  readonly description: Scalars['String']['output'];
  readonly descriptionHtml: Scalars['String']['output'];
  readonly handle: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly image: Maybe<Image>;
  readonly metafield: Maybe<Metafield>;
  readonly metafields: ReadonlyArray<Maybe<Metafield>>;
  readonly products: ProductConnection;
  readonly seo: Seo;
  readonly title: Scalars['String']['output'];
  readonly trackingParameters: Maybe<Scalars['String']['output']>;
  readonly updatedAt: Maybe<Scalars['String']['output']>;
};


export type CollectionMetafieldArgs = {
  key: Scalars['String']['input'];
  namespace: Scalars['String']['input'];
};


export type CollectionMetafieldsArgs = {
  identifiers: ReadonlyArray<HasMetafieldsIdentifier>;
};


export type CollectionProductsArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  before: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
  last: InputMaybe<Scalars['Int']['input']>;
};

export type CollectionConnection = {
  readonly __typename?: 'CollectionConnection';
  readonly edges: ReadonlyArray<CollectionEdge>;
  readonly nodes: ReadonlyArray<Collection>;
  readonly pageInfo: PageInfo;
};

export type CollectionEdge = {
  readonly __typename?: 'CollectionEdge';
  readonly cursor: Scalars['String']['output'];
  readonly node: Collection;
};

export type CollectionSortKeys =
  | 'ID'
  | 'RELEVANCE'
  | 'TITLE'
  | 'UPDATED_AT';

export type CommerceSettings = {
  readonly __typename?: 'CommerceSettings';
  readonly currencyCode: Scalars['String']['output'];
  readonly freeShippingThreshold: Maybe<MoneyV2>;
  readonly paymentMethods: ReadonlyArray<PaymentMethod>;
  readonly shippingMethods: ReadonlyArray<ShippingMethod>;
  /** Fraction of the merchandise subtotal charged as tax, e.g. 0.13. */
  readonly taxRate: Scalars['Float']['output'];
};

export type ComponentizableCartLine = {
  readonly __typename?: 'ComponentizableCartLine';
  readonly attributes: ReadonlyArray<Attribute>;
  readonly cost: CartLineCost;
  readonly id: Scalars['ID']['output'];
  readonly lineComponents: ReadonlyArray<CartLine>;
  readonly merchandise: Merchandise;
  readonly quantity: Scalars['Int']['output'];
};

export type Country = {
  readonly __typename?: 'Country';
  readonly availableLanguages: ReadonlyArray<Language>;
  readonly currency: CountryCurrency;
  readonly isoCode: Scalars['String']['output'];
  readonly name: Scalars['String']['output'];
};

export type CountryCode =
  | 'AU'
  | 'CA'
  | 'DE'
  | 'FR'
  | 'GB'
  | 'US'
  | 'ZZ';

export type CountryCurrency = {
  readonly __typename?: 'CountryCurrency';
  readonly isoCode: Scalars['String']['output'];
};

export type Currency = {
  readonly __typename?: 'Currency';
  readonly isoCode: Scalars['String']['output'];
  readonly name: Scalars['String']['output'];
  readonly symbol: Scalars['String']['output'];
};

export type CurrencyCode =
  | 'AUD'
  | 'CAD'
  | 'EUR'
  | 'GBP'
  | 'USD';

export type Customer = {
  readonly __typename?: 'Customer';
  readonly acceptsMarketing: Scalars['Boolean']['output'];
  readonly addresses: MailingAddressConnection;
  readonly createdAt: Scalars['String']['output'];
  readonly defaultAddress: Maybe<MailingAddress>;
  readonly displayName: Scalars['String']['output'];
  readonly email: Maybe<Scalars['String']['output']>;
  readonly firstName: Maybe<Scalars['String']['output']>;
  readonly id: Scalars['ID']['output'];
  readonly lastName: Maybe<Scalars['String']['output']>;
  readonly numberOfOrders: Scalars['Int']['output'];
  readonly orders: OrderConnection;
  readonly phone: Maybe<Scalars['String']['output']>;
  readonly updatedAt: Scalars['String']['output'];
};


export type CustomerAddressesArgs = {
  first: InputMaybe<Scalars['Int']['input']>;
};


export type CustomerOrdersArgs = {
  first: InputMaybe<Scalars['Int']['input']>;
  reverse: InputMaybe<Scalars['Boolean']['input']>;
  sortKey: InputMaybe<OrderSortKeys>;
};

export type CustomerAccessToken = {
  readonly __typename?: 'CustomerAccessToken';
  readonly accessToken: Scalars['String']['output'];
  readonly expiresAt: Scalars['String']['output'];
};

export type CustomerAccessTokenCreateInput = {
  readonly email: Scalars['String']['input'];
  readonly password: Scalars['String']['input'];
};

export type CustomerAccessTokenCreatePayload = {
  readonly __typename?: 'CustomerAccessTokenCreatePayload';
  readonly customerAccessToken: Maybe<CustomerAccessToken>;
  readonly customerUserErrors: ReadonlyArray<CustomerUserError>;
};

export type CustomerAccessTokenDeletePayload = {
  readonly __typename?: 'CustomerAccessTokenDeletePayload';
  readonly deletedAccessToken: Maybe<Scalars['String']['output']>;
  readonly deletedCustomerAccessTokenId: Maybe<Scalars['String']['output']>;
  readonly userErrors: ReadonlyArray<UserError>;
};

export type CustomerCreateInput = {
  readonly acceptsMarketing?: InputMaybe<Scalars['Boolean']['input']>;
  readonly email: Scalars['String']['input'];
  readonly firstName?: InputMaybe<Scalars['String']['input']>;
  readonly lastName?: InputMaybe<Scalars['String']['input']>;
  readonly password: Scalars['String']['input'];
  readonly phone?: InputMaybe<Scalars['String']['input']>;
};

export type CustomerCreatePayload = {
  readonly __typename?: 'CustomerCreatePayload';
  readonly customer: Maybe<Customer>;
  readonly customerUserErrors: ReadonlyArray<CustomerUserError>;
};

export type CustomerErrorCode =
  | 'BLANK'
  | 'INVALID'
  | 'TAKEN'
  | 'TOO_SHORT'
  | 'UNIDENTIFIED_CUSTOMER';

export type CustomerUserError = {
  readonly __typename?: 'CustomerUserError';
  readonly code: Maybe<CustomerErrorCode>;
  readonly field: Maybe<ReadonlyArray<Scalars['String']['output']>>;
  readonly message: Scalars['String']['output'];
};

export type DiscountApplicationTargetType =
  | 'LINE_ITEM'
  | 'SHIPPING_LINE';

export type HasMetafieldsIdentifier = {
  readonly key: Scalars['String']['input'];
  readonly namespace: Scalars['String']['input'];
};

export type Image = {
  readonly __typename?: 'Image';
  readonly altText: Maybe<Scalars['String']['output']>;
  readonly height: Maybe<Scalars['Int']['output']>;
  readonly id: Maybe<Scalars['ID']['output']>;
  readonly url: Scalars['String']['output'];
  readonly width: Maybe<Scalars['Int']['output']>;
};

export type ImageConnection = {
  readonly __typename?: 'ImageConnection';
  readonly edges: ReadonlyArray<ImageEdge>;
  readonly nodes: ReadonlyArray<Maybe<Image>>;
};

export type ImageEdge = {
  readonly __typename?: 'ImageEdge';
  readonly node: Maybe<Image>;
};

export type Language = {
  readonly __typename?: 'Language';
  readonly isoCode: Scalars['String']['output'];
  readonly name: Scalars['String']['output'];
};

export type LanguageCode =
  | 'DE'
  | 'EN'
  | 'ES'
  | 'FR';

export type Localization = {
  readonly __typename?: 'Localization';
  readonly availableCountries: ReadonlyArray<Country>;
  readonly availableLanguages: ReadonlyArray<Language>;
  readonly country: LocalizationCountry;
  readonly language: Language;
};

export type LocalizationCountry = {
  readonly __typename?: 'LocalizationCountry';
  readonly currency: Currency;
  readonly isoCode: Scalars['String']['output'];
  readonly name: Scalars['String']['output'];
};

export type MailingAddress = {
  readonly __typename?: 'MailingAddress';
  readonly address1: Maybe<Scalars['String']['output']>;
  readonly address2: Maybe<Scalars['String']['output']>;
  readonly city: Maybe<Scalars['String']['output']>;
  readonly company: Maybe<Scalars['String']['output']>;
  readonly country: Maybe<Scalars['String']['output']>;
  readonly countryCodeV2: Maybe<Scalars['String']['output']>;
  readonly firstName: Maybe<Scalars['String']['output']>;
  readonly formatted: ReadonlyArray<Scalars['String']['output']>;
  readonly id: Scalars['ID']['output'];
  readonly lastName: Maybe<Scalars['String']['output']>;
  readonly name: Maybe<Scalars['String']['output']>;
  readonly phone: Maybe<Scalars['String']['output']>;
  readonly province: Maybe<Scalars['String']['output']>;
  readonly provinceCode: Maybe<Scalars['String']['output']>;
  readonly zip: Maybe<Scalars['String']['output']>;
};

export type MailingAddressConnection = {
  readonly __typename?: 'MailingAddressConnection';
  readonly edges: ReadonlyArray<MailingAddressEdge>;
  readonly nodes: ReadonlyArray<MailingAddress>;
};

export type MailingAddressEdge = {
  readonly __typename?: 'MailingAddressEdge';
  readonly node: MailingAddress;
};

export type MailingAddressInput = {
  readonly address1?: InputMaybe<Scalars['String']['input']>;
  readonly address2?: InputMaybe<Scalars['String']['input']>;
  readonly city?: InputMaybe<Scalars['String']['input']>;
  readonly company?: InputMaybe<Scalars['String']['input']>;
  readonly country?: InputMaybe<Scalars['String']['input']>;
  readonly firstName?: InputMaybe<Scalars['String']['input']>;
  readonly lastName?: InputMaybe<Scalars['String']['input']>;
  readonly phone?: InputMaybe<Scalars['String']['input']>;
  readonly province?: InputMaybe<Scalars['String']['input']>;
  readonly zip?: InputMaybe<Scalars['String']['input']>;
};

export type MediaImage = {
  readonly __typename?: 'MediaImage';
  readonly image: Maybe<Image>;
  readonly previewImage: Maybe<Image>;
};

export type Menu = {
  readonly __typename?: 'Menu';
  readonly handle: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly items: ReadonlyArray<MenuItem>;
  readonly title: Scalars['String']['output'];
};

export type MenuItem = {
  readonly __typename?: 'MenuItem';
  readonly id: Scalars['ID']['output'];
  readonly items: ReadonlyArray<MenuItem>;
  readonly resourceId: Maybe<Scalars['ID']['output']>;
  readonly tags: ReadonlyArray<Scalars['String']['output']>;
  readonly title: Scalars['String']['output'];
  readonly type: Scalars['String']['output'];
  readonly url: Scalars['String']['output'];
};

export type Merchandise = ProductVariant;

export type Metafield = {
  readonly __typename?: 'Metafield';
  readonly id: Scalars['ID']['output'];
  readonly key: Scalars['String']['output'];
  readonly namespace: Scalars['String']['output'];
  readonly parentResource: Maybe<MetafieldParentResource>;
  readonly reference: Maybe<MetafieldReference>;
  readonly type: Scalars['String']['output'];
  readonly value: Scalars['String']['output'];
};

export type MetafieldParentResource = Collection | Product | ProductVariant;

export type MetafieldReference = Collection | Page | Product;

export type MoneyV2 = {
  readonly __typename?: 'MoneyV2';
  readonly amount: Scalars['String']['output'];
  readonly currencyCode: Scalars['String']['output'];
};

export type Mutation = {
  readonly __typename?: 'Mutation';
  readonly cartAttributesUpdate: CartAttributesUpdatePayload;
  readonly cartBuyerIdentityUpdate: CartBuyerIdentityUpdatePayload;
  readonly cartCreate: CartCreatePayload;
  readonly cartDiscountCodesUpdate: CartDiscountCodesUpdatePayload;
  readonly cartGiftCardCodesAdd: CartGiftCardCodesAddPayload;
  readonly cartGiftCardCodesRemove: CartGiftCardCodesRemovePayload;
  readonly cartGiftCardCodesUpdate: CartGiftCardCodesUpdatePayload;
  readonly cartLinesAdd: CartLinesAddPayload;
  readonly cartLinesRemove: CartLinesRemovePayload;
  readonly cartLinesUpdate: CartLinesUpdatePayload;
  readonly cartNoteUpdate: CartNoteUpdatePayload;
  /** Convert a cart into a paid, unfulfilled order. */
  readonly checkoutComplete: CheckoutCompletePayload;
  readonly customerAccessTokenCreate: CustomerAccessTokenCreatePayload;
  readonly customerAccessTokenDelete: CustomerAccessTokenDeletePayload;
  readonly customerCreate: CustomerCreatePayload;
};


export type MutationCartAttributesUpdateArgs = {
  attributes: ReadonlyArray<AttributeInput>;
  cartId: Scalars['ID']['input'];
};


export type MutationCartBuyerIdentityUpdateArgs = {
  buyerIdentity: CartBuyerIdentityInput;
  cartId: Scalars['ID']['input'];
};


export type MutationCartCreateArgs = {
  input: CartInput;
};


export type MutationCartDiscountCodesUpdateArgs = {
  cartId: Scalars['ID']['input'];
  discountCodes: InputMaybe<ReadonlyArray<Scalars['String']['input']>>;
};


export type MutationCartGiftCardCodesAddArgs = {
  cartId: Scalars['ID']['input'];
  giftCardCodes: ReadonlyArray<Scalars['String']['input']>;
};


export type MutationCartGiftCardCodesRemoveArgs = {
  appliedGiftCardIds: ReadonlyArray<Scalars['ID']['input']>;
  cartId: Scalars['ID']['input'];
};


export type MutationCartGiftCardCodesUpdateArgs = {
  cartId: Scalars['ID']['input'];
  giftCardCodes: ReadonlyArray<Scalars['String']['input']>;
};


export type MutationCartLinesAddArgs = {
  cartId: Scalars['ID']['input'];
  lines: ReadonlyArray<CartLineInput>;
};


export type MutationCartLinesRemoveArgs = {
  cartId: Scalars['ID']['input'];
  lineIds: ReadonlyArray<Scalars['ID']['input']>;
};


export type MutationCartLinesUpdateArgs = {
  cartId: Scalars['ID']['input'];
  lines: ReadonlyArray<CartLineUpdateInput>;
};


export type MutationCartNoteUpdateArgs = {
  cartId: Scalars['ID']['input'];
  note: Scalars['String']['input'];
};


export type MutationCheckoutCompleteArgs = {
  cartId: Scalars['ID']['input'];
  input: CheckoutCompleteInput;
};


export type MutationCustomerAccessTokenCreateArgs = {
  input: CustomerAccessTokenCreateInput;
};


export type MutationCustomerAccessTokenDeleteArgs = {
  customerAccessToken: Scalars['String']['input'];
};


export type MutationCustomerCreateArgs = {
  input: CustomerCreateInput;
};

export type Order = {
  readonly __typename?: 'Order';
  readonly currencyCode: Scalars['String']['output'];
  /** Discount code applied at checkout; null when the order has none. */
  readonly discountCode: Maybe<OrderDiscountCode>;
  readonly email: Maybe<Scalars['String']['output']>;
  readonly financialStatus: Maybe<OrderFinancialStatus>;
  readonly fulfillmentStatus: OrderFulfillmentStatus;
  readonly id: Scalars['ID']['output'];
  readonly lineItems: OrderLineItemConnection;
  /** Human-readable order name, e.g. "#1001". */
  readonly name: Scalars['String']['output'];
  readonly orderNumber: Scalars['Int']['output'];
  /** Handle of the commerce.json payment method chosen at checkout. */
  readonly paymentMethod: Maybe<Scalars['String']['output']>;
  readonly processedAt: Scalars['String']['output'];
  readonly shippingAddress: Maybe<MailingAddress>;
  /** Handle of the commerce.json shipping method chosen at checkout. */
  readonly shippingMethod: Maybe<Scalars['String']['output']>;
  readonly subtotalPrice: Maybe<MoneyV2>;
  readonly totalPrice: MoneyV2;
  readonly totalShippingPrice: MoneyV2;
  readonly totalTax: Maybe<MoneyV2>;
};


export type OrderLineItemsArgs = {
  first: InputMaybe<Scalars['Int']['input']>;
};

export type OrderConnection = {
  readonly __typename?: 'OrderConnection';
  readonly edges: ReadonlyArray<OrderEdge>;
  readonly nodes: ReadonlyArray<Order>;
  readonly totalCount: Scalars['Int']['output'];
};

export type OrderDiscountCode = {
  readonly __typename?: 'OrderDiscountCode';
  /** Merchandise discount, or the shipping charge waived by a free-shipping code. */
  readonly amount: MoneyV2;
  /** The code in its commerce.json spelling. */
  readonly code: Scalars['String']['output'];
  /** SHIPPING_LINE for a free-shipping code, LINE_ITEM for a percent or fixed code. */
  readonly targetType: DiscountApplicationTargetType;
};

export type OrderEdge = {
  readonly __typename?: 'OrderEdge';
  readonly node: Order;
};

export type OrderFinancialStatus =
  | 'AUTHORIZED'
  | 'PAID'
  | 'PARTIALLY_PAID'
  | 'PARTIALLY_REFUNDED'
  | 'PENDING'
  | 'REFUNDED'
  | 'VOIDED';

export type OrderFulfillmentStatus =
  | 'FULFILLED'
  | 'IN_PROGRESS'
  | 'ON_HOLD'
  | 'OPEN'
  | 'PARTIALLY_FULFILLED'
  | 'PENDING_FULFILLMENT'
  | 'RESTOCKED'
  | 'SCHEDULED'
  | 'UNFULFILLED';

export type OrderLineItem = {
  readonly __typename?: 'OrderLineItem';
  readonly originalTotalPrice: MoneyV2;
  readonly quantity: Scalars['Int']['output'];
  readonly title: Scalars['String']['output'];
  readonly variant: Maybe<ProductVariant>;
};

export type OrderLineItemConnection = {
  readonly __typename?: 'OrderLineItemConnection';
  readonly edges: ReadonlyArray<OrderLineItemEdge>;
  readonly nodes: ReadonlyArray<OrderLineItem>;
};

export type OrderLineItemEdge = {
  readonly __typename?: 'OrderLineItemEdge';
  readonly node: OrderLineItem;
};

export type OrderSortKeys =
  | 'ID'
  | 'PROCESSED_AT'
  | 'TOTAL_PRICE';

export type Page = {
  readonly __typename?: 'Page';
  readonly body: Scalars['String']['output'];
  readonly handle: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly seo: Seo;
  readonly title: Scalars['String']['output'];
  readonly trackingParameters: Maybe<Scalars['String']['output']>;
};

export type PageInfo = {
  readonly __typename?: 'PageInfo';
  readonly endCursor: Maybe<Scalars['String']['output']>;
  readonly hasNextPage: Scalars['Boolean']['output'];
  readonly hasPreviousPage: Scalars['Boolean']['output'];
  readonly startCursor: Maybe<Scalars['String']['output']>;
};

export type PaymentMethod = {
  readonly __typename?: 'PaymentMethod';
  readonly handle: Scalars['String']['output'];
  readonly title: Scalars['String']['output'];
};

export type PaymentSettings = {
  readonly __typename?: 'PaymentSettings';
  readonly acceptedCardBrands: ReadonlyArray<Scalars['String']['output']>;
  readonly countryCode: Scalars['String']['output'];
  readonly currencyCode: Scalars['String']['output'];
};

export type PredictiveSearchLimitScope =
  | 'ALL'
  | 'EACH';

export type PredictiveSearchResult = {
  readonly __typename?: 'PredictiveSearchResult';
  readonly articles: ReadonlyArray<Article>;
  readonly collections: ReadonlyArray<Collection>;
  readonly pages: ReadonlyArray<Page>;
  readonly products: ReadonlyArray<Product>;
  readonly queries: ReadonlyArray<SearchQuerySuggestion>;
};

export type PredictiveSearchType =
  | 'ARTICLE'
  | 'COLLECTION'
  | 'PAGE'
  | 'PRODUCT'
  | 'QUERY';

export type Product = {
  readonly __typename?: 'Product';
  readonly adjacentVariants: ReadonlyArray<ProductVariant>;
  readonly availableForSale: Scalars['Boolean']['output'];
  readonly compareAtPriceRange: ProductPriceRange;
  readonly createdAt: Maybe<Scalars['String']['output']>;
  readonly description: Scalars['String']['output'];
  readonly descriptionHtml: Scalars['String']['output'];
  readonly encodedVariantAvailability: Scalars['String']['output'];
  readonly encodedVariantExistence: Scalars['String']['output'];
  readonly featuredImage: Maybe<Image>;
  readonly handle: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly images: ImageConnection;
  readonly metafield: Maybe<Metafield>;
  readonly metafields: ReadonlyArray<Maybe<Metafield>>;
  readonly options: ReadonlyArray<ProductOption>;
  readonly priceRange: ProductPriceRange;
  readonly productType: Scalars['String']['output'];
  readonly publishedAt: Maybe<Scalars['String']['output']>;
  /**
   * The product's Reviews. The Storefront API has no Review type; shops show
   * Reviews through a review app.
   */
  readonly reviews: ReviewConnection;
  readonly selectedOrFirstAvailableVariant: Maybe<ProductVariant>;
  readonly seo: Seo;
  readonly tags: ReadonlyArray<Scalars['String']['output']>;
  readonly title: Scalars['String']['output'];
  readonly trackingParameters: Maybe<Scalars['String']['output']>;
  readonly updatedAt: Maybe<Scalars['String']['output']>;
  readonly variants: ProductVariantConnection;
  readonly vendor: Scalars['String']['output'];
};


export type ProductAdjacentVariantsArgs = {
  selectedOptions: InputMaybe<ReadonlyArray<SelectedOptionInput>>;
};


export type ProductImagesArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
};


export type ProductMetafieldArgs = {
  key: Scalars['String']['input'];
  namespace: Scalars['String']['input'];
};


export type ProductMetafieldsArgs = {
  identifiers: ReadonlyArray<HasMetafieldsIdentifier>;
};


export type ProductReviewsArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
  sortKey?: InputMaybe<ReviewSortKeys>;
};


export type ProductSelectedOrFirstAvailableVariantArgs = {
  caseInsensitiveMatch: InputMaybe<Scalars['Boolean']['input']>;
  ignoreUnknownOptions: InputMaybe<Scalars['Boolean']['input']>;
  selectedOptions: InputMaybe<ReadonlyArray<SelectedOptionInput>>;
};


export type ProductVariantsArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
};

export type ProductConnection = {
  readonly __typename?: 'ProductConnection';
  readonly edges: ReadonlyArray<ProductEdge>;
  readonly nodes: ReadonlyArray<Product>;
  readonly pageInfo: PageInfo;
  readonly totalCount: Maybe<Scalars['Int']['output']>;
};

export type ProductEdge = {
  readonly __typename?: 'ProductEdge';
  readonly cursor: Scalars['String']['output'];
  readonly node: Product;
};

export type ProductOption = {
  readonly __typename?: 'ProductOption';
  readonly id: Scalars['ID']['output'];
  readonly name: Scalars['String']['output'];
  readonly optionValues: ReadonlyArray<ProductOptionValue>;
  readonly values: ReadonlyArray<Scalars['String']['output']>;
};

export type ProductOptionValue = {
  readonly __typename?: 'ProductOptionValue';
  readonly firstSelectableVariant: Maybe<ProductVariant>;
  readonly name: Scalars['String']['output'];
  readonly swatch: Maybe<Swatch>;
};

export type ProductPriceRange = {
  readonly __typename?: 'ProductPriceRange';
  readonly maxVariantPrice: MoneyV2;
  readonly minVariantPrice: MoneyV2;
};

export type ProductRef = {
  readonly __typename?: 'ProductRef';
  readonly handle: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly title: Scalars['String']['output'];
  readonly vendor: Maybe<Scalars['String']['output']>;
};

export type ProductSortKeys =
  | 'BEST_SELLING'
  | 'CREATED_AT'
  | 'ID'
  | 'PRICE'
  | 'PRODUCT_TYPE'
  | 'RELEVANCE'
  | 'TITLE'
  | 'UPDATED_AT'
  | 'VENDOR';

export type ProductVariant = {
  readonly __typename?: 'ProductVariant';
  readonly availableForSale: Scalars['Boolean']['output'];
  readonly compareAtPrice: Maybe<MoneyV2>;
  readonly id: Scalars['ID']['output'];
  readonly image: Maybe<Image>;
  readonly metafield: Maybe<Metafield>;
  readonly metafields: ReadonlyArray<Maybe<Metafield>>;
  readonly price: MoneyV2;
  readonly product: ProductRef;
  readonly quantityAvailable: Maybe<Scalars['Int']['output']>;
  /** Resolves from the dataset's `variants[].requires_shipping` field; not hardcoded. */
  readonly requiresShipping: Scalars['Boolean']['output'];
  readonly selectedOptions: ReadonlyArray<SelectedOption>;
  readonly sku: Scalars['String']['output'];
  readonly title: Scalars['String']['output'];
  readonly unitPrice: Maybe<MoneyV2>;
};


export type ProductVariantMetafieldArgs = {
  key: Scalars['String']['input'];
  namespace: Scalars['String']['input'];
};


export type ProductVariantMetafieldsArgs = {
  identifiers: ReadonlyArray<HasMetafieldsIdentifier>;
};

export type ProductVariantConnection = {
  readonly __typename?: 'ProductVariantConnection';
  readonly edges: ReadonlyArray<ProductVariantEdge>;
  readonly nodes: ReadonlyArray<ProductVariant>;
};

export type ProductVariantEdge = {
  readonly __typename?: 'ProductVariantEdge';
  readonly node: ProductVariant;
};

export type Query = {
  readonly __typename?: 'Query';
  readonly blog: Maybe<Blog>;
  readonly blogs: BlogConnection;
  readonly cart: Maybe<Cart>;
  readonly collection: Maybe<Collection>;
  readonly collections: CollectionConnection;
  /** Shipping and payment options plus tax rules from commerce.json. */
  readonly commerceSettings: CommerceSettings;
  readonly customer: Maybe<Customer>;
  readonly localization: Localization;
  readonly menu: Maybe<Menu>;
  /** Look up any order by id, regardless of customer. */
  readonly order: Maybe<Order>;
  readonly page: Maybe<Page>;
  readonly predictiveSearch: Maybe<PredictiveSearchResult>;
  readonly product: Maybe<Product>;
  readonly productRecommendations: Maybe<ReadonlyArray<Product>>;
  readonly products: ProductConnection;
  readonly search: SearchResultItemConnection;
  readonly shop: Shop;
};


export type QueryBlogArgs = {
  handle: Scalars['String']['input'];
};


export type QueryBlogsArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  before: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
  last: InputMaybe<Scalars['Int']['input']>;
};


export type QueryCartArgs = {
  id: Scalars['ID']['input'];
};


export type QueryCollectionArgs = {
  handle: Scalars['String']['input'];
};


export type QueryCollectionsArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  before: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
  last: InputMaybe<Scalars['Int']['input']>;
  reverse: InputMaybe<Scalars['Boolean']['input']>;
  sortKey: InputMaybe<CollectionSortKeys>;
};


export type QueryCustomerArgs = {
  customerAccessToken: Scalars['String']['input'];
};


export type QueryMenuArgs = {
  handle: Scalars['String']['input'];
};


export type QueryOrderArgs = {
  id: Scalars['ID']['input'];
};


export type QueryPageArgs = {
  handle: Scalars['String']['input'];
};


export type QueryPredictiveSearchArgs = {
  limit: InputMaybe<Scalars['Int']['input']>;
  limitScope: InputMaybe<PredictiveSearchLimitScope>;
  query: Scalars['String']['input'];
  types: InputMaybe<ReadonlyArray<InputMaybe<PredictiveSearchType>>>;
};


export type QueryProductArgs = {
  handle: Scalars['String']['input'];
};


export type QueryProductRecommendationsArgs = {
  productId: Scalars['ID']['input'];
};


export type QueryProductsArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  before: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
  last: InputMaybe<Scalars['Int']['input']>;
  query: InputMaybe<Scalars['String']['input']>;
  reverse: InputMaybe<Scalars['Boolean']['input']>;
  sortKey: InputMaybe<ProductSortKeys>;
};


export type QuerySearchArgs = {
  after: InputMaybe<Scalars['String']['input']>;
  before: InputMaybe<Scalars['String']['input']>;
  first: InputMaybe<Scalars['Int']['input']>;
  last: InputMaybe<Scalars['Int']['input']>;
  prefix: InputMaybe<SearchPrefixQueryType>;
  query: Scalars['String']['input'];
  reverse: InputMaybe<Scalars['Boolean']['input']>;
  sortKey: InputMaybe<SearchSortKeys>;
  types: InputMaybe<ReadonlyArray<SearchType>>;
  unavailableProducts: InputMaybe<SearchUnavailableProductsType>;
};

/** One read-only product Review from reviews.json. */
export type Review = {
  readonly __typename?: 'Review';
  readonly body: Scalars['String']['output'];
  /** ISO 8601 date and time in UTC. */
  readonly createdAt: Scalars['String']['output'];
  readonly helpfulCount: Scalars['Int']['output'];
  readonly id: Scalars['ID']['output'];
  /** 1 to 5. */
  readonly rating: Scalars['Int']['output'];
  /** First name and last initial, e.g. "Maya R.". */
  readonly reviewerName: Scalars['String']['output'];
  readonly title: Scalars['String']['output'];
  /** The variant the reviewer bought; null when the product no longer has it. */
  readonly variant: Maybe<ProductVariant>;
  readonly verifiedBuyer: Scalars['Boolean']['output'];
};

export type ReviewConnection = {
  readonly __typename?: 'ReviewConnection';
  readonly edges: ReadonlyArray<ReviewEdge>;
  readonly nodes: ReadonlyArray<Review>;
  readonly pageInfo: PageInfo;
};

export type ReviewEdge = {
  readonly __typename?: 'ReviewEdge';
  readonly cursor: Scalars['String']['output'];
  readonly node: Review;
};

/**
 * Review orders. Ties put the more recent Review first, then keep the
 * reviews.json order.
 */
export type ReviewSortKeys =
  | 'HIGHEST_RATING'
  | 'LOWEST_RATING'
  | 'MOST_HELPFUL'
  | 'MOST_RECENT';

export type Seo = {
  readonly __typename?: 'SEO';
  readonly description: Maybe<Scalars['String']['output']>;
  readonly title: Maybe<Scalars['String']['output']>;
};

export type SearchPrefixQueryType =
  | 'LAST'
  | 'NONE';

export type SearchQuerySuggestion = {
  readonly __typename?: 'SearchQuerySuggestion';
  readonly styledText: Scalars['String']['output'];
  readonly text: Scalars['String']['output'];
  readonly trackingParameters: Maybe<Scalars['String']['output']>;
};

export type SearchResultItem = Article | Page | Product;

export type SearchResultItemConnection = {
  readonly __typename?: 'SearchResultItemConnection';
  readonly edges: ReadonlyArray<SearchResultItemEdge>;
  readonly nodes: ReadonlyArray<SearchResultItem>;
  readonly pageInfo: PageInfo;
  readonly totalCount: Scalars['Int']['output'];
};

export type SearchResultItemEdge = {
  readonly __typename?: 'SearchResultItemEdge';
  readonly cursor: Scalars['String']['output'];
  readonly node: SearchResultItem;
};

export type SearchSortKeys =
  | 'PRICE'
  | 'RELEVANCE';

export type SearchType =
  | 'ARTICLE'
  | 'PAGE'
  | 'PRODUCT';

export type SearchUnavailableProductsType =
  | 'HIDE'
  | 'LAST'
  | 'SHOW';

export type SelectedOption = {
  readonly __typename?: 'SelectedOption';
  readonly name: Scalars['String']['output'];
  readonly value: Scalars['String']['output'];
};

export type SelectedOptionInput = {
  readonly name: Scalars['String']['input'];
  readonly value: Scalars['String']['input'];
};

export type ShippingMethod = {
  readonly __typename?: 'ShippingMethod';
  readonly handle: Scalars['String']['output'];
  readonly price: MoneyV2;
  readonly title: Scalars['String']['output'];
};

export type Shop = {
  readonly __typename?: 'Shop';
  readonly brand: Maybe<Brand>;
  readonly description: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly metafield: Maybe<Metafield>;
  readonly metafields: ReadonlyArray<Maybe<Metafield>>;
  readonly name: Scalars['String']['output'];
  readonly paymentSettings: PaymentSettings;
  readonly primaryDomain: ShopDomain;
  readonly privacyPolicy: Maybe<ShopPolicy>;
  readonly refundPolicy: Maybe<ShopPolicy>;
  readonly shippingPolicy: Maybe<ShopPolicy>;
  readonly subscriptionPolicy: Maybe<ShopPolicy>;
  readonly termsOfService: Maybe<ShopPolicy>;
};


export type ShopMetafieldArgs = {
  key: Scalars['String']['input'];
  namespace: Scalars['String']['input'];
};


export type ShopMetafieldsArgs = {
  identifiers: ReadonlyArray<HasMetafieldsIdentifier>;
};

export type ShopDomain = {
  readonly __typename?: 'ShopDomain';
  readonly host: Scalars['String']['output'];
  readonly url: Scalars['String']['output'];
};

export type ShopPolicy = {
  readonly __typename?: 'ShopPolicy';
  readonly body: Scalars['String']['output'];
  readonly handle: Scalars['String']['output'];
  readonly id: Scalars['ID']['output'];
  readonly title: Scalars['String']['output'];
  readonly url: Scalars['String']['output'];
};

export type Swatch = {
  readonly __typename?: 'Swatch';
  readonly color: Maybe<Scalars['String']['output']>;
  readonly image: Maybe<SwatchMedia>;
};

export type SwatchMedia = {
  readonly __typename?: 'SwatchMedia';
  readonly previewImage: Maybe<Image>;
};

export type UserError = {
  readonly __typename?: 'UserError';
  readonly field: Maybe<ReadonlyArray<Scalars['String']['output']>>;
  readonly message: Scalars['String']['output'];
};

export type VisitorConsent = {
  readonly analytics?: InputMaybe<Scalars['Boolean']['input']>;
  readonly marketing?: InputMaybe<Scalars['Boolean']['input']>;
  readonly preferences?: InputMaybe<Scalars['Boolean']['input']>;
  readonly saleOfData?: InputMaybe<Scalars['Boolean']['input']>;
};



export type ResolverTypeWrapper<T> = Promise<T> | T;


export type ResolverWithResolve<TResult, TParent, TContext, TArgs> = {
  resolve: ResolverFn<TResult, TParent, TContext, TArgs>;
};
export type Resolver<TResult, TParent = {}, TContext = {}, TArgs = {}> = ResolverFn<TResult, TParent, TContext, TArgs> | ResolverWithResolve<TResult, TParent, TContext, TArgs>;

export type ResolverFn<TResult, TParent, TContext, TArgs> = (
  parent: TParent,
  args: TArgs,
  context: TContext,
  info: GraphQLResolveInfo
) => Promise<TResult> | TResult;

export type SubscriptionSubscribeFn<TResult, TParent, TContext, TArgs> = (
  parent: TParent,
  args: TArgs,
  context: TContext,
  info: GraphQLResolveInfo
) => AsyncIterable<TResult> | Promise<AsyncIterable<TResult>>;

export type SubscriptionResolveFn<TResult, TParent, TContext, TArgs> = (
  parent: TParent,
  args: TArgs,
  context: TContext,
  info: GraphQLResolveInfo
) => TResult | Promise<TResult>;

export interface SubscriptionSubscriberObject<TResult, TKey extends string, TParent, TContext, TArgs> {
  subscribe: SubscriptionSubscribeFn<{ [key in TKey]: TResult }, TParent, TContext, TArgs>;
  resolve?: SubscriptionResolveFn<TResult, { [key in TKey]: TResult }, TContext, TArgs>;
}

export interface SubscriptionResolverObject<TResult, TParent, TContext, TArgs> {
  subscribe: SubscriptionSubscribeFn<any, TParent, TContext, TArgs>;
  resolve: SubscriptionResolveFn<TResult, any, TContext, TArgs>;
}

export type SubscriptionObject<TResult, TKey extends string, TParent, TContext, TArgs> =
  | SubscriptionSubscriberObject<TResult, TKey, TParent, TContext, TArgs>
  | SubscriptionResolverObject<TResult, TParent, TContext, TArgs>;

export type SubscriptionResolver<TResult, TKey extends string, TParent = {}, TContext = {}, TArgs = {}> =
  | ((...args: any[]) => SubscriptionObject<TResult, TKey, TParent, TContext, TArgs>)
  | SubscriptionObject<TResult, TKey, TParent, TContext, TArgs>;

export type TypeResolveFn<TTypes, TParent = {}, TContext = {}> = (
  parent: TParent,
  context: TContext,
  info: GraphQLResolveInfo
) => Maybe<TTypes> | Promise<Maybe<TTypes>>;

export type IsTypeOfResolverFn<T = {}, TContext = {}> = (obj: T, context: TContext, info: GraphQLResolveInfo) => boolean | Promise<boolean>;

export type NextResolverFn<T> = () => Promise<T>;

export type DirectiveResolverFn<TResult = {}, TParent = {}, TContext = {}, TArgs = {}> = (
  next: NextResolverFn<TResult>,
  parent: TParent,
  args: TArgs,
  context: TContext,
  info: GraphQLResolveInfo
) => TResult | Promise<TResult>;

/** Mapping of union types */
export type ResolversUnionTypes<_RefType extends Record<string, unknown>> = {
  BaseCartLine: ( Omit<CartLine, 'merchandise'> & { merchandise: _RefType['Merchandise'] } ) | ( Omit<ComponentizableCartLine, 'lineComponents' | 'merchandise'> & { lineComponents: ReadonlyArray<_RefType['CartLine']>, merchandise: _RefType['Merchandise'] } );
  Merchandise: ( Omit<ProductVariant, 'metafield' | 'metafields'> & { metafield?: Maybe<_RefType['Metafield']>, metafields: ReadonlyArray<Maybe<_RefType['Metafield']>> } );
  MetafieldParentResource: ( Omit<Collection, 'metafield' | 'metafields' | 'products'> & { metafield?: Maybe<_RefType['Metafield']>, metafields: ReadonlyArray<Maybe<_RefType['Metafield']>>, products: _RefType['ProductConnection'] } ) | ( Omit<Product, 'adjacentVariants' | 'metafield' | 'metafields' | 'options' | 'reviews' | 'selectedOrFirstAvailableVariant' | 'variants'> & { adjacentVariants: ReadonlyArray<_RefType['ProductVariant']>, metafield?: Maybe<_RefType['Metafield']>, metafields: ReadonlyArray<Maybe<_RefType['Metafield']>>, options: ReadonlyArray<_RefType['ProductOption']>, reviews: _RefType['ReviewConnection'], selectedOrFirstAvailableVariant?: Maybe<_RefType['ProductVariant']>, variants: _RefType['ProductVariantConnection'] } ) | ( Omit<ProductVariant, 'metafield' | 'metafields'> & { metafield?: Maybe<_RefType['Metafield']>, metafields: ReadonlyArray<Maybe<_RefType['Metafield']>> } );
  MetafieldReference: ( Omit<Collection, 'metafield' | 'metafields' | 'products'> & { metafield?: Maybe<_RefType['Metafield']>, metafields: ReadonlyArray<Maybe<_RefType['Metafield']>>, products: _RefType['ProductConnection'] } ) | ( Page ) | ( Omit<Product, 'adjacentVariants' | 'metafield' | 'metafields' | 'options' | 'reviews' | 'selectedOrFirstAvailableVariant' | 'variants'> & { adjacentVariants: ReadonlyArray<_RefType['ProductVariant']>, metafield?: Maybe<_RefType['Metafield']>, metafields: ReadonlyArray<Maybe<_RefType['Metafield']>>, options: ReadonlyArray<_RefType['ProductOption']>, reviews: _RefType['ReviewConnection'], selectedOrFirstAvailableVariant?: Maybe<_RefType['ProductVariant']>, variants: _RefType['ProductVariantConnection'] } );
  SearchResultItem: ( Article ) | ( Page ) | ( Omit<Product, 'adjacentVariants' | 'metafield' | 'metafields' | 'options' | 'reviews' | 'selectedOrFirstAvailableVariant' | 'variants'> & { adjacentVariants: ReadonlyArray<_RefType['ProductVariant']>, metafield?: Maybe<_RefType['Metafield']>, metafields: ReadonlyArray<Maybe<_RefType['Metafield']>>, options: ReadonlyArray<_RefType['ProductOption']>, reviews: _RefType['ReviewConnection'], selectedOrFirstAvailableVariant?: Maybe<_RefType['ProductVariant']>, variants: _RefType['ProductVariantConnection'] } );
};

/** Mapping of interface types */
export type ResolversInterfaceTypes<_RefType extends Record<string, unknown>> = {
  CartDiscountAllocation: ( CartCodeDiscountAllocation );
};

/** Mapping between all available schema types and the resolvers types */
export type ResolversTypes = {
  AppliedGiftCard: ResolverTypeWrapper<AppliedGiftCard>;
  Article: ResolverTypeWrapper<Article>;
  ArticleAuthor: ResolverTypeWrapper<ArticleAuthor>;
  ArticleConnection: ResolverTypeWrapper<ArticleConnection>;
  ArticleEdge: ResolverTypeWrapper<ArticleEdge>;
  Attribute: ResolverTypeWrapper<Attribute>;
  AttributeInput: AttributeInput;
  BaseCartLine: ResolverTypeWrapper<ResolversUnionTypes<ResolversTypes>['BaseCartLine']>;
  Blog: ResolverTypeWrapper<Blog>;
  BlogConnection: ResolverTypeWrapper<BlogConnection>;
  BlogEdge: ResolverTypeWrapper<BlogEdge>;
  BlogRef: ResolverTypeWrapper<BlogRef>;
  Boolean: ResolverTypeWrapper<Scalars['Boolean']['output']>;
  Brand: ResolverTypeWrapper<Brand>;
  BrandColorGroup: ResolverTypeWrapper<BrandColorGroup>;
  BrandColors: ResolverTypeWrapper<BrandColors>;
  Cart: ResolverTypeWrapper<Omit<Cart, 'buyerIdentity' | 'discountAllocations' | 'lines'> & { buyerIdentity: ResolversTypes['CartBuyerIdentity'], discountAllocations: ReadonlyArray<ResolversTypes['CartDiscountAllocation']>, lines: ResolversTypes['CartLineConnection'] }>;
  CartAttributesUpdatePayload: ResolverTypeWrapper<Omit<CartAttributesUpdatePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartBuyerIdentity: ResolverTypeWrapper<Omit<CartBuyerIdentity, 'customer'> & { customer?: Maybe<ResolversTypes['Customer']> }>;
  CartBuyerIdentityInput: CartBuyerIdentityInput;
  CartBuyerIdentityUpdatePayload: ResolverTypeWrapper<Omit<CartBuyerIdentityUpdatePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartCodeDiscountAllocation: ResolverTypeWrapper<CartCodeDiscountAllocation>;
  CartCost: ResolverTypeWrapper<CartCost>;
  CartCreatePayload: ResolverTypeWrapper<Omit<CartCreatePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartDiscountAllocation: ResolverTypeWrapper<ResolversInterfaceTypes<ResolversTypes>['CartDiscountAllocation']>;
  CartDiscountCode: ResolverTypeWrapper<CartDiscountCode>;
  CartDiscountCodesUpdatePayload: ResolverTypeWrapper<Omit<CartDiscountCodesUpdatePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartGiftCardCodesAddPayload: ResolverTypeWrapper<Omit<CartGiftCardCodesAddPayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartGiftCardCodesRemovePayload: ResolverTypeWrapper<Omit<CartGiftCardCodesRemovePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartGiftCardCodesUpdatePayload: ResolverTypeWrapper<Omit<CartGiftCardCodesUpdatePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartInput: CartInput;
  CartLine: ResolverTypeWrapper<Omit<CartLine, 'merchandise'> & { merchandise: ResolversTypes['Merchandise'] }>;
  CartLineConnection: ResolverTypeWrapper<Omit<CartLineConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversTypes['CartLineEdge']>, nodes: ReadonlyArray<ResolversTypes['BaseCartLine']> }>;
  CartLineCost: ResolverTypeWrapper<CartLineCost>;
  CartLineEdge: ResolverTypeWrapper<Omit<CartLineEdge, 'node'> & { node: ResolversTypes['BaseCartLine'] }>;
  CartLineInput: CartLineInput;
  CartLineParent: ResolverTypeWrapper<CartLineParent>;
  CartLineParentRelationship: ResolverTypeWrapper<CartLineParentRelationship>;
  CartLineUpdateInput: CartLineUpdateInput;
  CartLinesAddPayload: ResolverTypeWrapper<Omit<CartLinesAddPayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartLinesRemovePayload: ResolverTypeWrapper<Omit<CartLinesRemovePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartLinesUpdatePayload: ResolverTypeWrapper<Omit<CartLinesUpdatePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartNoteUpdatePayload: ResolverTypeWrapper<Omit<CartNoteUpdatePayload, 'cart'> & { cart?: Maybe<ResolversTypes['Cart']> }>;
  CartUserError: ResolverTypeWrapper<CartUserError>;
  CartWarning: ResolverTypeWrapper<CartWarning>;
  CheckoutCompleteInput: CheckoutCompleteInput;
  CheckoutCompletePayload: ResolverTypeWrapper<Omit<CheckoutCompletePayload, 'order'> & { order?: Maybe<ResolversTypes['Order']> }>;
  CheckoutUserError: ResolverTypeWrapper<CheckoutUserError>;
  Collection: ResolverTypeWrapper<Omit<Collection, 'metafield' | 'metafields' | 'products'> & { metafield?: Maybe<ResolversTypes['Metafield']>, metafields: ReadonlyArray<Maybe<ResolversTypes['Metafield']>>, products: ResolversTypes['ProductConnection'] }>;
  CollectionConnection: ResolverTypeWrapper<Omit<CollectionConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversTypes['CollectionEdge']>, nodes: ReadonlyArray<ResolversTypes['Collection']> }>;
  CollectionEdge: ResolverTypeWrapper<Omit<CollectionEdge, 'node'> & { node: ResolversTypes['Collection'] }>;
  CollectionSortKeys: CollectionSortKeys;
  CommerceSettings: ResolverTypeWrapper<CommerceSettings>;
  ComponentizableCartLine: ResolverTypeWrapper<Omit<ComponentizableCartLine, 'lineComponents' | 'merchandise'> & { lineComponents: ReadonlyArray<ResolversTypes['CartLine']>, merchandise: ResolversTypes['Merchandise'] }>;
  Country: ResolverTypeWrapper<Country>;
  CountryCode: CountryCode;
  CountryCurrency: ResolverTypeWrapper<CountryCurrency>;
  Currency: ResolverTypeWrapper<Currency>;
  CurrencyCode: CurrencyCode;
  Customer: ResolverTypeWrapper<Omit<Customer, 'orders'> & { orders: ResolversTypes['OrderConnection'] }>;
  CustomerAccessToken: ResolverTypeWrapper<CustomerAccessToken>;
  CustomerAccessTokenCreateInput: CustomerAccessTokenCreateInput;
  CustomerAccessTokenCreatePayload: ResolverTypeWrapper<CustomerAccessTokenCreatePayload>;
  CustomerAccessTokenDeletePayload: ResolverTypeWrapper<CustomerAccessTokenDeletePayload>;
  CustomerCreateInput: CustomerCreateInput;
  CustomerCreatePayload: ResolverTypeWrapper<Omit<CustomerCreatePayload, 'customer'> & { customer?: Maybe<ResolversTypes['Customer']> }>;
  CustomerErrorCode: CustomerErrorCode;
  CustomerUserError: ResolverTypeWrapper<CustomerUserError>;
  DiscountApplicationTargetType: DiscountApplicationTargetType;
  Float: ResolverTypeWrapper<Scalars['Float']['output']>;
  HasMetafieldsIdentifier: HasMetafieldsIdentifier;
  ID: ResolverTypeWrapper<Scalars['ID']['output']>;
  Image: ResolverTypeWrapper<Image>;
  ImageConnection: ResolverTypeWrapper<ImageConnection>;
  ImageEdge: ResolverTypeWrapper<ImageEdge>;
  Int: ResolverTypeWrapper<Scalars['Int']['output']>;
  Language: ResolverTypeWrapper<Language>;
  LanguageCode: LanguageCode;
  Localization: ResolverTypeWrapper<Localization>;
  LocalizationCountry: ResolverTypeWrapper<LocalizationCountry>;
  MailingAddress: ResolverTypeWrapper<MailingAddress>;
  MailingAddressConnection: ResolverTypeWrapper<MailingAddressConnection>;
  MailingAddressEdge: ResolverTypeWrapper<MailingAddressEdge>;
  MailingAddressInput: MailingAddressInput;
  MediaImage: ResolverTypeWrapper<MediaImage>;
  Menu: ResolverTypeWrapper<Menu>;
  MenuItem: ResolverTypeWrapper<MenuItem>;
  Merchandise: ResolverTypeWrapper<ResolversUnionTypes<ResolversTypes>['Merchandise']>;
  Metafield: ResolverTypeWrapper<Omit<Metafield, 'parentResource' | 'reference'> & { parentResource?: Maybe<ResolversTypes['MetafieldParentResource']>, reference?: Maybe<ResolversTypes['MetafieldReference']> }>;
  MetafieldParentResource: ResolverTypeWrapper<ResolversUnionTypes<ResolversTypes>['MetafieldParentResource']>;
  MetafieldReference: ResolverTypeWrapper<ResolversUnionTypes<ResolversTypes>['MetafieldReference']>;
  MoneyV2: ResolverTypeWrapper<MoneyV2>;
  Mutation: ResolverTypeWrapper<{}>;
  Order: ResolverTypeWrapper<Omit<Order, 'discountCode' | 'lineItems'> & { discountCode?: Maybe<ResolversTypes['OrderDiscountCode']>, lineItems: ResolversTypes['OrderLineItemConnection'] }>;
  OrderConnection: ResolverTypeWrapper<Omit<OrderConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversTypes['OrderEdge']>, nodes: ReadonlyArray<ResolversTypes['Order']> }>;
  OrderDiscountCode: ResolverTypeWrapper<OrderDiscountCode>;
  OrderEdge: ResolverTypeWrapper<Omit<OrderEdge, 'node'> & { node: ResolversTypes['Order'] }>;
  OrderFinancialStatus: OrderFinancialStatus;
  OrderFulfillmentStatus: OrderFulfillmentStatus;
  OrderLineItem: ResolverTypeWrapper<Omit<OrderLineItem, 'variant'> & { variant?: Maybe<ResolversTypes['ProductVariant']> }>;
  OrderLineItemConnection: ResolverTypeWrapper<Omit<OrderLineItemConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversTypes['OrderLineItemEdge']>, nodes: ReadonlyArray<ResolversTypes['OrderLineItem']> }>;
  OrderLineItemEdge: ResolverTypeWrapper<Omit<OrderLineItemEdge, 'node'> & { node: ResolversTypes['OrderLineItem'] }>;
  OrderSortKeys: OrderSortKeys;
  Page: ResolverTypeWrapper<Page>;
  PageInfo: ResolverTypeWrapper<PageInfo>;
  PaymentMethod: ResolverTypeWrapper<PaymentMethod>;
  PaymentSettings: ResolverTypeWrapper<PaymentSettings>;
  PredictiveSearchLimitScope: PredictiveSearchLimitScope;
  PredictiveSearchResult: ResolverTypeWrapper<Omit<PredictiveSearchResult, 'collections' | 'products'> & { collections: ReadonlyArray<ResolversTypes['Collection']>, products: ReadonlyArray<ResolversTypes['Product']> }>;
  PredictiveSearchType: PredictiveSearchType;
  Product: ResolverTypeWrapper<Omit<Product, 'adjacentVariants' | 'metafield' | 'metafields' | 'options' | 'reviews' | 'selectedOrFirstAvailableVariant' | 'variants'> & { adjacentVariants: ReadonlyArray<ResolversTypes['ProductVariant']>, metafield?: Maybe<ResolversTypes['Metafield']>, metafields: ReadonlyArray<Maybe<ResolversTypes['Metafield']>>, options: ReadonlyArray<ResolversTypes['ProductOption']>, reviews: ResolversTypes['ReviewConnection'], selectedOrFirstAvailableVariant?: Maybe<ResolversTypes['ProductVariant']>, variants: ResolversTypes['ProductVariantConnection'] }>;
  ProductConnection: ResolverTypeWrapper<Omit<ProductConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversTypes['ProductEdge']>, nodes: ReadonlyArray<ResolversTypes['Product']> }>;
  ProductEdge: ResolverTypeWrapper<Omit<ProductEdge, 'node'> & { node: ResolversTypes['Product'] }>;
  ProductOption: ResolverTypeWrapper<Omit<ProductOption, 'optionValues'> & { optionValues: ReadonlyArray<ResolversTypes['ProductOptionValue']> }>;
  ProductOptionValue: ResolverTypeWrapper<Omit<ProductOptionValue, 'firstSelectableVariant'> & { firstSelectableVariant?: Maybe<ResolversTypes['ProductVariant']> }>;
  ProductPriceRange: ResolverTypeWrapper<ProductPriceRange>;
  ProductRef: ResolverTypeWrapper<ProductRef>;
  ProductSortKeys: ProductSortKeys;
  ProductVariant: ResolverTypeWrapper<Omit<ProductVariant, 'metafield' | 'metafields'> & { metafield?: Maybe<ResolversTypes['Metafield']>, metafields: ReadonlyArray<Maybe<ResolversTypes['Metafield']>> }>;
  ProductVariantConnection: ResolverTypeWrapper<Omit<ProductVariantConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversTypes['ProductVariantEdge']>, nodes: ReadonlyArray<ResolversTypes['ProductVariant']> }>;
  ProductVariantEdge: ResolverTypeWrapper<Omit<ProductVariantEdge, 'node'> & { node: ResolversTypes['ProductVariant'] }>;
  Query: ResolverTypeWrapper<{}>;
  Review: ResolverTypeWrapper<Omit<Review, 'variant'> & { variant?: Maybe<ResolversTypes['ProductVariant']> }>;
  ReviewConnection: ResolverTypeWrapper<Omit<ReviewConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversTypes['ReviewEdge']>, nodes: ReadonlyArray<ResolversTypes['Review']> }>;
  ReviewEdge: ResolverTypeWrapper<Omit<ReviewEdge, 'node'> & { node: ResolversTypes['Review'] }>;
  ReviewSortKeys: ReviewSortKeys;
  SEO: ResolverTypeWrapper<Seo>;
  SearchPrefixQueryType: SearchPrefixQueryType;
  SearchQuerySuggestion: ResolverTypeWrapper<SearchQuerySuggestion>;
  SearchResultItem: ResolverTypeWrapper<ResolversUnionTypes<ResolversTypes>['SearchResultItem']>;
  SearchResultItemConnection: ResolverTypeWrapper<Omit<SearchResultItemConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversTypes['SearchResultItemEdge']>, nodes: ReadonlyArray<ResolversTypes['SearchResultItem']> }>;
  SearchResultItemEdge: ResolverTypeWrapper<Omit<SearchResultItemEdge, 'node'> & { node: ResolversTypes['SearchResultItem'] }>;
  SearchSortKeys: SearchSortKeys;
  SearchType: SearchType;
  SearchUnavailableProductsType: SearchUnavailableProductsType;
  SelectedOption: ResolverTypeWrapper<SelectedOption>;
  SelectedOptionInput: SelectedOptionInput;
  ShippingMethod: ResolverTypeWrapper<ShippingMethod>;
  Shop: ResolverTypeWrapper<Omit<Shop, 'metafield' | 'metafields'> & { metafield?: Maybe<ResolversTypes['Metafield']>, metafields: ReadonlyArray<Maybe<ResolversTypes['Metafield']>> }>;
  ShopDomain: ResolverTypeWrapper<ShopDomain>;
  ShopPolicy: ResolverTypeWrapper<ShopPolicy>;
  String: ResolverTypeWrapper<Scalars['String']['output']>;
  Swatch: ResolverTypeWrapper<Swatch>;
  SwatchMedia: ResolverTypeWrapper<SwatchMedia>;
  UserError: ResolverTypeWrapper<UserError>;
  VisitorConsent: VisitorConsent;
};

/** Mapping between all available schema types and the resolvers parents */
export type ResolversParentTypes = {
  AppliedGiftCard: AppliedGiftCard;
  Article: Article;
  ArticleAuthor: ArticleAuthor;
  ArticleConnection: ArticleConnection;
  ArticleEdge: ArticleEdge;
  Attribute: Attribute;
  AttributeInput: AttributeInput;
  BaseCartLine: ResolversUnionTypes<ResolversParentTypes>['BaseCartLine'];
  Blog: Blog;
  BlogConnection: BlogConnection;
  BlogEdge: BlogEdge;
  BlogRef: BlogRef;
  Boolean: Scalars['Boolean']['output'];
  Brand: Brand;
  BrandColorGroup: BrandColorGroup;
  BrandColors: BrandColors;
  Cart: Omit<Cart, 'buyerIdentity' | 'discountAllocations' | 'lines'> & { buyerIdentity: ResolversParentTypes['CartBuyerIdentity'], discountAllocations: ReadonlyArray<ResolversParentTypes['CartDiscountAllocation']>, lines: ResolversParentTypes['CartLineConnection'] };
  CartAttributesUpdatePayload: Omit<CartAttributesUpdatePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartBuyerIdentity: Omit<CartBuyerIdentity, 'customer'> & { customer?: Maybe<ResolversParentTypes['Customer']> };
  CartBuyerIdentityInput: CartBuyerIdentityInput;
  CartBuyerIdentityUpdatePayload: Omit<CartBuyerIdentityUpdatePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartCodeDiscountAllocation: CartCodeDiscountAllocation;
  CartCost: CartCost;
  CartCreatePayload: Omit<CartCreatePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartDiscountAllocation: ResolversInterfaceTypes<ResolversParentTypes>['CartDiscountAllocation'];
  CartDiscountCode: CartDiscountCode;
  CartDiscountCodesUpdatePayload: Omit<CartDiscountCodesUpdatePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartGiftCardCodesAddPayload: Omit<CartGiftCardCodesAddPayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartGiftCardCodesRemovePayload: Omit<CartGiftCardCodesRemovePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartGiftCardCodesUpdatePayload: Omit<CartGiftCardCodesUpdatePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartInput: CartInput;
  CartLine: Omit<CartLine, 'merchandise'> & { merchandise: ResolversParentTypes['Merchandise'] };
  CartLineConnection: Omit<CartLineConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversParentTypes['CartLineEdge']>, nodes: ReadonlyArray<ResolversParentTypes['BaseCartLine']> };
  CartLineCost: CartLineCost;
  CartLineEdge: Omit<CartLineEdge, 'node'> & { node: ResolversParentTypes['BaseCartLine'] };
  CartLineInput: CartLineInput;
  CartLineParent: CartLineParent;
  CartLineParentRelationship: CartLineParentRelationship;
  CartLineUpdateInput: CartLineUpdateInput;
  CartLinesAddPayload: Omit<CartLinesAddPayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartLinesRemovePayload: Omit<CartLinesRemovePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartLinesUpdatePayload: Omit<CartLinesUpdatePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartNoteUpdatePayload: Omit<CartNoteUpdatePayload, 'cart'> & { cart?: Maybe<ResolversParentTypes['Cart']> };
  CartUserError: CartUserError;
  CartWarning: CartWarning;
  CheckoutCompleteInput: CheckoutCompleteInput;
  CheckoutCompletePayload: Omit<CheckoutCompletePayload, 'order'> & { order?: Maybe<ResolversParentTypes['Order']> };
  CheckoutUserError: CheckoutUserError;
  Collection: Omit<Collection, 'metafield' | 'metafields' | 'products'> & { metafield?: Maybe<ResolversParentTypes['Metafield']>, metafields: ReadonlyArray<Maybe<ResolversParentTypes['Metafield']>>, products: ResolversParentTypes['ProductConnection'] };
  CollectionConnection: Omit<CollectionConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversParentTypes['CollectionEdge']>, nodes: ReadonlyArray<ResolversParentTypes['Collection']> };
  CollectionEdge: Omit<CollectionEdge, 'node'> & { node: ResolversParentTypes['Collection'] };
  CommerceSettings: CommerceSettings;
  ComponentizableCartLine: Omit<ComponentizableCartLine, 'lineComponents' | 'merchandise'> & { lineComponents: ReadonlyArray<ResolversParentTypes['CartLine']>, merchandise: ResolversParentTypes['Merchandise'] };
  Country: Country;
  CountryCurrency: CountryCurrency;
  Currency: Currency;
  Customer: Omit<Customer, 'orders'> & { orders: ResolversParentTypes['OrderConnection'] };
  CustomerAccessToken: CustomerAccessToken;
  CustomerAccessTokenCreateInput: CustomerAccessTokenCreateInput;
  CustomerAccessTokenCreatePayload: CustomerAccessTokenCreatePayload;
  CustomerAccessTokenDeletePayload: CustomerAccessTokenDeletePayload;
  CustomerCreateInput: CustomerCreateInput;
  CustomerCreatePayload: Omit<CustomerCreatePayload, 'customer'> & { customer?: Maybe<ResolversParentTypes['Customer']> };
  CustomerUserError: CustomerUserError;
  Float: Scalars['Float']['output'];
  HasMetafieldsIdentifier: HasMetafieldsIdentifier;
  ID: Scalars['ID']['output'];
  Image: Image;
  ImageConnection: ImageConnection;
  ImageEdge: ImageEdge;
  Int: Scalars['Int']['output'];
  Language: Language;
  Localization: Localization;
  LocalizationCountry: LocalizationCountry;
  MailingAddress: MailingAddress;
  MailingAddressConnection: MailingAddressConnection;
  MailingAddressEdge: MailingAddressEdge;
  MailingAddressInput: MailingAddressInput;
  MediaImage: MediaImage;
  Menu: Menu;
  MenuItem: MenuItem;
  Merchandise: ResolversUnionTypes<ResolversParentTypes>['Merchandise'];
  Metafield: Omit<Metafield, 'parentResource' | 'reference'> & { parentResource?: Maybe<ResolversParentTypes['MetafieldParentResource']>, reference?: Maybe<ResolversParentTypes['MetafieldReference']> };
  MetafieldParentResource: ResolversUnionTypes<ResolversParentTypes>['MetafieldParentResource'];
  MetafieldReference: ResolversUnionTypes<ResolversParentTypes>['MetafieldReference'];
  MoneyV2: MoneyV2;
  Mutation: {};
  Order: Omit<Order, 'discountCode' | 'lineItems'> & { discountCode?: Maybe<ResolversParentTypes['OrderDiscountCode']>, lineItems: ResolversParentTypes['OrderLineItemConnection'] };
  OrderConnection: Omit<OrderConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversParentTypes['OrderEdge']>, nodes: ReadonlyArray<ResolversParentTypes['Order']> };
  OrderDiscountCode: OrderDiscountCode;
  OrderEdge: Omit<OrderEdge, 'node'> & { node: ResolversParentTypes['Order'] };
  OrderLineItem: Omit<OrderLineItem, 'variant'> & { variant?: Maybe<ResolversParentTypes['ProductVariant']> };
  OrderLineItemConnection: Omit<OrderLineItemConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversParentTypes['OrderLineItemEdge']>, nodes: ReadonlyArray<ResolversParentTypes['OrderLineItem']> };
  OrderLineItemEdge: Omit<OrderLineItemEdge, 'node'> & { node: ResolversParentTypes['OrderLineItem'] };
  Page: Page;
  PageInfo: PageInfo;
  PaymentMethod: PaymentMethod;
  PaymentSettings: PaymentSettings;
  PredictiveSearchResult: Omit<PredictiveSearchResult, 'collections' | 'products'> & { collections: ReadonlyArray<ResolversParentTypes['Collection']>, products: ReadonlyArray<ResolversParentTypes['Product']> };
  Product: Omit<Product, 'adjacentVariants' | 'metafield' | 'metafields' | 'options' | 'reviews' | 'selectedOrFirstAvailableVariant' | 'variants'> & { adjacentVariants: ReadonlyArray<ResolversParentTypes['ProductVariant']>, metafield?: Maybe<ResolversParentTypes['Metafield']>, metafields: ReadonlyArray<Maybe<ResolversParentTypes['Metafield']>>, options: ReadonlyArray<ResolversParentTypes['ProductOption']>, reviews: ResolversParentTypes['ReviewConnection'], selectedOrFirstAvailableVariant?: Maybe<ResolversParentTypes['ProductVariant']>, variants: ResolversParentTypes['ProductVariantConnection'] };
  ProductConnection: Omit<ProductConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversParentTypes['ProductEdge']>, nodes: ReadonlyArray<ResolversParentTypes['Product']> };
  ProductEdge: Omit<ProductEdge, 'node'> & { node: ResolversParentTypes['Product'] };
  ProductOption: Omit<ProductOption, 'optionValues'> & { optionValues: ReadonlyArray<ResolversParentTypes['ProductOptionValue']> };
  ProductOptionValue: Omit<ProductOptionValue, 'firstSelectableVariant'> & { firstSelectableVariant?: Maybe<ResolversParentTypes['ProductVariant']> };
  ProductPriceRange: ProductPriceRange;
  ProductRef: ProductRef;
  ProductVariant: Omit<ProductVariant, 'metafield' | 'metafields'> & { metafield?: Maybe<ResolversParentTypes['Metafield']>, metafields: ReadonlyArray<Maybe<ResolversParentTypes['Metafield']>> };
  ProductVariantConnection: Omit<ProductVariantConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversParentTypes['ProductVariantEdge']>, nodes: ReadonlyArray<ResolversParentTypes['ProductVariant']> };
  ProductVariantEdge: Omit<ProductVariantEdge, 'node'> & { node: ResolversParentTypes['ProductVariant'] };
  Query: {};
  Review: Omit<Review, 'variant'> & { variant?: Maybe<ResolversParentTypes['ProductVariant']> };
  ReviewConnection: Omit<ReviewConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversParentTypes['ReviewEdge']>, nodes: ReadonlyArray<ResolversParentTypes['Review']> };
  ReviewEdge: Omit<ReviewEdge, 'node'> & { node: ResolversParentTypes['Review'] };
  SEO: Seo;
  SearchQuerySuggestion: SearchQuerySuggestion;
  SearchResultItem: ResolversUnionTypes<ResolversParentTypes>['SearchResultItem'];
  SearchResultItemConnection: Omit<SearchResultItemConnection, 'edges' | 'nodes'> & { edges: ReadonlyArray<ResolversParentTypes['SearchResultItemEdge']>, nodes: ReadonlyArray<ResolversParentTypes['SearchResultItem']> };
  SearchResultItemEdge: Omit<SearchResultItemEdge, 'node'> & { node: ResolversParentTypes['SearchResultItem'] };
  SelectedOption: SelectedOption;
  SelectedOptionInput: SelectedOptionInput;
  ShippingMethod: ShippingMethod;
  Shop: Omit<Shop, 'metafield' | 'metafields'> & { metafield?: Maybe<ResolversParentTypes['Metafield']>, metafields: ReadonlyArray<Maybe<ResolversParentTypes['Metafield']>> };
  ShopDomain: ShopDomain;
  ShopPolicy: ShopPolicy;
  String: Scalars['String']['output'];
  Swatch: Swatch;
  SwatchMedia: SwatchMedia;
  UserError: UserError;
  VisitorConsent: VisitorConsent;
};

export type DeferDirectiveArgs = {
  if?: Maybe<Scalars['Boolean']['input']>;
  label: Maybe<Scalars['String']['input']>;
};

export type DeferDirectiveResolver<Result, Parent, ContextType = ResolverContext, Args = DeferDirectiveArgs> = DirectiveResolverFn<Result, Parent, ContextType, Args>;

export type InContextDirectiveArgs = {
  country: Maybe<CountryCode>;
  language: Maybe<LanguageCode>;
  visitorConsent: Maybe<VisitorConsent>;
};

export type InContextDirectiveResolver<Result, Parent, ContextType = ResolverContext, Args = InContextDirectiveArgs> = DirectiveResolverFn<Result, Parent, ContextType, Args>;

export type SandboxDirectiveArgs = {
  reason: Maybe<Scalars['String']['input']>;
};

export type SandboxDirectiveResolver<Result, Parent, ContextType = ResolverContext, Args = SandboxDirectiveArgs> = DirectiveResolverFn<Result, Parent, ContextType, Args>;

export type AppliedGiftCardResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['AppliedGiftCard'] = ResolversParentTypes['AppliedGiftCard']> = {
  amountUsed?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  lastCharacters?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ArticleResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Article'] = ResolversParentTypes['Article']> = {
  author?: Resolver<Maybe<ResolversTypes['ArticleAuthor']>, ParentType, ContextType>;
  blog?: Resolver<ResolversTypes['BlogRef'], ParentType, ContextType>;
  contentHtml?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  image?: Resolver<Maybe<ResolversTypes['Image']>, ParentType, ContextType>;
  publishedAt?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  seo?: Resolver<Maybe<ResolversTypes['SEO']>, ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  trackingParameters?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ArticleAuthorResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ArticleAuthor'] = ResolversParentTypes['ArticleAuthor']> = {
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ArticleConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ArticleConnection'] = ResolversParentTypes['ArticleConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['ArticleEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['Article']>, ParentType, ContextType>;
  pageInfo?: Resolver<ResolversTypes['PageInfo'], ParentType, ContextType>;
  totalCount?: Resolver<Maybe<ResolversTypes['Int']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ArticleEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ArticleEdge'] = ResolversParentTypes['ArticleEdge']> = {
  cursor?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  node?: Resolver<ResolversTypes['Article'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type AttributeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Attribute'] = ResolversParentTypes['Attribute']> = {
  key?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  value?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type BaseCartLineResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['BaseCartLine'] = ResolversParentTypes['BaseCartLine']> = {
  __resolveType: TypeResolveFn<'CartLine' | 'ComponentizableCartLine', ParentType, ContextType>;
};

export type BlogResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Blog'] = ResolversParentTypes['Blog']> = {
  articleByHandle?: Resolver<Maybe<ResolversTypes['Article']>, ParentType, ContextType, RequireFields<BlogArticleByHandleArgs, 'handle'>>;
  articles?: Resolver<ResolversTypes['ArticleConnection'], ParentType, ContextType, Partial<BlogArticlesArgs>>;
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  seo?: Resolver<ResolversTypes['SEO'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type BlogConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['BlogConnection'] = ResolversParentTypes['BlogConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['BlogEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['Blog']>, ParentType, ContextType>;
  pageInfo?: Resolver<ResolversTypes['PageInfo'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type BlogEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['BlogEdge'] = ResolversParentTypes['BlogEdge']> = {
  cursor?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  node?: Resolver<ResolversTypes['Blog'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type BlogRefResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['BlogRef'] = ResolversParentTypes['BlogRef']> = {
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type BrandResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Brand'] = ResolversParentTypes['Brand']> = {
  colors?: Resolver<Maybe<ResolversTypes['BrandColors']>, ParentType, ContextType>;
  coverImage?: Resolver<Maybe<ResolversTypes['MediaImage']>, ParentType, ContextType>;
  logo?: Resolver<Maybe<ResolversTypes['MediaImage']>, ParentType, ContextType>;
  shortDescription?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type BrandColorGroupResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['BrandColorGroup'] = ResolversParentTypes['BrandColorGroup']> = {
  background?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  foreground?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type BrandColorsResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['BrandColors'] = ResolversParentTypes['BrandColors']> = {
  primary?: Resolver<Maybe<ReadonlyArray<ResolversTypes['BrandColorGroup']>>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Cart'] = ResolversParentTypes['Cart']> = {
  appliedGiftCards?: Resolver<ReadonlyArray<ResolversTypes['AppliedGiftCard']>, ParentType, ContextType>;
  attributes?: Resolver<ReadonlyArray<ResolversTypes['Attribute']>, ParentType, ContextType>;
  buyerIdentity?: Resolver<ResolversTypes['CartBuyerIdentity'], ParentType, ContextType>;
  checkoutUrl?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  cost?: Resolver<ResolversTypes['CartCost'], ParentType, ContextType>;
  discountAllocations?: Resolver<ReadonlyArray<ResolversTypes['CartDiscountAllocation']>, ParentType, ContextType>;
  discountCodes?: Resolver<ReadonlyArray<ResolversTypes['CartDiscountCode']>, ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  lines?: Resolver<ResolversTypes['CartLineConnection'], ParentType, ContextType, Partial<CartLinesArgs>>;
  note?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  totalQuantity?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  updatedAt?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartAttributesUpdatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartAttributesUpdatePayload'] = ResolversParentTypes['CartAttributesUpdatePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartBuyerIdentityResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartBuyerIdentity'] = ResolversParentTypes['CartBuyerIdentity']> = {
  countryCode?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  customer?: Resolver<Maybe<ResolversTypes['Customer']>, ParentType, ContextType>;
  email?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  phone?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartBuyerIdentityUpdatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartBuyerIdentityUpdatePayload'] = ResolversParentTypes['CartBuyerIdentityUpdatePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartCodeDiscountAllocationResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartCodeDiscountAllocation'] = ResolversParentTypes['CartCodeDiscountAllocation']> = {
  code?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  discountedAmount?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  targetType?: Resolver<ResolversTypes['DiscountApplicationTargetType'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartCostResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartCost'] = ResolversParentTypes['CartCost']> = {
  subtotalAmount?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  totalAmount?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  totalDutyAmount?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  totalTaxAmount?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartCreatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartCreatePayload'] = ResolversParentTypes['CartCreatePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartDiscountAllocationResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartDiscountAllocation'] = ResolversParentTypes['CartDiscountAllocation']> = {
  __resolveType: TypeResolveFn<'CartCodeDiscountAllocation', ParentType, ContextType>;
  discountedAmount?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  targetType?: Resolver<ResolversTypes['DiscountApplicationTargetType'], ParentType, ContextType>;
};

export type CartDiscountCodeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartDiscountCode'] = ResolversParentTypes['CartDiscountCode']> = {
  applicable?: Resolver<ResolversTypes['Boolean'], ParentType, ContextType>;
  code?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartDiscountCodesUpdatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartDiscountCodesUpdatePayload'] = ResolversParentTypes['CartDiscountCodesUpdatePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartGiftCardCodesAddPayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartGiftCardCodesAddPayload'] = ResolversParentTypes['CartGiftCardCodesAddPayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartGiftCardCodesRemovePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartGiftCardCodesRemovePayload'] = ResolversParentTypes['CartGiftCardCodesRemovePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartGiftCardCodesUpdatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartGiftCardCodesUpdatePayload'] = ResolversParentTypes['CartGiftCardCodesUpdatePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLineResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLine'] = ResolversParentTypes['CartLine']> = {
  attributes?: Resolver<ReadonlyArray<ResolversTypes['Attribute']>, ParentType, ContextType>;
  cost?: Resolver<ResolversTypes['CartLineCost'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  merchandise?: Resolver<ResolversTypes['Merchandise'], ParentType, ContextType>;
  parentRelationship?: Resolver<Maybe<ResolversTypes['CartLineParentRelationship']>, ParentType, ContextType>;
  quantity?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLineConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLineConnection'] = ResolversParentTypes['CartLineConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['CartLineEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['BaseCartLine']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLineCostResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLineCost'] = ResolversParentTypes['CartLineCost']> = {
  amountPerQuantity?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  compareAtAmountPerQuantity?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  subtotalAmount?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  totalAmount?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLineEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLineEdge'] = ResolversParentTypes['CartLineEdge']> = {
  node?: Resolver<ResolversTypes['BaseCartLine'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLineParentResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLineParent'] = ResolversParentTypes['CartLineParent']> = {
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLineParentRelationshipResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLineParentRelationship'] = ResolversParentTypes['CartLineParentRelationship']> = {
  parent?: Resolver<Maybe<ResolversTypes['CartLineParent']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLinesAddPayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLinesAddPayload'] = ResolversParentTypes['CartLinesAddPayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLinesRemovePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLinesRemovePayload'] = ResolversParentTypes['CartLinesRemovePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartLinesUpdatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartLinesUpdatePayload'] = ResolversParentTypes['CartLinesUpdatePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartNoteUpdatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartNoteUpdatePayload'] = ResolversParentTypes['CartNoteUpdatePayload']> = {
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CartUserError']>, ParentType, ContextType>;
  warnings?: Resolver<ReadonlyArray<ResolversTypes['CartWarning']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartUserErrorResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartUserError'] = ResolversParentTypes['CartUserError']> = {
  code?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  field?: Resolver<Maybe<ReadonlyArray<ResolversTypes['String']>>, ParentType, ContextType>;
  message?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CartWarningResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CartWarning'] = ResolversParentTypes['CartWarning']> = {
  code?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  message?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  target?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CheckoutCompletePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CheckoutCompletePayload'] = ResolversParentTypes['CheckoutCompletePayload']> = {
  order?: Resolver<Maybe<ResolversTypes['Order']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['CheckoutUserError']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CheckoutUserErrorResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CheckoutUserError'] = ResolversParentTypes['CheckoutUserError']> = {
  code?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  field?: Resolver<Maybe<ReadonlyArray<ResolversTypes['String']>>, ParentType, ContextType>;
  message?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CollectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Collection'] = ResolversParentTypes['Collection']> = {
  description?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  descriptionHtml?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  image?: Resolver<Maybe<ResolversTypes['Image']>, ParentType, ContextType>;
  metafield?: Resolver<Maybe<ResolversTypes['Metafield']>, ParentType, ContextType, RequireFields<CollectionMetafieldArgs, 'key' | 'namespace'>>;
  metafields?: Resolver<ReadonlyArray<Maybe<ResolversTypes['Metafield']>>, ParentType, ContextType, RequireFields<CollectionMetafieldsArgs, 'identifiers'>>;
  products?: Resolver<ResolversTypes['ProductConnection'], ParentType, ContextType, Partial<CollectionProductsArgs>>;
  seo?: Resolver<ResolversTypes['SEO'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  trackingParameters?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  updatedAt?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CollectionConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CollectionConnection'] = ResolversParentTypes['CollectionConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['CollectionEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['Collection']>, ParentType, ContextType>;
  pageInfo?: Resolver<ResolversTypes['PageInfo'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CollectionEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CollectionEdge'] = ResolversParentTypes['CollectionEdge']> = {
  cursor?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  node?: Resolver<ResolversTypes['Collection'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CommerceSettingsResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CommerceSettings'] = ResolversParentTypes['CommerceSettings']> = {
  currencyCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  freeShippingThreshold?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  paymentMethods?: Resolver<ReadonlyArray<ResolversTypes['PaymentMethod']>, ParentType, ContextType>;
  shippingMethods?: Resolver<ReadonlyArray<ResolversTypes['ShippingMethod']>, ParentType, ContextType>;
  taxRate?: Resolver<ResolversTypes['Float'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ComponentizableCartLineResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ComponentizableCartLine'] = ResolversParentTypes['ComponentizableCartLine']> = {
  attributes?: Resolver<ReadonlyArray<ResolversTypes['Attribute']>, ParentType, ContextType>;
  cost?: Resolver<ResolversTypes['CartLineCost'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  lineComponents?: Resolver<ReadonlyArray<ResolversTypes['CartLine']>, ParentType, ContextType>;
  merchandise?: Resolver<ResolversTypes['Merchandise'], ParentType, ContextType>;
  quantity?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CountryResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Country'] = ResolversParentTypes['Country']> = {
  availableLanguages?: Resolver<ReadonlyArray<ResolversTypes['Language']>, ParentType, ContextType>;
  currency?: Resolver<ResolversTypes['CountryCurrency'], ParentType, ContextType>;
  isoCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CountryCurrencyResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CountryCurrency'] = ResolversParentTypes['CountryCurrency']> = {
  isoCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CurrencyResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Currency'] = ResolversParentTypes['Currency']> = {
  isoCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  symbol?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CustomerResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Customer'] = ResolversParentTypes['Customer']> = {
  acceptsMarketing?: Resolver<ResolversTypes['Boolean'], ParentType, ContextType>;
  addresses?: Resolver<ResolversTypes['MailingAddressConnection'], ParentType, ContextType, Partial<CustomerAddressesArgs>>;
  createdAt?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  defaultAddress?: Resolver<Maybe<ResolversTypes['MailingAddress']>, ParentType, ContextType>;
  displayName?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  email?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  firstName?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  lastName?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  numberOfOrders?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  orders?: Resolver<ResolversTypes['OrderConnection'], ParentType, ContextType, Partial<CustomerOrdersArgs>>;
  phone?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  updatedAt?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CustomerAccessTokenResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CustomerAccessToken'] = ResolversParentTypes['CustomerAccessToken']> = {
  accessToken?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  expiresAt?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CustomerAccessTokenCreatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CustomerAccessTokenCreatePayload'] = ResolversParentTypes['CustomerAccessTokenCreatePayload']> = {
  customerAccessToken?: Resolver<Maybe<ResolversTypes['CustomerAccessToken']>, ParentType, ContextType>;
  customerUserErrors?: Resolver<ReadonlyArray<ResolversTypes['CustomerUserError']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CustomerAccessTokenDeletePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CustomerAccessTokenDeletePayload'] = ResolversParentTypes['CustomerAccessTokenDeletePayload']> = {
  deletedAccessToken?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  deletedCustomerAccessTokenId?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  userErrors?: Resolver<ReadonlyArray<ResolversTypes['UserError']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CustomerCreatePayloadResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CustomerCreatePayload'] = ResolversParentTypes['CustomerCreatePayload']> = {
  customer?: Resolver<Maybe<ResolversTypes['Customer']>, ParentType, ContextType>;
  customerUserErrors?: Resolver<ReadonlyArray<ResolversTypes['CustomerUserError']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type CustomerUserErrorResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['CustomerUserError'] = ResolversParentTypes['CustomerUserError']> = {
  code?: Resolver<Maybe<ResolversTypes['CustomerErrorCode']>, ParentType, ContextType>;
  field?: Resolver<Maybe<ReadonlyArray<ResolversTypes['String']>>, ParentType, ContextType>;
  message?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ImageResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Image'] = ResolversParentTypes['Image']> = {
  altText?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  height?: Resolver<Maybe<ResolversTypes['Int']>, ParentType, ContextType>;
  id?: Resolver<Maybe<ResolversTypes['ID']>, ParentType, ContextType>;
  url?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  width?: Resolver<Maybe<ResolversTypes['Int']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ImageConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ImageConnection'] = ResolversParentTypes['ImageConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['ImageEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<Maybe<ResolversTypes['Image']>>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ImageEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ImageEdge'] = ResolversParentTypes['ImageEdge']> = {
  node?: Resolver<Maybe<ResolversTypes['Image']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type LanguageResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Language'] = ResolversParentTypes['Language']> = {
  isoCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type LocalizationResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Localization'] = ResolversParentTypes['Localization']> = {
  availableCountries?: Resolver<ReadonlyArray<ResolversTypes['Country']>, ParentType, ContextType>;
  availableLanguages?: Resolver<ReadonlyArray<ResolversTypes['Language']>, ParentType, ContextType>;
  country?: Resolver<ResolversTypes['LocalizationCountry'], ParentType, ContextType>;
  language?: Resolver<ResolversTypes['Language'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type LocalizationCountryResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['LocalizationCountry'] = ResolversParentTypes['LocalizationCountry']> = {
  currency?: Resolver<ResolversTypes['Currency'], ParentType, ContextType>;
  isoCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MailingAddressResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['MailingAddress'] = ResolversParentTypes['MailingAddress']> = {
  address1?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  address2?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  city?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  company?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  country?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  countryCodeV2?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  firstName?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  formatted?: Resolver<ReadonlyArray<ResolversTypes['String']>, ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  lastName?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  name?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  phone?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  province?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  provinceCode?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  zip?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MailingAddressConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['MailingAddressConnection'] = ResolversParentTypes['MailingAddressConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['MailingAddressEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['MailingAddress']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MailingAddressEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['MailingAddressEdge'] = ResolversParentTypes['MailingAddressEdge']> = {
  node?: Resolver<ResolversTypes['MailingAddress'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MediaImageResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['MediaImage'] = ResolversParentTypes['MediaImage']> = {
  image?: Resolver<Maybe<ResolversTypes['Image']>, ParentType, ContextType>;
  previewImage?: Resolver<Maybe<ResolversTypes['Image']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MenuResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Menu'] = ResolversParentTypes['Menu']> = {
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  items?: Resolver<ReadonlyArray<ResolversTypes['MenuItem']>, ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MenuItemResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['MenuItem'] = ResolversParentTypes['MenuItem']> = {
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  items?: Resolver<ReadonlyArray<ResolversTypes['MenuItem']>, ParentType, ContextType>;
  resourceId?: Resolver<Maybe<ResolversTypes['ID']>, ParentType, ContextType>;
  tags?: Resolver<ReadonlyArray<ResolversTypes['String']>, ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  type?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  url?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MerchandiseResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Merchandise'] = ResolversParentTypes['Merchandise']> = {
  __resolveType: TypeResolveFn<'ProductVariant', ParentType, ContextType>;
};

export type MetafieldResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Metafield'] = ResolversParentTypes['Metafield']> = {
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  key?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  namespace?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  parentResource?: Resolver<Maybe<ResolversTypes['MetafieldParentResource']>, ParentType, ContextType>;
  reference?: Resolver<Maybe<ResolversTypes['MetafieldReference']>, ParentType, ContextType>;
  type?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  value?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MetafieldParentResourceResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['MetafieldParentResource'] = ResolversParentTypes['MetafieldParentResource']> = {
  __resolveType: TypeResolveFn<'Collection' | 'Product' | 'ProductVariant', ParentType, ContextType>;
};

export type MetafieldReferenceResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['MetafieldReference'] = ResolversParentTypes['MetafieldReference']> = {
  __resolveType: TypeResolveFn<'Collection' | 'Page' | 'Product', ParentType, ContextType>;
};

export type MoneyV2Resolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['MoneyV2'] = ResolversParentTypes['MoneyV2']> = {
  amount?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  currencyCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type MutationResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Mutation'] = ResolversParentTypes['Mutation']> = {
  cartAttributesUpdate?: Resolver<ResolversTypes['CartAttributesUpdatePayload'], ParentType, ContextType, RequireFields<MutationCartAttributesUpdateArgs, 'attributes' | 'cartId'>>;
  cartBuyerIdentityUpdate?: Resolver<ResolversTypes['CartBuyerIdentityUpdatePayload'], ParentType, ContextType, RequireFields<MutationCartBuyerIdentityUpdateArgs, 'buyerIdentity' | 'cartId'>>;
  cartCreate?: Resolver<ResolversTypes['CartCreatePayload'], ParentType, ContextType, RequireFields<MutationCartCreateArgs, 'input'>>;
  cartDiscountCodesUpdate?: Resolver<ResolversTypes['CartDiscountCodesUpdatePayload'], ParentType, ContextType, RequireFields<MutationCartDiscountCodesUpdateArgs, 'cartId'>>;
  cartGiftCardCodesAdd?: Resolver<ResolversTypes['CartGiftCardCodesAddPayload'], ParentType, ContextType, RequireFields<MutationCartGiftCardCodesAddArgs, 'cartId' | 'giftCardCodes'>>;
  cartGiftCardCodesRemove?: Resolver<ResolversTypes['CartGiftCardCodesRemovePayload'], ParentType, ContextType, RequireFields<MutationCartGiftCardCodesRemoveArgs, 'appliedGiftCardIds' | 'cartId'>>;
  cartGiftCardCodesUpdate?: Resolver<ResolversTypes['CartGiftCardCodesUpdatePayload'], ParentType, ContextType, RequireFields<MutationCartGiftCardCodesUpdateArgs, 'cartId' | 'giftCardCodes'>>;
  cartLinesAdd?: Resolver<ResolversTypes['CartLinesAddPayload'], ParentType, ContextType, RequireFields<MutationCartLinesAddArgs, 'cartId' | 'lines'>>;
  cartLinesRemove?: Resolver<ResolversTypes['CartLinesRemovePayload'], ParentType, ContextType, RequireFields<MutationCartLinesRemoveArgs, 'cartId' | 'lineIds'>>;
  cartLinesUpdate?: Resolver<ResolversTypes['CartLinesUpdatePayload'], ParentType, ContextType, RequireFields<MutationCartLinesUpdateArgs, 'cartId' | 'lines'>>;
  cartNoteUpdate?: Resolver<ResolversTypes['CartNoteUpdatePayload'], ParentType, ContextType, RequireFields<MutationCartNoteUpdateArgs, 'cartId' | 'note'>>;
  checkoutComplete?: Resolver<ResolversTypes['CheckoutCompletePayload'], ParentType, ContextType, RequireFields<MutationCheckoutCompleteArgs, 'cartId' | 'input'>>;
  customerAccessTokenCreate?: Resolver<ResolversTypes['CustomerAccessTokenCreatePayload'], ParentType, ContextType, RequireFields<MutationCustomerAccessTokenCreateArgs, 'input'>>;
  customerAccessTokenDelete?: Resolver<ResolversTypes['CustomerAccessTokenDeletePayload'], ParentType, ContextType, RequireFields<MutationCustomerAccessTokenDeleteArgs, 'customerAccessToken'>>;
  customerCreate?: Resolver<ResolversTypes['CustomerCreatePayload'], ParentType, ContextType, RequireFields<MutationCustomerCreateArgs, 'input'>>;
};

export type OrderResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Order'] = ResolversParentTypes['Order']> = {
  currencyCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  discountCode?: Resolver<Maybe<ResolversTypes['OrderDiscountCode']>, ParentType, ContextType>;
  email?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  financialStatus?: Resolver<Maybe<ResolversTypes['OrderFinancialStatus']>, ParentType, ContextType>;
  fulfillmentStatus?: Resolver<ResolversTypes['OrderFulfillmentStatus'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  lineItems?: Resolver<ResolversTypes['OrderLineItemConnection'], ParentType, ContextType, Partial<OrderLineItemsArgs>>;
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  orderNumber?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  paymentMethod?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  processedAt?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  shippingAddress?: Resolver<Maybe<ResolversTypes['MailingAddress']>, ParentType, ContextType>;
  shippingMethod?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  subtotalPrice?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  totalPrice?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  totalShippingPrice?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  totalTax?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type OrderConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['OrderConnection'] = ResolversParentTypes['OrderConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['OrderEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['Order']>, ParentType, ContextType>;
  totalCount?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type OrderDiscountCodeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['OrderDiscountCode'] = ResolversParentTypes['OrderDiscountCode']> = {
  amount?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  code?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  targetType?: Resolver<ResolversTypes['DiscountApplicationTargetType'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type OrderEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['OrderEdge'] = ResolversParentTypes['OrderEdge']> = {
  node?: Resolver<ResolversTypes['Order'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type OrderLineItemResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['OrderLineItem'] = ResolversParentTypes['OrderLineItem']> = {
  originalTotalPrice?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  quantity?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  variant?: Resolver<Maybe<ResolversTypes['ProductVariant']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type OrderLineItemConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['OrderLineItemConnection'] = ResolversParentTypes['OrderLineItemConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['OrderLineItemEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['OrderLineItem']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type OrderLineItemEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['OrderLineItemEdge'] = ResolversParentTypes['OrderLineItemEdge']> = {
  node?: Resolver<ResolversTypes['OrderLineItem'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type PageResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Page'] = ResolversParentTypes['Page']> = {
  body?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  seo?: Resolver<ResolversTypes['SEO'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  trackingParameters?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type PageInfoResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['PageInfo'] = ResolversParentTypes['PageInfo']> = {
  endCursor?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  hasNextPage?: Resolver<ResolversTypes['Boolean'], ParentType, ContextType>;
  hasPreviousPage?: Resolver<ResolversTypes['Boolean'], ParentType, ContextType>;
  startCursor?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type PaymentMethodResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['PaymentMethod'] = ResolversParentTypes['PaymentMethod']> = {
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type PaymentSettingsResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['PaymentSettings'] = ResolversParentTypes['PaymentSettings']> = {
  acceptedCardBrands?: Resolver<ReadonlyArray<ResolversTypes['String']>, ParentType, ContextType>;
  countryCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  currencyCode?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type PredictiveSearchResultResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['PredictiveSearchResult'] = ResolversParentTypes['PredictiveSearchResult']> = {
  articles?: Resolver<ReadonlyArray<ResolversTypes['Article']>, ParentType, ContextType>;
  collections?: Resolver<ReadonlyArray<ResolversTypes['Collection']>, ParentType, ContextType>;
  pages?: Resolver<ReadonlyArray<ResolversTypes['Page']>, ParentType, ContextType>;
  products?: Resolver<ReadonlyArray<ResolversTypes['Product']>, ParentType, ContextType>;
  queries?: Resolver<ReadonlyArray<ResolversTypes['SearchQuerySuggestion']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Product'] = ResolversParentTypes['Product']> = {
  adjacentVariants?: Resolver<ReadonlyArray<ResolversTypes['ProductVariant']>, ParentType, ContextType, Partial<ProductAdjacentVariantsArgs>>;
  availableForSale?: Resolver<ResolversTypes['Boolean'], ParentType, ContextType>;
  compareAtPriceRange?: Resolver<ResolversTypes['ProductPriceRange'], ParentType, ContextType>;
  createdAt?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  description?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  descriptionHtml?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  encodedVariantAvailability?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  encodedVariantExistence?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  featuredImage?: Resolver<Maybe<ResolversTypes['Image']>, ParentType, ContextType>;
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  images?: Resolver<ResolversTypes['ImageConnection'], ParentType, ContextType, Partial<ProductImagesArgs>>;
  metafield?: Resolver<Maybe<ResolversTypes['Metafield']>, ParentType, ContextType, RequireFields<ProductMetafieldArgs, 'key' | 'namespace'>>;
  metafields?: Resolver<ReadonlyArray<Maybe<ResolversTypes['Metafield']>>, ParentType, ContextType, RequireFields<ProductMetafieldsArgs, 'identifiers'>>;
  options?: Resolver<ReadonlyArray<ResolversTypes['ProductOption']>, ParentType, ContextType>;
  priceRange?: Resolver<ResolversTypes['ProductPriceRange'], ParentType, ContextType>;
  productType?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  publishedAt?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  reviews?: Resolver<ResolversTypes['ReviewConnection'], ParentType, ContextType, RequireFields<ProductReviewsArgs, 'sortKey'>>;
  selectedOrFirstAvailableVariant?: Resolver<Maybe<ResolversTypes['ProductVariant']>, ParentType, ContextType, Partial<ProductSelectedOrFirstAvailableVariantArgs>>;
  seo?: Resolver<ResolversTypes['SEO'], ParentType, ContextType>;
  tags?: Resolver<ReadonlyArray<ResolversTypes['String']>, ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  trackingParameters?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  updatedAt?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  variants?: Resolver<ResolversTypes['ProductVariantConnection'], ParentType, ContextType, Partial<ProductVariantsArgs>>;
  vendor?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductConnection'] = ResolversParentTypes['ProductConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['ProductEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['Product']>, ParentType, ContextType>;
  pageInfo?: Resolver<ResolversTypes['PageInfo'], ParentType, ContextType>;
  totalCount?: Resolver<Maybe<ResolversTypes['Int']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductEdge'] = ResolversParentTypes['ProductEdge']> = {
  cursor?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  node?: Resolver<ResolversTypes['Product'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductOptionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductOption'] = ResolversParentTypes['ProductOption']> = {
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  optionValues?: Resolver<ReadonlyArray<ResolversTypes['ProductOptionValue']>, ParentType, ContextType>;
  values?: Resolver<ReadonlyArray<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductOptionValueResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductOptionValue'] = ResolversParentTypes['ProductOptionValue']> = {
  firstSelectableVariant?: Resolver<Maybe<ResolversTypes['ProductVariant']>, ParentType, ContextType>;
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  swatch?: Resolver<Maybe<ResolversTypes['Swatch']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductPriceRangeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductPriceRange'] = ResolversParentTypes['ProductPriceRange']> = {
  maxVariantPrice?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  minVariantPrice?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductRefResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductRef'] = ResolversParentTypes['ProductRef']> = {
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  vendor?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductVariantResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductVariant'] = ResolversParentTypes['ProductVariant']> = {
  availableForSale?: Resolver<ResolversTypes['Boolean'], ParentType, ContextType>;
  compareAtPrice?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  image?: Resolver<Maybe<ResolversTypes['Image']>, ParentType, ContextType>;
  metafield?: Resolver<Maybe<ResolversTypes['Metafield']>, ParentType, ContextType, RequireFields<ProductVariantMetafieldArgs, 'key' | 'namespace'>>;
  metafields?: Resolver<ReadonlyArray<Maybe<ResolversTypes['Metafield']>>, ParentType, ContextType, RequireFields<ProductVariantMetafieldsArgs, 'identifiers'>>;
  price?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  product?: Resolver<ResolversTypes['ProductRef'], ParentType, ContextType>;
  quantityAvailable?: Resolver<Maybe<ResolversTypes['Int']>, ParentType, ContextType>;
  requiresShipping?: Resolver<ResolversTypes['Boolean'], ParentType, ContextType>;
  selectedOptions?: Resolver<ReadonlyArray<ResolversTypes['SelectedOption']>, ParentType, ContextType>;
  sku?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  unitPrice?: Resolver<Maybe<ResolversTypes['MoneyV2']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductVariantConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductVariantConnection'] = ResolversParentTypes['ProductVariantConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['ProductVariantEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['ProductVariant']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ProductVariantEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ProductVariantEdge'] = ResolversParentTypes['ProductVariantEdge']> = {
  node?: Resolver<ResolversTypes['ProductVariant'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type QueryResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Query'] = ResolversParentTypes['Query']> = {
  blog?: Resolver<Maybe<ResolversTypes['Blog']>, ParentType, ContextType, RequireFields<QueryBlogArgs, 'handle'>>;
  blogs?: Resolver<ResolversTypes['BlogConnection'], ParentType, ContextType, Partial<QueryBlogsArgs>>;
  cart?: Resolver<Maybe<ResolversTypes['Cart']>, ParentType, ContextType, RequireFields<QueryCartArgs, 'id'>>;
  collection?: Resolver<Maybe<ResolversTypes['Collection']>, ParentType, ContextType, RequireFields<QueryCollectionArgs, 'handle'>>;
  collections?: Resolver<ResolversTypes['CollectionConnection'], ParentType, ContextType, Partial<QueryCollectionsArgs>>;
  commerceSettings?: Resolver<ResolversTypes['CommerceSettings'], ParentType, ContextType>;
  customer?: Resolver<Maybe<ResolversTypes['Customer']>, ParentType, ContextType, RequireFields<QueryCustomerArgs, 'customerAccessToken'>>;
  localization?: Resolver<ResolversTypes['Localization'], ParentType, ContextType>;
  menu?: Resolver<Maybe<ResolversTypes['Menu']>, ParentType, ContextType, RequireFields<QueryMenuArgs, 'handle'>>;
  order?: Resolver<Maybe<ResolversTypes['Order']>, ParentType, ContextType, RequireFields<QueryOrderArgs, 'id'>>;
  page?: Resolver<Maybe<ResolversTypes['Page']>, ParentType, ContextType, RequireFields<QueryPageArgs, 'handle'>>;
  predictiveSearch?: Resolver<Maybe<ResolversTypes['PredictiveSearchResult']>, ParentType, ContextType, RequireFields<QueryPredictiveSearchArgs, 'query'>>;
  product?: Resolver<Maybe<ResolversTypes['Product']>, ParentType, ContextType, RequireFields<QueryProductArgs, 'handle'>>;
  productRecommendations?: Resolver<Maybe<ReadonlyArray<ResolversTypes['Product']>>, ParentType, ContextType, RequireFields<QueryProductRecommendationsArgs, 'productId'>>;
  products?: Resolver<ResolversTypes['ProductConnection'], ParentType, ContextType, Partial<QueryProductsArgs>>;
  search?: Resolver<ResolversTypes['SearchResultItemConnection'], ParentType, ContextType, RequireFields<QuerySearchArgs, 'query'>>;
  shop?: Resolver<ResolversTypes['Shop'], ParentType, ContextType>;
};

export type ReviewResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Review'] = ResolversParentTypes['Review']> = {
  body?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  createdAt?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  helpfulCount?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  rating?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  reviewerName?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  variant?: Resolver<Maybe<ResolversTypes['ProductVariant']>, ParentType, ContextType>;
  verifiedBuyer?: Resolver<ResolversTypes['Boolean'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ReviewConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ReviewConnection'] = ResolversParentTypes['ReviewConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['ReviewEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['Review']>, ParentType, ContextType>;
  pageInfo?: Resolver<ResolversTypes['PageInfo'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ReviewEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ReviewEdge'] = ResolversParentTypes['ReviewEdge']> = {
  cursor?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  node?: Resolver<ResolversTypes['Review'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type SeoResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['SEO'] = ResolversParentTypes['SEO']> = {
  description?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  title?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type SearchQuerySuggestionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['SearchQuerySuggestion'] = ResolversParentTypes['SearchQuerySuggestion']> = {
  styledText?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  text?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  trackingParameters?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type SearchResultItemResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['SearchResultItem'] = ResolversParentTypes['SearchResultItem']> = {
  __resolveType: TypeResolveFn<'Article' | 'Page' | 'Product', ParentType, ContextType>;
};

export type SearchResultItemConnectionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['SearchResultItemConnection'] = ResolversParentTypes['SearchResultItemConnection']> = {
  edges?: Resolver<ReadonlyArray<ResolversTypes['SearchResultItemEdge']>, ParentType, ContextType>;
  nodes?: Resolver<ReadonlyArray<ResolversTypes['SearchResultItem']>, ParentType, ContextType>;
  pageInfo?: Resolver<ResolversTypes['PageInfo'], ParentType, ContextType>;
  totalCount?: Resolver<ResolversTypes['Int'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type SearchResultItemEdgeResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['SearchResultItemEdge'] = ResolversParentTypes['SearchResultItemEdge']> = {
  cursor?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  node?: Resolver<ResolversTypes['SearchResultItem'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type SelectedOptionResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['SelectedOption'] = ResolversParentTypes['SelectedOption']> = {
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  value?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ShippingMethodResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ShippingMethod'] = ResolversParentTypes['ShippingMethod']> = {
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  price?: Resolver<ResolversTypes['MoneyV2'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ShopResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Shop'] = ResolversParentTypes['Shop']> = {
  brand?: Resolver<Maybe<ResolversTypes['Brand']>, ParentType, ContextType>;
  description?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  metafield?: Resolver<Maybe<ResolversTypes['Metafield']>, ParentType, ContextType, RequireFields<ShopMetafieldArgs, 'key' | 'namespace'>>;
  metafields?: Resolver<ReadonlyArray<Maybe<ResolversTypes['Metafield']>>, ParentType, ContextType, RequireFields<ShopMetafieldsArgs, 'identifiers'>>;
  name?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  paymentSettings?: Resolver<ResolversTypes['PaymentSettings'], ParentType, ContextType>;
  primaryDomain?: Resolver<ResolversTypes['ShopDomain'], ParentType, ContextType>;
  privacyPolicy?: Resolver<Maybe<ResolversTypes['ShopPolicy']>, ParentType, ContextType>;
  refundPolicy?: Resolver<Maybe<ResolversTypes['ShopPolicy']>, ParentType, ContextType>;
  shippingPolicy?: Resolver<Maybe<ResolversTypes['ShopPolicy']>, ParentType, ContextType>;
  subscriptionPolicy?: Resolver<Maybe<ResolversTypes['ShopPolicy']>, ParentType, ContextType>;
  termsOfService?: Resolver<Maybe<ResolversTypes['ShopPolicy']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ShopDomainResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ShopDomain'] = ResolversParentTypes['ShopDomain']> = {
  host?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  url?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type ShopPolicyResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['ShopPolicy'] = ResolversParentTypes['ShopPolicy']> = {
  body?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  handle?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  id?: Resolver<ResolversTypes['ID'], ParentType, ContextType>;
  title?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  url?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type SwatchResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['Swatch'] = ResolversParentTypes['Swatch']> = {
  color?: Resolver<Maybe<ResolversTypes['String']>, ParentType, ContextType>;
  image?: Resolver<Maybe<ResolversTypes['SwatchMedia']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type SwatchMediaResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['SwatchMedia'] = ResolversParentTypes['SwatchMedia']> = {
  previewImage?: Resolver<Maybe<ResolversTypes['Image']>, ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type UserErrorResolvers<ContextType = ResolverContext, ParentType extends ResolversParentTypes['UserError'] = ResolversParentTypes['UserError']> = {
  field?: Resolver<Maybe<ReadonlyArray<ResolversTypes['String']>>, ParentType, ContextType>;
  message?: Resolver<ResolversTypes['String'], ParentType, ContextType>;
  __isTypeOf?: IsTypeOfResolverFn<ParentType, ContextType>;
};

export type Resolvers<ContextType = ResolverContext> = {
  AppliedGiftCard?: AppliedGiftCardResolvers<ContextType>;
  Article?: ArticleResolvers<ContextType>;
  ArticleAuthor?: ArticleAuthorResolvers<ContextType>;
  ArticleConnection?: ArticleConnectionResolvers<ContextType>;
  ArticleEdge?: ArticleEdgeResolvers<ContextType>;
  Attribute?: AttributeResolvers<ContextType>;
  BaseCartLine?: BaseCartLineResolvers<ContextType>;
  Blog?: BlogResolvers<ContextType>;
  BlogConnection?: BlogConnectionResolvers<ContextType>;
  BlogEdge?: BlogEdgeResolvers<ContextType>;
  BlogRef?: BlogRefResolvers<ContextType>;
  Brand?: BrandResolvers<ContextType>;
  BrandColorGroup?: BrandColorGroupResolvers<ContextType>;
  BrandColors?: BrandColorsResolvers<ContextType>;
  Cart?: CartResolvers<ContextType>;
  CartAttributesUpdatePayload?: CartAttributesUpdatePayloadResolvers<ContextType>;
  CartBuyerIdentity?: CartBuyerIdentityResolvers<ContextType>;
  CartBuyerIdentityUpdatePayload?: CartBuyerIdentityUpdatePayloadResolvers<ContextType>;
  CartCodeDiscountAllocation?: CartCodeDiscountAllocationResolvers<ContextType>;
  CartCost?: CartCostResolvers<ContextType>;
  CartCreatePayload?: CartCreatePayloadResolvers<ContextType>;
  CartDiscountAllocation?: CartDiscountAllocationResolvers<ContextType>;
  CartDiscountCode?: CartDiscountCodeResolvers<ContextType>;
  CartDiscountCodesUpdatePayload?: CartDiscountCodesUpdatePayloadResolvers<ContextType>;
  CartGiftCardCodesAddPayload?: CartGiftCardCodesAddPayloadResolvers<ContextType>;
  CartGiftCardCodesRemovePayload?: CartGiftCardCodesRemovePayloadResolvers<ContextType>;
  CartGiftCardCodesUpdatePayload?: CartGiftCardCodesUpdatePayloadResolvers<ContextType>;
  CartLine?: CartLineResolvers<ContextType>;
  CartLineConnection?: CartLineConnectionResolvers<ContextType>;
  CartLineCost?: CartLineCostResolvers<ContextType>;
  CartLineEdge?: CartLineEdgeResolvers<ContextType>;
  CartLineParent?: CartLineParentResolvers<ContextType>;
  CartLineParentRelationship?: CartLineParentRelationshipResolvers<ContextType>;
  CartLinesAddPayload?: CartLinesAddPayloadResolvers<ContextType>;
  CartLinesRemovePayload?: CartLinesRemovePayloadResolvers<ContextType>;
  CartLinesUpdatePayload?: CartLinesUpdatePayloadResolvers<ContextType>;
  CartNoteUpdatePayload?: CartNoteUpdatePayloadResolvers<ContextType>;
  CartUserError?: CartUserErrorResolvers<ContextType>;
  CartWarning?: CartWarningResolvers<ContextType>;
  CheckoutCompletePayload?: CheckoutCompletePayloadResolvers<ContextType>;
  CheckoutUserError?: CheckoutUserErrorResolvers<ContextType>;
  Collection?: CollectionResolvers<ContextType>;
  CollectionConnection?: CollectionConnectionResolvers<ContextType>;
  CollectionEdge?: CollectionEdgeResolvers<ContextType>;
  CommerceSettings?: CommerceSettingsResolvers<ContextType>;
  ComponentizableCartLine?: ComponentizableCartLineResolvers<ContextType>;
  Country?: CountryResolvers<ContextType>;
  CountryCurrency?: CountryCurrencyResolvers<ContextType>;
  Currency?: CurrencyResolvers<ContextType>;
  Customer?: CustomerResolvers<ContextType>;
  CustomerAccessToken?: CustomerAccessTokenResolvers<ContextType>;
  CustomerAccessTokenCreatePayload?: CustomerAccessTokenCreatePayloadResolvers<ContextType>;
  CustomerAccessTokenDeletePayload?: CustomerAccessTokenDeletePayloadResolvers<ContextType>;
  CustomerCreatePayload?: CustomerCreatePayloadResolvers<ContextType>;
  CustomerUserError?: CustomerUserErrorResolvers<ContextType>;
  Image?: ImageResolvers<ContextType>;
  ImageConnection?: ImageConnectionResolvers<ContextType>;
  ImageEdge?: ImageEdgeResolvers<ContextType>;
  Language?: LanguageResolvers<ContextType>;
  Localization?: LocalizationResolvers<ContextType>;
  LocalizationCountry?: LocalizationCountryResolvers<ContextType>;
  MailingAddress?: MailingAddressResolvers<ContextType>;
  MailingAddressConnection?: MailingAddressConnectionResolvers<ContextType>;
  MailingAddressEdge?: MailingAddressEdgeResolvers<ContextType>;
  MediaImage?: MediaImageResolvers<ContextType>;
  Menu?: MenuResolvers<ContextType>;
  MenuItem?: MenuItemResolvers<ContextType>;
  Merchandise?: MerchandiseResolvers<ContextType>;
  Metafield?: MetafieldResolvers<ContextType>;
  MetafieldParentResource?: MetafieldParentResourceResolvers<ContextType>;
  MetafieldReference?: MetafieldReferenceResolvers<ContextType>;
  MoneyV2?: MoneyV2Resolvers<ContextType>;
  Mutation?: MutationResolvers<ContextType>;
  Order?: OrderResolvers<ContextType>;
  OrderConnection?: OrderConnectionResolvers<ContextType>;
  OrderDiscountCode?: OrderDiscountCodeResolvers<ContextType>;
  OrderEdge?: OrderEdgeResolvers<ContextType>;
  OrderLineItem?: OrderLineItemResolvers<ContextType>;
  OrderLineItemConnection?: OrderLineItemConnectionResolvers<ContextType>;
  OrderLineItemEdge?: OrderLineItemEdgeResolvers<ContextType>;
  Page?: PageResolvers<ContextType>;
  PageInfo?: PageInfoResolvers<ContextType>;
  PaymentMethod?: PaymentMethodResolvers<ContextType>;
  PaymentSettings?: PaymentSettingsResolvers<ContextType>;
  PredictiveSearchResult?: PredictiveSearchResultResolvers<ContextType>;
  Product?: ProductResolvers<ContextType>;
  ProductConnection?: ProductConnectionResolvers<ContextType>;
  ProductEdge?: ProductEdgeResolvers<ContextType>;
  ProductOption?: ProductOptionResolvers<ContextType>;
  ProductOptionValue?: ProductOptionValueResolvers<ContextType>;
  ProductPriceRange?: ProductPriceRangeResolvers<ContextType>;
  ProductRef?: ProductRefResolvers<ContextType>;
  ProductVariant?: ProductVariantResolvers<ContextType>;
  ProductVariantConnection?: ProductVariantConnectionResolvers<ContextType>;
  ProductVariantEdge?: ProductVariantEdgeResolvers<ContextType>;
  Query?: QueryResolvers<ContextType>;
  Review?: ReviewResolvers<ContextType>;
  ReviewConnection?: ReviewConnectionResolvers<ContextType>;
  ReviewEdge?: ReviewEdgeResolvers<ContextType>;
  SEO?: SeoResolvers<ContextType>;
  SearchQuerySuggestion?: SearchQuerySuggestionResolvers<ContextType>;
  SearchResultItem?: SearchResultItemResolvers<ContextType>;
  SearchResultItemConnection?: SearchResultItemConnectionResolvers<ContextType>;
  SearchResultItemEdge?: SearchResultItemEdgeResolvers<ContextType>;
  SelectedOption?: SelectedOptionResolvers<ContextType>;
  ShippingMethod?: ShippingMethodResolvers<ContextType>;
  Shop?: ShopResolvers<ContextType>;
  ShopDomain?: ShopDomainResolvers<ContextType>;
  ShopPolicy?: ShopPolicyResolvers<ContextType>;
  Swatch?: SwatchResolvers<ContextType>;
  SwatchMedia?: SwatchMediaResolvers<ContextType>;
  UserError?: UserErrorResolvers<ContextType>;
};

export type DirectiveResolvers<ContextType = ResolverContext> = {
  defer?: DeferDirectiveResolver<any, any, ContextType>;
  inContext?: InContextDirectiveResolver<any, any, ContextType>;
  sandbox?: SandboxDirectiveResolver<any, any, ContextType>;
};
