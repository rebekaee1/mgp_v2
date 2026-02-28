import { useState, useEffect, useCallback } from 'react';
import api from '../lib/api';

export function useFetch(url, params = {}, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await api.get(url, { params });
      setData(res);
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  }, [url, JSON.stringify(params), ...deps]);

  useEffect(() => { fetch(); }, [fetch]);

  return { data, loading, error, refetch: fetch };
}

export function useOverview(period) {
  return useFetch('/dashboard/overview', { period }, [period]);
}

export function useOverviewChart(period, metric) {
  return useFetch('/dashboard/overview/chart', { period, metric }, [period, metric]);
}

export function useRecentConversations(limit = 5) {
  return useFetch('/dashboard/overview/recent', { limit }, [limit]);
}

export function useConversations(page, perPage, period, hasSearch, searchQuery, sortBy, sortDir) {
  const params = { page, per_page: perPage };
  if (period !== 'all') params.period = period;
  if (hasSearch !== undefined) params.has_search = hasSearch;
  if (searchQuery) params.search = searchQuery;
  if (sortBy) params.sort_by = sortBy;
  if (sortDir) params.sort_dir = sortDir;
  return useFetch('/dashboard/conversations', params, [page, perPage, period, hasSearch, searchQuery, sortBy, sortDir]);
}

export function useConversationDetail(id) {
  return useFetch(`/dashboard/conversations/${id}`, {}, [id]);
}

export function useConversationSearches(id) {
  return useFetch(`/dashboard/conversations/${id}/searches`, {}, [id]);
}

export function useAnalyticsDestinations(period) {
  return useFetch('/dashboard/analytics/destinations', { period }, [period]);
}

export function useAnalyticsDepartures(period) {
  return useFetch('/dashboard/analytics/departures', { period }, [period]);
}

export function useAnalyticsSearchParams(period) {
  return useFetch('/dashboard/analytics/search-params', { period }, [period]);
}

export function useAnalyticsResponseTimes(period) {
  return useFetch('/dashboard/analytics/response-times', { period }, [period]);
}

export function useAnalyticsSearchTypes(period) {
  return useFetch('/dashboard/analytics/search-types', { period }, [period]);
}

export function useAnalyticsPerformance(period) {
  return useFetch('/dashboard/analytics/performance', { period }, [period]);
}

export function useAnalyticsBusinessMetrics(period) {
  return useFetch('/dashboard/analytics/business-metrics', { period }, [period]);
}

export function useAnalyticsDemand(period) {
  return useFetch('/dashboard/analytics/demand', { period }, [period]);
}

export function useAnalyticsOperators(period) {
  return useFetch('/dashboard/analytics/operators', { period }, [period]);
}

export function useAnalyticsActivity(period) {
  return useFetch('/dashboard/analytics/activity', { period }, [period]);
}

export function useAnalyticsTravelDates(period) {
  return useFetch('/dashboard/analytics/travel-dates', { period }, [period]);
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
