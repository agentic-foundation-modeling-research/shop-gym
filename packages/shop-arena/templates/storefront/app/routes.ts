import { type RouteConfig, index, route } from '@react-router/dev/routes';

export default [
  index('routes/home.tsx'),
  route('collections', 'routes/collections.tsx'),
  route('collections/:handle', 'routes/collection.tsx'),
  route('products/:handle', 'routes/product.tsx'),
  route('search', 'routes/search.tsx'),
  route('cart', 'routes/cart.tsx'),
  route('checkout', 'routes/checkout.tsx'),
  route('checkout/confirmation/:orderNumber', 'routes/checkout-confirmation.tsx'),
  route('account', 'routes/account/profile.tsx'),
  route('account/login', 'routes/account/login.tsx'),
  route('account/register', 'routes/account/register.tsx'),
  route('account/logout', 'routes/account/logout.tsx'),
  route('account/addresses', 'routes/account/addresses.tsx'),
  route('account/orders', 'routes/account/orders.tsx'),
  route('account/orders/:orderNumber', 'routes/account/order.tsx'),
  route('pages/:handle', 'routes/page.tsx'),
  route('policies/:handle', 'routes/policy.tsx'),
] satisfies RouteConfig;
