export const MONEY_FRAGMENT = `#graphql
  fragment MoneyFields on MoneyV2 {
    amount
    currencyCode
  }
`;

export const IMAGE_FRAGMENT = `#graphql
  fragment ImageFields on Image {
    id
    url
    altText
    width
    height
  }
`;

export const MENU_FRAGMENT = `#graphql
  fragment MenuFields on Menu {
    id
    handle
    title
    items {
      id
      title
      url
      type
      items {
        id
        title
        url
        type
        items {
          id
          title
          url
          type
        }
      }
    }
  }
`;

export const SHOP_FRAGMENT = `#graphql
  fragment ShopFields on Shop {
    id
    name
    description
    primaryDomain {
      url
    }
    privacyPolicy {
      id
      handle
      title
      body
      url
    }
    shippingPolicy {
      id
      handle
      title
      body
      url
    }
    termsOfService {
      id
      handle
      title
      body
      url
    }
    refundPolicy {
      id
      handle
      title
      body
      url
    }
    subscriptionPolicy {
      id
      handle
      title
      body
      url
    }
  }
`;

export const PRODUCT_CARD_FRAGMENT = `#graphql
  fragment ProductCardFields on Product {
    id
    handle
    title
    vendor
    featuredImage {
      ...ImageFields
    }
    priceRange {
      minVariantPrice {
        ...MoneyFields
      }
    }
  }
`;

export const PRODUCT_VARIANT_FRAGMENT = `#graphql
  fragment ProductVariantFields on ProductVariant {
    id
    title
    availableForSale
    quantityAvailable
    selectedOptions {
      name
      value
    }
    image {
      ...ImageFields
    }
    price {
      ...MoneyFields
    }
    compareAtPrice {
      ...MoneyFields
    }
    product {
      title
      handle
    }
  }
`;

export const CART_FRAGMENT = `#graphql
  fragment CartVariantFields on ProductVariant {
    ...ProductVariantFields
  }

  fragment CartLineFields on CartLine {
    id
    quantity
    cost {
      totalAmount {
        ...MoneyFields
      }
    }
    merchandise {
      ... on ProductVariant {
        ...CartVariantFields
      }
    }
  }

  fragment ComponentCartLineFields on ComponentizableCartLine {
    id
    quantity
    cost {
      totalAmount {
        ...MoneyFields
      }
    }
    merchandise {
      ... on ProductVariant {
        ...CartVariantFields
      }
    }
  }

  fragment CartFields on Cart {
    id
    checkoutUrl
    totalQuantity
    cost {
      subtotalAmount {
        ...MoneyFields
      }
      totalAmount {
        ...MoneyFields
      }
      totalTaxAmount {
        ...MoneyFields
      }
    }
    lines(first: 100) {
      nodes {
        __typename
        ... on CartLine {
          ...CartLineFields
        }
        ... on ComponentizableCartLine {
          ...ComponentCartLineFields
        }
      }
    }
    discountCodes {
      code
      applicable
    }
    discountAllocations {
      discountedAmount {
        ...MoneyFields
      }
      targetType
      ... on CartCodeDiscountAllocation {
        code
      }
    }
  }
`;

export const ROOT_QUERY = `#graphql
  query Root($headerMenuHandle: String!, $footerMenuHandle: String!) {
    shop {
      ...ShopFields
    }
    headerMenu: menu(handle: $headerMenuHandle) {
      ...MenuFields
    }
    footerMenu: menu(handle: $footerMenuHandle) {
      ...MenuFields
    }
  }
  ${SHOP_FRAGMENT}
  ${MENU_FRAGMENT}
`;

export const CART_QUERY = `#graphql
  query Cart($cartId: ID!) {
    cart(id: $cartId) {
      ...CartFields
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_VARIANT_FRAGMENT}
  ${CART_FRAGMENT}
`;

export const HOME_QUERY = `#graphql
  query Home {
    shop {
      ...ShopFields
    }
    collections(first: 6) {
      nodes {
        id
        handle
        title
        description
        image {
          ...ImageFields
        }
      }
    }
    products(first: 8) {
      nodes {
        ...ProductCardFields
      }
    }
  }
  ${SHOP_FRAGMENT}
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_CARD_FRAGMENT}
`;

export const COLLECTIONS_QUERY = `#graphql
  query Collections {
    collections(first: 50) {
      nodes {
        id
        handle
        title
        description
        image {
          ...ImageFields
        }
      }
    }
  }
  ${IMAGE_FRAGMENT}
`;

export const COLLECTION_QUERY = `#graphql
  query Collection($handle: String!) {
    collection(handle: $handle) {
      id
      handle
      title
      description
      descriptionHtml
      image {
        ...ImageFields
      }
      products(first: 50) {
        totalCount
        nodes {
          ...ProductCardFields
        }
      }
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_CARD_FRAGMENT}
`;

