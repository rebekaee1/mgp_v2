export const COUNTRY_NAMES = {
  1: 'Турция', 2: 'Египет', 3: 'ОАЭ', 4: 'Таиланд', 5: 'Тунис',
  6: 'Греция', 7: 'Кипр', 8: 'Испания', 9: 'Италия', 10: 'Черногория',
  11: 'Болгария', 12: 'Хорватия', 13: 'Чехия', 14: 'Андорра',
  15: 'Куба', 16: 'Доминикана', 17: 'Мексика', 18: 'Ямайка',
  19: 'Мальдивы', 20: 'Сингапур', 21: 'Малайзия',
  22: 'Шри-Ланка', 23: 'Индия (Гоа)', 24: 'Вьетнам',
  25: 'Южная Корея', 26: 'Япония', 27: 'ЮАР',
  28: 'Индонезия (Бали)', 29: 'Камбоджа',
  30: 'Танзания', 31: 'Иордания', 32: 'Марокко', 33: 'Оман',
  34: 'Бахрейн', 35: 'Маврикий', 36: 'Мадагаскар',
  40: 'Австрия', 41: 'Франция', 42: 'Сейшелы', 43: 'Китай',
  44: 'Грузия', 45: 'Армения', 46: 'Азербайджан', 47: 'Узбекистан',
  48: 'Казахстан', 49: 'Кыргызстан',
  76: 'Россия', 90: 'Абхазия',
};

export const DEPARTURE_NAMES = {
  1: 'Москва', 2: 'Санкт-Петербург', 3: 'Екатеринбург', 4: 'Казань',
  5: 'Новосибирск', 6: 'Ростов-на-Дону', 7: 'Самара', 8: 'Уфа',
  9: 'Краснодар', 10: 'Минеральные Воды', 11: 'Нижний Новгород',
  12: 'Пермь', 13: 'Красноярск', 14: 'Воронеж', 15: 'Волгоград',
  16: 'Челябинск', 17: 'Омск', 18: 'Тюмень', 19: 'Иркутск',
  20: 'Хабаровск', 21: 'Владивосток', 22: 'Сочи',
  99: 'Без перелёта',
};

export const MEAL_NAMES = {
  0: 'Любое питание',
  1: 'RO (без питания)', 2: 'BB (завтрак)', 3: 'HB (полупансион)',
  4: 'FB (полный пансион)', 5: 'AI (всё включено)',
  6: 'UAI (ультра всё включено)',
  7: 'HB+ (полупансион+)', 8: 'FB+ (полный пансион+)',
  9: 'AI+ (расш. всё включено)',
};

export const STARS_LABELS = {
  2: '2★', 3: '3★', 4: '4★', 5: '5★',
};

export function formatNumber(n) {
  if (n == null) return '—';
  return new Intl.NumberFormat('ru-RU').format(n);
}

export function formatMs(ms) {
  if (ms == null) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}с` : `${ms}мс`;
}

export function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export function formatShortDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: '2-digit', month: '2-digit',
  });
}

export function formatRelativeTime(iso) {
  if (!iso) return '—';
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 60) return 'только что';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} мин. назад`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} ч. назад`;
  if (diffSec < 172800) return 'вчера';
  if (diffSec < 604800) return `${Math.floor(diffSec / 86400)} дн. назад`;
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
}

export function formatDateLong(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric', month: 'long', year: 'numeric',
  });
}
