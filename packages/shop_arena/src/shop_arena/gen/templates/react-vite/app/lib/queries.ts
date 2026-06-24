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
