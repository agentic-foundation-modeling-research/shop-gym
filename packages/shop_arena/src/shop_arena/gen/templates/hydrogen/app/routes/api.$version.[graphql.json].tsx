import type {Route} from './+types/api.$version.[graphql.json]';

export async function action({params, context, request}: Route.ActionArgs) {
  const init: RequestInit & {duplex?: 'half'} = {
    method: 'POST',
    body: request.body,
    headers: request.headers,
    duplex: 'half',
  };
  const response = await fetch(
    `${context.env.PUBLIC_STORE_DOMAIN}/api/${params.version}/graphql.json`,
    init,
  );

  return new Response(response.body, {headers: new Headers(response.headers)});
}
