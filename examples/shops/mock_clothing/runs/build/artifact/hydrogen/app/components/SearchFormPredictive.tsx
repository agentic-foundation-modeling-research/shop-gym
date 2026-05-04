import {useEffect, useRef} from 'react';
import {useFetcher, useNavigate, type Fetcher} from 'react-router';
import type {PredictiveSearchReturn} from '~/lib/search';

export const SEARCH_ENDPOINT = '/search';
export const PREDICTIVE_FETCHER_KEY = 'predictive-search';

export type PredictiveSearchHandle = {
  fetcher: Fetcher<PredictiveSearchReturn>;
  inputRef: React.MutableRefObject<HTMLInputElement | null>;
  goToSearch: (term: string) => void;
  fetchResults: (term: string) => void;
};

export function usePredictiveSearchForm({
  autoFocus = false,
  onNavigate,
}: {
  autoFocus?: boolean;
  onNavigate?: () => void;
} = {}): PredictiveSearchHandle {
  const fetcher = useFetcher<PredictiveSearchReturn>({
    key: PREDICTIVE_FETCHER_KEY,
  });
  const inputRef = useRef<HTMLInputElement | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (autoFocus) {
      const t = window.setTimeout(() => inputRef.current?.focus(), 50);
      return () => window.clearTimeout(t);
    }
  }, [autoFocus]);

  const goToSearch = (term: string) => {
    const value = (term ?? '').trim();
    if (!value) return;
    onNavigate?.();
    void navigate(`${SEARCH_ENDPOINT}?q=${encodeURIComponent(value)}`);
  };

  const fetchResults = (term: string) => {
    const value = (term ?? '').trim();
    if (value.length < 2) return;
    void fetcher.submit(
      {q: value, limit: 6, predictive: 'true'},
      {method: 'GET', action: SEARCH_ENDPOINT},
    );
  };

  return {fetcher, inputRef, goToSearch, fetchResults};
}

type SearchFormPredictiveChildren = (
  handle: PredictiveSearchHandle,
) => React.ReactNode;

type SearchFormPredictiveProps = {
  autoFocus?: boolean;
  onNavigate?: () => void;
  children: SearchFormPredictiveChildren;
};

export function SearchFormPredictive({
  autoFocus,
  onNavigate,
  children,
}: SearchFormPredictiveProps) {
  const handle = usePredictiveSearchForm({autoFocus, onNavigate});
  return <>{children(handle)}</>;
}
