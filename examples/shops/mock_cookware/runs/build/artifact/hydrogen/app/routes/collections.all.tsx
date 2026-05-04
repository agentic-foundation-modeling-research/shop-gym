import {redirect} from 'react-router';
import type {Route} from './+types/collections.all';

export const meta: Route.MetaFunction = () => {
  return [{title: 'Mock Cookware | All Products'}];
};

export async function loader(_args: Route.LoaderArgs) {
  return redirect('/collections/all');
}

export default function CollectionsAllRedirect() {
  return null;
}