export const PRODUCT_QUERY = `#graphql
  query Product($handle: String!) {
    product(handle: $handle) {
      ...ProductCardFields
      description
      descriptionHtml
      productType
      images(first: 10) {
        nodes {
          ...ImageFields
        }
      }
      variants(first: 100) {
        nodes {
          ...ProductVariantFields
        }
      }
      selectedOrFirstAvailableVariant {
        ...ProductVariantFields
      }
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_CARD_FRAGMENT}
  ${PRODUCT_VARIANT_FRAGMENT}
`;

export const SEARCH_QUERY = `#graphql
  query Search($query: String!) {
    search(query: $query, first: 50, types: [PRODUCT, PAGE, ARTICLE]) {
      totalCount
      nodes {
        __typename
        ... on Product {
          ...ProductCardFields
        }
        ... on Page {
          id
          handle
          title
          body
        }
        ... on Article {
          id
          handle
          title
          contentHtml
          blog {
            handle
          }
        }
      }
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_CARD_FRAGMENT}
`;

export const PAGE_QUERY = `#graphql
  query Page($handle: String!) {
    page(handle: $handle) {
      id
      handle
      title
      body
    }
  }
`;

export const POLICIES_QUERY = `#graphql
  query Policies {
    shop {
      privacyPolicy {
        id
        handle
        title
        body
        url
      }
      shippingPolicy {
        id
        handle
        title
        body
        url
      }
      termsOfService {
        id
        handle
        title
        body
        url
      }
      refundPolicy {
        id
        handle
        title
        body
        url
      }
      subscriptionPolicy {
        id
        handle
        title
        body
        url
      }
    }
  }
`;

export const CART_CREATE_MUTATION = `#graphql
  mutation CartCreate($input: CartInput!) {
    cartCreate(input: $input) {
      cart {
        ...CartFields
      }
      userErrors {
        message
      }
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_VARIANT_FRAGMENT}
  ${CART_FRAGMENT}
`;

export const CART_LINES_ADD_MUTATION = `#graphql
  mutation CartLinesAdd($cartId: ID!, $lines: [CartLineInput!]!) {
    cartLinesAdd(cartId: $cartId, lines: $lines) {
      cart {
        ...CartFields
      }
      userErrors {
        message
      }
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_VARIANT_FRAGMENT}
  ${CART_FRAGMENT}
`;

export const CART_LINES_UPDATE_MUTATION = `#graphql
  mutation CartLinesUpdate($cartId: ID!, $lines: [CartLineUpdateInput!]!) {
    cartLinesUpdate(cartId: $cartId, lines: $lines) {
      cart {
        ...CartFields
      }
      userErrors {
        message
      }
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_VARIANT_FRAGMENT}
  ${CART_FRAGMENT}
`;

export const CART_LINES_REMOVE_MUTATION = `#graphql
  mutation CartLinesRemove($cartId: ID!, $lineIds: [ID!]!) {
    cartLinesRemove(cartId: $cartId, lineIds: $lineIds) {
      cart {
        ...CartFields
      }
      userErrors {
        message
      }
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_VARIANT_FRAGMENT}
  ${CART_FRAGMENT}
`;

export const CART_DISCOUNT_CODES_UPDATE_MUTATION = `#graphql
  mutation CartDiscountCodesUpdate($cartId: ID!, $discountCodes: [String!]) {
    cartDiscountCodesUpdate(cartId: $cartId, discountCodes: $discountCodes) {
      cart {
        ...CartFields
      }
      userErrors {
        message
      }
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${PRODUCT_VARIANT_FRAGMENT}
  ${CART_FRAGMENT}
`;

export const MAILING_ADDRESS_FRAGMENT = `#graphql
  fragment MailingAddressFields on MailingAddress {
    id
    firstName
    lastName
    company
    address1
    address2
    city
    province
    country
    zip
    phone
    formatted
  }
`;

export const CUSTOMER_FRAGMENT = `#graphql
  fragment CustomerFields on Customer {
    id
    email
    firstName
    lastName
    displayName
    phone
    defaultAddress {
      ...MailingAddressFields
    }
  }
`;

export const ORDER_SUMMARY_FRAGMENT = `#graphql
  fragment OrderSummaryFields on Order {
    id
    name
    orderNumber
    processedAt
    financialStatus
    fulfillmentStatus
    totalPrice {
      ...MoneyFields
    }
  }
`;

