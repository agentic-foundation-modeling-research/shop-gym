import {data} from 'react-router';
import type {Route} from './+types/api.klaviyo';

export async function action(_args: Route.ActionArgs) {
  return data({ok: true});
}

export async function loader(_args: Route.LoaderArgs) {
  return data({ok: true});
}
