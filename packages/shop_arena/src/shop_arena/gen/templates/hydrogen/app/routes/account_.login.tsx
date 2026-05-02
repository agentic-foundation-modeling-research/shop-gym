import type {Route} from './+types/account_.login';
import {Link} from 'react-router';

export const meta: Route.MetaFunction = () => {
  return [{title: `Hydrogen | Sign in`}];
};

export default function AccountLoginMock() {
  return (
    <div className="mock-page">
      <div className="mock-page-inner">
        <h1 className="mock-page-heading">Sign in</h1>
        <p className="mock-page-body">
          Customer accounts are not supported in this demo store.
        </p>
        <Link to="/" className="mock-page-link">
          Continue shopping
        </Link>
      </div>
    </div>
  );
}
