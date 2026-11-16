import { type ActionFunctionArgs, redirect } from 'react-router';
import { clearCustomerAccessToken, getAppContext, getCustomerAccessToken } from '~/lib/context';
import { CUSTOMER_ACCESS_TOKEN_DELETE_MUTATION } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';

interface CustomerAccessTokenDeleteData {
  readonly customerAccessTokenDelete: {
    readonly deletedAccessToken: string | null;
  };
}

export function loader() {
  return redirect('/account');
}

export async function action({ context }: ActionFunctionArgs) {
  const appContext = getAppContext(context);
  const customerAccessToken = getCustomerAccessToken(appContext);
  if (customerAccessToken !== null) {
    await storefrontQuery<CustomerAccessTokenDeleteData>(
      appContext,
      CUSTOMER_ACCESS_TOKEN_DELETE_MUTATION,
      { customerAccessToken },
    );
  }
  return redirect('/', { headers: await clearCustomerAccessToken(appContext) });
}
