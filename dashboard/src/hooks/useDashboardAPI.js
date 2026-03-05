import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../lib/api';
import { markDataFetched } from '../lib/dataFreshness';

const AUTO_REFRESH_MS = 60_000;

export function useFetch(url, params = {}, deps = [], options = {}) {
  const { refreshInterval = 0, refreshKey = 0 } = options;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastFetchedAt, setLastFetchedAt] = useState(null);
  const [softRefreshing, setSoftRefreshing] = useState(false);
  const abortRef = useRef(null);
  const reqIdRef = useRef(0);
  const hasLoadedOnce = useRef(false);

  const fetchData = useCallback(async (soft = false) => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const id = ++reqIdRef.current;

    if (soft && hasLoadedOnce.current) {
      setSoftRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const { data: res } = await api.get(url, { params, signal: controller.signal });
      if (reqIdRef.current === id) {
        setData(res);
        setLastFetchedAt(Date.now());
        hasLoadedOnce.current = true;
        markDataFetched();
      }
    } catch (err) {
      if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') return;
      if (reqIdRef.current === id && !soft) {
        setError(err.response?.data?.error || err.message);
      }
    } finally {
      if (reqIdRef.current === id) {
        setLoading(false);
        setSoftRefreshing(false);
      }
    }
  }, [url, JSON.stringify(params), refreshKey, ...deps]);

  useEffect(() => {
    fetchData(false);
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, [fetchData]);

  useEffect(() => {
    if (!refreshInterval || refreshInterval <= 0) return;
    const timer = setInterval(() => fetchData(true), refreshInterval);
    return () => clearInterval(timer);
  }, [fetchData, refreshInterval]);

  return {
    data, loading, error, softRefreshing, lastFetchedAt,
    refetch: useCallback(() => fetchData(false), [fetchData]),
  };
}

export function useOverview(period) {
  return useFetch('/dashboard/overview', { period }, [period], { refreshInterval: AUTO_REFRESH_MS });
}

export function useOverviewChart(period, metric) {
  return useFetch('/dashboard/overview/chart', { period, metric }, [period, metric]);
}

export function useRecentConversations(limit = 5) {
  return useFetch('/dashboard/overview/recent', { limit }, [limit], { refreshInterval: AUTO_REFRESH_MS });
}

export function useConversations(page, perPage, period, searchQuery, sortBy, sortDir, hasBooking, hasCards) {
  const params = { page, per_page: perPage };
  if (period !== 'all') params.period = period;
  if (hasCards !== undefined) params.has_cards = hasCards;
  if (hasBooking !== undefined) params.has_booking = hasBooking;
  if (searchQuery) params.search = searchQuery;
  if (sortBy) params.sort_by = sortBy;
  if (sortDir) params.sort_dir = sortDir;
  return useFetch('/dashboard/conversations', params, [page, perPage, period, searchQuery, sortBy, sortDir, hasBooking, hasCards]);
}

export function useConversationDetail(id) {
  return useFetch(`/dashboard/conversations/${id}`, {}, [id]);
}

export function useConversationSearches(id) {
  return useFetch(`/dashboard/conversations/${id}/searches`, {}, [id]);
}

export function useAnalyticsDestinations(period, opts = {}) {
  return useFetch('/dashboard/analytics/destinations', { period }, [period], opts);
}

export function useAnalyticsDepartures(period, opts = {}) {
  return useFetch('/dashboard/analytics/departures', { period }, [period], opts);
}

export function useAnalyticsSearchParams(period, opts = {}) {
  return useFetch('/dashboard/analytics/search-params', { period }, [period], opts);
}

export function useAnalyticsResponseTimes(period, opts = {}) {
  return useFetch('/dashboard/analytics/response-times', { period }, [period], opts);
}

export function useAnalyticsSearchTypes(period, opts = {}) {
  return useFetch('/dashboard/analytics/search-types', { period }, [period], opts);
}

export function useAnalyticsPerformance(period, opts = {}) {
  return useFetch('/dashboard/analytics/performance', { period }, [period], opts);
}

export function useAnalyticsBusinessMetrics(period, opts = {}) {
  return useFetch('/dashboard/analytics/business-metrics', { period }, [period], opts);
}

export function useAnalyticsDemand(period, opts = {}) {
  return useFetch('/dashboard/analytics/demand', { period }, [period], opts);
}

export function useAnalyticsOperators(period, opts = {}) {
  return useFetch('/dashboard/analytics/operators', { period }, [period], opts);
}

export function useAnalyticsActivity(period, opts = {}) {
  return useFetch('/dashboard/analytics/activity', { period }, [period], opts);
}

export function useAnalyticsTravelDates(period, opts = {}) {
  return useFetch('/dashboard/analytics/travel-dates', { period }, [period], opts);
}

export function useAIReport(period, params = {}, opts = {}) {
  return useFetch('/dashboard/analytics/ai-report', { period, ...params }, [period, JSON.stringify(params)], opts);
}

export function useSystemHealth() {
  return useFetch('/dashboard/system/health');
}

export function useAssistants() {
  return useFetch('/dashboard/assistants');
}

export function useWidgetConfig() {
  return useFetch('/dashboard/widget/config');
}

export function useWidgetEmbedCode() {
  return useFetch('/dashboard/widget/embed-code');
}

export function useAccount() {
  return useFetch('/dashboard/account');
}
