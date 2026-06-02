-- Re-outreach PER-USER candidate selection (AnyTour, READ-ONLY).
-- One row per external_user_id = their MOST RECENT conversation. Eligible when
-- that latest dialogue has been silent >= {SILENCE_HOURS}h (counter resets when
-- the client writes again, because last_active_at moves). One JSON object per line.
-- Placeholders: {SILENCE_HOURS}, {LOOKBACK_DAYS}.
WITH latest AS (
  SELECT DISTINCT ON (COALESCE(c.external_user_id, ''))
    c.id, COALESCE(c.external_user_id, '') AS uid, c.external_chat_id AS chat_id,
    c.session_id, c.last_active_at,
    c.search_count AS searches, c.tour_cards_shown AS cards, c.tour_clicks AS clicks
  FROM conversations c
  WHERE c.assistant_id = '64fea0d3-2605-4c4c-be67-62258ebfa7a9'
    AND c.channel = 'max'
    AND COALESCE(c.external_user_id, '') <> ''
  ORDER BY COALESCE(c.external_user_id, ''), c.last_active_at DESC
)
SELECT json_build_object(
  'id', l.id,
  'uid', l.uid,
  'chat_id', l.chat_id,
  'session_id', l.session_id,
  'last_active_epoch', extract(epoch from l.last_active_at)::bigint,
  'idle_hours', round(extract(epoch from (now() - l.last_active_at)) / 3600.0, 1),
  'searches', l.searches,
  'cards', l.cards,
  'clicks', l.clicks,
  'umsgs', (SELECT count(*) FROM messages m WHERE m.conversation_id = l.id AND m.role = 'user'),
  'submitted', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id = l.id AND m.role = 'assistant'
                      AND m.tool_calls::text LIKE '%submit_client_request%'),
  'handoff', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id = l.id AND m.role = 'assistant'
                    AND m.content ~* '(составн\w* маршрут|внутренн\w* перел|менеджер (собер|подбер|свяж)|передал.{0,20}менеджер|вручную)'),
  'decline', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id = l.id AND m.role = 'user'
                    AND m.content ~* '(не нужно|не интересн|не надо|передумал|уже (куп|забронир|нашл))'),
  'optout', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id = l.id AND m.role = 'user'
                   AND m.content ~* '(не пиши|не пишите|отпишите|отписаться|больше не пиши|не беспоко|stop\b|унсаб|unsubscribe)'),
  'search_meta', (SELECT json_build_object('date_from', ts.date_from, 'date_to', ts.date_to,
                    'adults', ts.adults, 'children', ts.children, 'stars', ts.stars, 'meal', ts.meal,
                    'price_to', ts.price_to, 'country', ts.country, 'departure', ts.departure)
                  FROM tour_searches ts WHERE ts.conversation_id = l.id ORDER BY ts.created_at DESC LIMIT 1),
  'utext', (SELECT left(regexp_replace(string_agg(regexp_replace(m.content, '\[(ИСТОЧНИК|КОНТЕКСТ):[^\]]*\]', '', 'g'), ' ¦ ' ORDER BY m.created_at), '\s+', ' ', 'g'), 400)
            FROM messages m WHERE m.conversation_id = l.id AND m.role = 'user')
)
FROM latest l
WHERE l.last_active_at <= now() - interval '{SILENCE_HOURS} hours'
  AND l.last_active_at >= now() - interval '{LOOKBACK_DAYS} days'
  AND l.uid NOT IN ('213771498', '999900111', '999900222', '880001', '880002', '880003', '880004')
ORDER BY l.last_active_at DESC;
