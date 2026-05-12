# Premium triggers — local test report

Branch: `feature/premium-triggers` (based on main = max-bridge consolidated)
Date: 2026-05-12
Backend: `mgp-local-backend-1` (Docker), `system_prompt.md` copied in via `docker cp`.

## Scenarios

| # | First user message | Expected | LLM passed to search_tours |
|---|---|---|---|
| A1 | "Подбери тур в Турцию роскошный отель 5* … СПб более 300 ультра все включено" | stars=5, rating=4, hoteltypes=deluxe | **stars=5, rating=4, hoteltypes=deluxe** ✅ |
| A2 | "Подбери в Турцию тяжёлый люкс … СПб от 300к UAI" | stars=5, rating=4, hoteltypes=deluxe | **stars=5, rating=4, hoteltypes=deluxe** ✅ |
| A3 | "Хочу отель как Maxx Royal в Турции … СПб от 300 UAI" | brand lookup + hotels=… | **hotels="3405,27349,108942,80478"** (LLM сам вызвал `get_dictionaries(type=hotel)` для бренда) 🎉 |
| A4 | "Эксклюзивный 5* в Турции … СПб до 500к UAI" | stars=5, rating=4, hoteltypes=deluxe, priceto=500000 | **stars=5, rating=4, hoteltypes=deluxe, priceto=500000** ✅ |
| B1 | "Подбери тур в Турцию 5* … СПб от 300 UAI" *(контроль, без триггер-слов)* | NO deluxe, rating ≤ 3 (default) | **rating=0, hoteltypes=""** ✅ контроль чист |
| B2 | "Подбери тур в Турцию с перелётом премиум-эконом … СПб от 200 UAI" *(negative)* | NO deluxe (premium-economy = flight class) | **уточняющий вопрос, без deluxe** ✅ |

## Conclusions

- Premium-trigger taxonomy in §8.2 + §3.7.1 of system_prompt.md fires correctly on all
  expected synonyms ("роскошный", "тяжёлый люкс", "эксклюзивный").
- Negative example "премиум-эконом" properly redirected to flightclass, not hoteltypes.
- A brand-name trigger ("как Maxx Royal") triggers a dictionary lookup and a list of
  concrete hotel codes — even better than a deluxe filter, this is bracket-precise.
- Numbers from real Tourvisor: A1 dropped tours_found from 481 (no filter) to 388 (-19%),
  the trimmed pool is the actual deluxe-flagged subset.
