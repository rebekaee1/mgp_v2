-- Generic re-outreach candidate selection (READ-ONLY). Any tenant, by param.
-- Placeholders: {ASSISTANT_ID}, {SILENCE_MINUTES} (idle at least), {LOOKBACK_HOURS} (active within).
-- The narrow LOOKBACK_HOURS isolates a fresh pilot dialogue from old users.
SELECT json_build_object(
  'id', c.id,
  'last_active_epoch', extract(epoch from c.last_active_at)::bigint,
  'searches', c.search_count,
  'cards', c.tour_cards_shown,
  'clicks', c.tour_clicks,
  'umsgs', (SELECT count(*) FROM messages m WHERE m.conversation_id=c.id AND m.role='user'),
  'submitted', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND m.role='assistant'
                      AND m.tool_calls::text LIKE '%submit_client_request%'),
  'handoff', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND m.role='assistant'
                    AND m.content ~* '(составн\w* маршрут|внутренн\w* перел|менеджер (собер|подбер|свяж)|передал.{0,20}менеджер|вручную)'),
  'decline', EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND m.role='user'
                    AND m.content ~* '(не нужно|не интересн|не надо|передумал|уже (куп|забронир|нашл))'),
  'search_meta', (SELECT json_build_object('date_from',ts.date_from,'date_to',ts.date_to,
                    'adults',ts.adults,'children',ts.children,'stars',ts.stars,'meal',ts.meal,
                    'price_to',ts.price_to,'country',ts.country,'departure',ts.departure)
                  FROM tour_searches ts WHERE ts.conversation_id=c.id ORDER BY ts.created_at DESC LIMIT 1),
  'utext', (SELECT left(regexp_replace(string_agg(regexp_replace(m.content,'\[(ИСТОЧНИК|КОНТЕКСТ):[^\]]*\]','','g'),' ¦ ' ORDER BY m.created_at),'\s+',' ','g'),400)
            FROM messages m WHERE m.conversation_id=c.id AND m.role='user'),
  'uid', COALESCE(c.external_user_id,''),
  'chat_id', c.external_chat_id
)
FROM conversations c
WHERE c.assistant_id = '{ASSISTANT_ID}'
  AND c.channel='max'
  AND c.last_active_at <= now() - interval '{SILENCE_MINUTES} minutes'
  AND c.last_active_at >= now() - interval '{LOOKBACK_HOURS} hours'
ORDER BY c.last_active_at DESC;
