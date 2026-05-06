import {data} from 'react-router';
import type {Route} from './+types/api.newsletter';

export async function action({request}: Route.ActionArgs) {
  try {
    const formData = await request.formData();
    const email = String(formData.get('email') || '').trim();
    return data({ok: true, email});
  } catch {
    return data({ok: true});
  }
}

export async function loader() {
  return data({ok: true});
}
