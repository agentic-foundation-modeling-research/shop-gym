import {
  useFetcher,
  useNavigate,
  type FormProps,
  type Fetcher,
} from 'react-router';
import {
  useRef,
  useEffect,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import type {PredictiveSearchReturn} from '~/lib/search';

type SearchFormPredictiveChildren = (args: {
  fetchResults: (event: ChangeEvent<HTMLInputElement>) => void;
  goToSearch: () => void;
  inputRef: RefObject<HTMLInputElement | null>;
  fetcher: Fetcher<PredictiveSearchReturn>;
}) => ReactNode;

type SearchFormPredictiveProps = Omit<FormProps, 'children'> & {
  children: SearchFormPredictiveChildren | null;
  onSubmitSearch?: () => void;
};

export const SEARCH_ENDPOINT = '/search';

export function SearchFormPredictive({
  children,
  className = 'predictive-search-form',
  onSubmitSearch,
  ...props
}: SearchFormPredictiveProps) {
  const fetcher = useFetcher<PredictiveSearchReturn>({key: 'search'});
  const inputRef = useRef<HTMLInputElement | null>(null);
  const navigate = useNavigate();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.stopPropagation();
    goToSearch();
  }

  function goToSearch() {
    const term = inputRef?.current?.value?.trim();
    if (term) {
      void navigate(
        `${SEARCH_ENDPOINT}?q=${encodeURIComponent(term)}&type=product`,
      );
    } else {
      void navigate(SEARCH_ENDPOINT);
    }
    if (inputRef?.current) {
      inputRef.current.blur();
    }
    onSubmitSearch?.();
  }

  function fetchResults(event: ChangeEvent<HTMLInputElement>) {
    void fetcher.submit(
      {q: event.target.value || '', limit: 5, predictive: true},
      {method: 'GET', action: SEARCH_ENDPOINT},
    );
  }

  useEffect(() => {
    inputRef?.current?.setAttribute('type', 'search');
  }, []);

  if (typeof children !== 'function') {
    return null;
  }

  return (
    <fetcher.Form
      {...props}
      className={className}
      onSubmit={onSubmit}
      role="search"
    >
      {children({inputRef, fetcher, fetchResults, goToSearch})}
    </fetcher.Form>
  );
}
