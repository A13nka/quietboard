"""Abruf-Lock und Zustellung (Review 3b, M1/M2): Schreibaktionen sehen den neuen Stand, langsame Kanäle halten den
Abruf nicht auf."""

import asyncio

from app import main


def test_fresh_refresh_waits_for_a_new_run(monkeypatch):
    """Läuft gerade ein Abruf, holt refresh(fresh=True) danach einen eigenen – der laufende hat die Änderung evtl.
    noch nicht gesehen. Ohne fresh reicht das Ergebnis des laufenden."""
    runs = []

    async def fake_refresh():
        runs.append(len(runs) + 1)
        await asyncio.sleep(0.05)

    async def scenario():
        monkeypatch.setattr(main, "_refresh_lock", asyncio.Lock())
        monkeypatch.setattr(main, "_refresh", fake_refresh)
        first = asyncio.create_task(main.refresh())
        await asyncio.sleep(0.01)  # erster Abruf läuft
        waiter = asyncio.create_task(main.refresh())  # wartet nur auf den laufenden
        second = asyncio.create_task(main.refresh(fresh=True))
        third = asyncio.create_task(main.refresh(fresh=True))  # beide wollen einen neuen Abruf: einer reicht
        await asyncio.gather(first, waiter, second, third)
        assert runs == [1, 2]
        await main.refresh(fresh=True)  # nichts läuft: neuer Abruf
        assert runs == [1, 2, 3]

    asyncio.run(scenario())


def test_slow_delivery_does_not_block_refresh(monkeypatch):
    started, release = [], asyncio.Event

    async def scenario():
        gate = release()

        async def slow_transitions():
            started.append(1)
            await gate.wait()  # z. B. hängender Mailserver

        async def nothing():
            return None

        monkeypatch.setattr(main, "_deliver_task", None)
        monkeypatch.setattr(main, "check_transitions", slow_transitions)
        monkeypatch.setattr(main, "check_sec_overdue", nothing)
        monkeypatch.setattr(main, "check_source_outage", nothing)
        main._schedule_delivery()
        await asyncio.sleep(0.01)
        main._schedule_delivery()  # läuft noch: keine zweite Auswertung (sonst doppelte Meldungen)
        await asyncio.sleep(0.01)
        assert started == [1]
        assert not main._deliver_task.done()
        gate.set()
        await main.deliveries_done()
        main._schedule_delivery()  # danach wieder möglich
        await main.deliveries_done()
        assert started == [1, 1]

    asyncio.run(scenario())


def test_push_to_devices_in_parallel(monkeypatch):
    """Ein langsames Gerät hält die anderen nicht auf: drei Geräte à 0,2 s brauchen zusammen keine 0,6 s."""

    class Resp:
        status_code = 201
        text = ""

    async def slow_post(self, **kw):
        await asyncio.sleep(0.2)
        return Resp()

    monkeypatch.setattr(main, "VAPID", object())
    monkeypatch.setattr(main, "push_subs", {f"https://push.example/{i}": {"endpoint": i} for i in range(3)})
    monkeypatch.setattr(main.push, "request_args", lambda vapid, sub, msg: {"url": "https://push.example"})
    monkeypatch.setattr(main.httpx.AsyncClient, "post", slow_post)

    async def scenario():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        ok = await main.push_all("Titel")
        return ok, loop.time() - t0

    ok, took = asyncio.run(scenario())
    assert ok == 3 and took < 0.5


def test_beszel_login_cached_and_renewed(monkeypatch):
    """Review 3b-N5: nicht bei jedem Abruf neu anmelden; bei abgelaufenem Token einmal neu."""
    import httpx

    calls = {"auth": 0, "records": 0}
    valid = {"t1"}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("auth-with-password"):
            calls["auth"] += 1
            return httpx.Response(200, json={"token": f"t{calls['auth']}"})
        calls["records"] += 1
        if req.headers.get("Authorization") not in valid:
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(main, "_beszel_auth", {"user": "", "token": ""})
    monkeypatch.setattr(main.CREDS, "beszel_user", "app@example.org")
    monkeypatch.setattr(main.CREDS, "beszel_pass", "x")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as cli:
            await main.fetch_hosts(cli)
            await main.fetch_hosts(cli)
            assert calls == {"auth": 1, "records": 2}
            valid.add("t2")
            valid.discard("t1")  # Token abgelaufen
            await main.fetch_hosts(cli)
            assert calls == {"auth": 2, "records": 4}

    asyncio.run(scenario())
