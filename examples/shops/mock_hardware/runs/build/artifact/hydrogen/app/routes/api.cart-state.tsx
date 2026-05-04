import {data} from 'react-router';
import type {Route} from './+types/api.cart-state';

export async function loader({context}: Route.LoaderArgs) {
  const cart = await context.cart.get();
  if (!cart) return data({items: [], total_price: 0, currency: 'USD'});
  const items = (cart.lines?.nodes ?? []).map((line: any) => ({
    id: line.id,
    title: line.merchandise.product.title,
    price: Math.round(parseFloat(line.merchandise.price.amount) * 100),
    variant_id: parseInt(line.merchandise.id.split('/').pop() ?? '0'),
  }));
  return data({
    items,
    total_price: Math.round(parseFloat(cart.cost?.totalAmount?.amount ?? '0') * 100),
    currency: cart.cost?.totalAmount?.currencyCode ?? 'USD',
  });
}