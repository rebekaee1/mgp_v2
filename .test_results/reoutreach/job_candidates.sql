-- AnyTour re-outreach candidates: ONE row per CLIENT (latest dialogue), silent in
-- the [now-{LOOKBACK_DAYS}d, now-{SILENCE_HOURS}h] window. READ-ONLY. JSON per line.
WITH latest AS (
  SELECT DISTINCT ON (external_user_id)
         id, session_id, external_user_id, external_chat_id, last_active_at,
         search_count, tour_cards_shown, tour_clicks
  FROM conversations
  WHERE assistant_id = '64fea0d3-2605-4c4c-be67-62258ebfa7a9'
    AND channel = 'max'
    AND external_user_id IS NOT NULL
    AND external_user_id NOT IN ('213771498','999900111','999900222','880001','880002','880003','880004')
    AND last_active_at <= now() - interval '{SILENCE_HOURS} hours'
    AND last_active_at >= now() - interval '{LOOKBACK_DAYS} days'
  ORDER BY external_user_id, last_active_at DESC
)
SELECT json_build_object(
  'id', l.id, 'session_id', l.session_id, 'uid', l.external_user_id, 'chat_id', l.external_chat_id,
  'last_active_epoch', extract(epoch from l.last_active_at)::bigint,
  'searches', l.search_count, 'cards', l.tour_cards_shown, 'clicks', l.tour_clicks,
  'umsgs', (SELECT count(*) FROM messages m WHERE m.conversation_id=l.id AND m.role='user'),
  'submitted', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=l.id AND m.role='assistant'
                      AND m.tool_calls::text LIKE '%submit_client_request%'),
  'handoff', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=l.id AND m.role='assistant'
                    AND m.content ~* '(составн\w* маршрут|внутренн\w* перел|менеджер (собер|подбер|свяж)|передал.{0,20}менеджер|вручную)'),
  'decline', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=l.id AND m.role='user'
                    AND m.content ~* '(не нужно|не интересн|не надо|передумал|уже (куп|забронир|нашл))'),
  'optout', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=l.id AND m.role='user'
                   AND m.content ~* '(не пиши|не писать|отстань|не беспокой|отпиш|хватит писать|больше не пиш|\bstop\b|unsubscribe|заблокир)'),
  'search_meta', (SELECT json_build_object('date_from',ts.date_from,'adults',ts.adults,
                    'children',ts.children,'stars',ts.stars,'price_to',ts.price_to,'departure',ts.departure)
                  FROM tour_searches ts WHERE ts.conversation_id=l.id ORDER BY ts.created_at DESC LIMIT 1),
  'utext', (SELECT left(regexp_replace(string_agg(regexp_replace(m.content,'\[(ИСТОЧНИК|КОНТЕКСТ):[^\]]*\]','','g'),' ¦ ' ORDER BY m.created_at),'\s+',' ','g'),400)
            FROM messages m WHERE m.conversation_id=l.id AND m.role='user')
)
FROM latest l
ORDER BY l.last_active_at DESC;