export const ORDER_DETAIL_FRAGMENT = `#graphql
  fragment OrderDetailFields on Order {
    ...OrderSummaryFields
    email
    subtotalPrice {
      ...MoneyFields
    }
    totalShippingPrice {
      ...MoneyFields
    }
    totalTax {
      ...MoneyFields
    }
    shippingAddress {
      ...MailingAddressFields
    }
    shippingMethod
    paymentMethod
    discountCode {
      code
      targetType
      amount {
        ...MoneyFields
      }
    }
    lineItems(first: 100) {
      nodes {
        title
        quantity
        originalTotalPrice {
          ...MoneyFields
        }
        variant {
          ...ProductVariantFields
          sku
        }
      }
    }
  }
`;

export const CUSTOMER_QUERY = `#graphql
  query Customer($customerAccessToken: String!) {
    customer(customerAccessToken: $customerAccessToken) {
      ...CustomerFields
    }
  }
  ${MAILING_ADDRESS_FRAGMENT}
  ${CUSTOMER_FRAGMENT}
`;

export const CUSTOMER_ADDRESSES_QUERY = `#graphql
  query CustomerAddresses($customerAccessToken: String!) {
    customer(customerAccessToken: $customerAccessToken) {
      ...CustomerFields
      addresses(first: 50) {
        nodes {
          ...MailingAddressFields
        }
      }
    }
  }
  ${MAILING_ADDRESS_FRAGMENT}
  ${CUSTOMER_FRAGMENT}
`;

export const CUSTOMER_ORDERS_QUERY = `#graphql
  query CustomerOrders($customerAccessToken: String!, $first: Int!) {
    customer(customerAccessToken: $customerAccessToken) {
      ...CustomerFields
      addresses(first: 50) {
        nodes {
          id
        }
      }
      orders(first: $first, reverse: true, sortKey: PROCESSED_AT) {
        totalCount
        nodes {
          ...OrderSummaryFields
        }
      }
    }
  }
  ${MONEY_FRAGMENT}
  ${MAILING_ADDRESS_FRAGMENT}
  ${CUSTOMER_FRAGMENT}
  ${ORDER_SUMMARY_FRAGMENT}
`;

export const ORDER_QUERY = `#graphql
  query Order($id: ID!) {
    order(id: $id) {
      ...OrderDetailFields
    }
  }
  ${IMAGE_FRAGMENT}
  ${MONEY_FRAGMENT}
  ${MAILING_ADDRESS_FRAGMENT}
  ${PRODUCT_VARIANT_FRAGMENT}
  ${ORDER_SUMMARY_FRAGMENT}
  ${ORDER_DETAIL_FRAGMENT}
`;

export const COMMERCE_SETTINGS_QUERY = `#graphql
  query CommerceSettings {
    commerceSettings {
      currencyCode
      taxRate
      freeShippingThreshold {
        ...MoneyFields
      }
      shippingMethods {
        handle
        title
        price {
          ...MoneyFields
        }
      }
      paymentMethods {
        handle
        title
      }
    }
  }
  ${MONEY_FRAGMENT}
`;

export const CUSTOMER_CREATE_MUTATION = `#graphql
  mutation CustomerCreate($input: CustomerCreateInput!) {
    customerCreate(input: $input) {
      customer {
        id
      }
      customerUserErrors {
        code
        field
        message
      }
    }
  }
`;

export const CUSTOMER_ACCESS_TOKEN_CREATE_MUTATION = `#graphql
  mutation CustomerAccessTokenCreate($input: CustomerAccessTokenCreateInput!) {
    customerAccessTokenCreate(input: $input) {
      customerAccessToken {
        accessToken
        expiresAt
      }
      customerUserErrors {
        code
        field
        message
      }
    }
  }
`;

export const CUSTOMER_ACCESS_TOKEN_DELETE_MUTATION = `#graphql
  mutation CustomerAccessTokenDelete($customerAccessToken: String!) {
    customerAccessTokenDelete(customerAccessToken: $customerAccessToken) {
      deletedAccessToken
      userErrors {
        message
      }
    }
  }
`;

export const CART_BUYER_IDENTITY_UPDATE_MUTATION = `#graphql
  mutation CartBuyerIdentityUpdate($cartId: ID!, $buyerIdentity: CartBuyerIdentityInput!) {
    cartBuyerIdentityUpdate(cartId: $cartId, buyerIdentity: $buyerIdentity) {
      cart {
        id
      }
      userErrors {
        message
      }
    }
  }
`;

export const CHECKOUT_COMPLETE_MUTATION = `#graphql
  mutation CheckoutComplete($cartId: ID!, $input: CheckoutCompleteInput!) {
    checkoutComplete(cartId: $cartId, input: $input) {
      order {
        id
        orderNumber
      }
      userErrors {
        code
        field
        message
      }
    }
  }
`;
