-- Re-outreach candidate selection (AnyTour-pinned, READ-ONLY).
-- One JSON object per line (psql -t -A). Placeholders substituted by gen_report.py.
--   {SILENCE_HOURS} : min hours of client silence to be eligible
--   {LOOKBACK_DAYS} : do not resurrect dialogues older than this
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
  'last_asst', (SELECT left(regexp_replace(m.content,'\s+',' ','g'),160) FROM messages m
                WHERE m.conversation_id=c.id AND m.role='assistant' AND m.content IS NOT NULL
                ORDER BY m.created_at DESC LIMIT 1),
  'uid', COALESCE(c.external_user_id,''),
  'chat_id', c.external_chat_id
)
FROM conversations c
WHERE c.assistant_id = '64fea0d3-2605-4c4c-be67-62258ebfa7a9'
  AND c.channel='max'
  AND c.last_active_at <= now() - interval '{SILENCE_HOURS} hours'
  AND c.last_active_at >= now() - interval '{LOOKBACK_DAYS} days'
  AND COALESCE(c.external_user_id,'') NOT IN ('213771498','999900111','999900222','880001','880002','880003','880004')
ORDER BY c.last_active_at DESC;
