import { useState, useEffect } from 'react';

let _lastFetchedAt = null;
const _listeners = new Set();

export function markDataFetched() {
  _lastFetchedAt = Date.now();
  _listeners.forEach((fn) => fn(_lastFetchedAt));
}

export function useDataFreshness() {
  const [ts, setTs] = useState(_lastFetchedAt);

  useEffect(() => {
    const handler = (newTs) => setTs(newTs);
    _listeners.add(handler);
    return () => _listeners.delete(handler);
  }, []);

  return ts;
}

export function useRelativeTimeLabel(timestamp) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, []);

  if (!timestamp) return 'Загрузка...';

  const diffSec = Math.floor((now - timestamp) / 1000);
  if (diffSec < 10) return 'Только что';
  if (diffSec < 60) return `${diffSec} сек. назад`;
  if (diffSec < 3600) {
    const m = Math.floor(diffSec / 60);
    return `${m} мин. назад`;
  }
  const h = Math.floor(diffSec / 3600);
  return `${h} ч. назад`;
}
