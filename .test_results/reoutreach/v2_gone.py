#!/usr/bin/env python3
"""V2: earlier-shown tour is GONE -> assistant must say so + offer alternatives.

Clean setup: NO active подборка, ONLY one earlier-shown hotel with a BOGUS
hotelcode (returns no tours). Ask for it by name. Expect: targeted search returns
nothing -> honest 'уже нет' + alternatives.
Run from backend/: cd backend && python3 ../.test_results/reoutreach/v2_gone.py
"""
import asyncio
import behavior_test as B


async def main():
    h = B.OpenAIHandler()
    print(">>> seeding...")
    await B.seed(h)
    snap = B.snapshot(h)
    B.restore(h, snap)
    h._tourid_map = {}
    h._pending_tour_cards = []
    h._pinned_context = (
        "[КОНТЕКСТ: текущей активной подборки нет]\n\n"
        "[КОНТЕКСТ: ранее показанные туры — для справки, цены могли измениться]\n"
        "- DREAM PALACE EXCLUSIVE (hotelcode=99999999)\n"
        "Если клиент ссылается на ранее показанные/предыдущие варианты — это ИМЕННО "
        "отели из списка выше. Чтобы показать их с актуальными ценами, вызови search_tours "
        "с параметром hotels=<hotelcode этих отелей через запятую> и теми же датами/составом "
        "(НЕ делай общий поиск). Если какого-то отеля НЕТ в результатах — значит тура на эти "
        "даты больше нет: честно скажи это по конкретному отелю и предложи ближайшие альтернативы."
    )
    calls, orig = B.wrap_search(h)
    print("\n### V2 earlier tour GONE (bogus hotelcode 99999999)")
    for msg in ["Покажите, пожалуйста, отель DREAM PALACE EXCLUSIVE, который вы предлагали ранее.",
                "Да, проверьте по нему актуальные цены."]:
        rep = await h.chat(msg)
        print(f"  CLIENT: {msg}")
        print(f"  ASSIST: {(rep or '')[:340]}")
    h.tourvisor.search_tours = orig
    print(f"\nsearched={len(calls)}  hotels_arg={[c.get('hotels') for c in calls]}")


if __name__ == "__main__":
    asyncio.run(main())
