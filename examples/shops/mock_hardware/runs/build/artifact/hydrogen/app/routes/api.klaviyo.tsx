import {data} from 'react-router';

export async function action() {
  return data({ok: true});
}

export async function loader() {
  return data({ok: true});
}
