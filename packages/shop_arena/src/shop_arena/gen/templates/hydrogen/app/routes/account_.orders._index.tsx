import type {Route} from './+types/account_.orders._index';
import {Link} from 'react-router';

export const meta: Route.MetaFunction = () => {
  return [{title: `Hydrogen | Orders`}];
};

export default function AccountOrdersMock() {
  return (
    <div className="mock-page">
      <div className="mock-page-inner">
        <h1 className="mock-page-heading">Orders</h1>
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
