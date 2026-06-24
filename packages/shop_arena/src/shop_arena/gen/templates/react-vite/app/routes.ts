import {
  index,
  route,
  type RouteConfig,
} from '@react-router/dev/routes';

export default [
  index('routes/home.tsx'),
  route('collections', 'routes/collections.tsx'),
  route('collections/:handle', 'routes/collection.tsx'),
  route('products/:handle', 'routes/product.tsx'),
  route('search', 'routes/search.tsx'),
  route('cart', 'routes/cart.tsx'),
  route('checkout', 'routes/checkout.tsx'),
  route('pages/:handle', 'routes/page.tsx'),
  route('policies/:handle', 'routes/policy.tsx'),
] satisfies RouteConfig;
