"""AI piyasa analisti — tüm istihbarat katmanını tek bağlamda okuyan analist.

Girdi olarak şunların HEPSİ verilir:
  · grafik/teknik durum (chart + kural motoru sinyali)
  · CEX/DEX fiyatı, emir defteri dengesizliği, spread
  · türev tarafı (funding, OI değişimi, long/short, squeeze yönü)
  · balina akışı (büyük emirler, defter duvarları)
  · GÜNCEL HABER başlıkları
  · **piyasa istihbaratı** (engine/marketdata/intel): makro rejim, risk-on/off,
    korku endeksleri, Coinbase primi, ETF akışı, stablecoin likiditesi, sektör
    rotasyonu, MVRV/maliyet tabanı, Hyperliquid konumlanması, smart-money
  · Hyperliquid perp bağlamı (mark, funding, azami kaldıraç) — kaldıraçlı
    işlem önerisi üretilebilsin diye

Çıktı, işleme çevrilebilir yapıda bir JSON'dur: yön, güven, seviyeler,
geçersizleşme noktası, senaryolar ve (istenirse) somut bir perp işlem planı.

LLM yoksa sezgisel fallback devrede kalır — bot asla LLM'e bağımlı değildir.
"""
from __future__ import annotations

import json
import logging
import os

from engine.marketdata import (aggregator, chart, derivatives, news,
                               onchain, whales)
from engine.models import now_ms
from engine.signals import llm

log = logging.getLogger("marketdata.analyst")

# Analiz derinliği: LLM'in üretebileceği azami token. Kısa bütçe uzun
# gerekçeleri ortadan keser; bu yüzden UI'dan seçilebilir hale getirildi.
DEPTHS: dict[str, int] = {
    "kisa": 500,      # tek paragraf görüş
    "normal": 1200,   # varsayılan — seviyeler + senaryolar
    "derin": 2400,    # tam gerekçelendirme + işlem planı
    "cok_derin": 4000,
}
DEFAULT_DEPTH = os.getenv("ANALYST_DEPTH", "normal")


def depth_tokens(depth: str | None = None) -> int:
    """Derinlik adını token bütçesine çevirir. Bilinmeyen ad -> normal."""
    if depth and depth.isdigit():
        return max(200, min(8000, int(depth)))
    key = (depth or DEFAULT_DEPTH or "normal").strip().lower()
    return DEPTHS.get(key, DEPTHS["normal"])


SYSTEM_PROMPT = (
    "Sen kurumsal bir kripto masasinda calisan kidemli piyasa analistisin. "
    "Sana TEK bir varlik icin su katmanlar verilir: grafik/teknik, CEX/DEX "
    "fiyat ve emir defteri, turev (funding/OI/long-short/squeeze), balina "
    "akisi, guncel haberler, PIYASA ISTIHBARATI (makro rejim, risk-on/off, "
    "korku endeksleri, Coinbase primi, ETF akisi, stablecoin likiditesi, "
    "sektor rotasyonu, MVRV maliyet tabani, Hyperliquid konumlanmasi, "
    "smart-money) ve varsa Hyperliquid perp baglami.\n\n"
    "CALISMA KURALLARIN:\n"
    "1. Once ZEMIN: makro rejim ve likidite kripto icin uygun mu? Zemin ters "
    "ise teknik ne kadar guzel olursa olsun guveni dusur.\n"
    "2. Sonra AKIS: ETF/stablecoin/smart-money/balina ayni yonu mu isaret "
    "ediyor, celisiyor mu? Celiski varsa bunu acikca yaz.\n"
    "3. Sonra YAPI: teknik seviyeler, trend, momentum, kirilma/donus.\n"
    "4. Sonra KALABALIK: funding ve long/short kalabaligin nerede oldugunu "
    "soyler. Kalabalik ASIRI tek yonluyse bu CONTRARIAN bir uyaridir.\n"
    "5. En sonda karar. Katmanlar celisiyorsa BEKLE de ve nedenini yaz. "
    "Emin olmadigin sayiyi UYDURMA; veri yoksa 'veri yok' de.\n\n"
    "SADECE su JSON semasinda yanit ver, baska metin yazma:\n"
    '{"bias":"AL|SAT|BEKLE","confidence":0.0-1.0,'
    '"sentiment":"BULLISH|BEARISH|NEUTRAL",'
    '"horizon":"saatlik|gunluk|haftalik",'
    '"macro_view":"makro zemin ve likidite 1-2 cumle",'
    '"flow_view":"ETF/stablecoin/balina/smart-money akisi 1-2 cumle",'
    '"chart_view":"teknik yapi 2-3 cumle",'
    '"crowd_view":"funding/long-short/haber kalabaligi 1-2 cumle",'
    '"levels":{"support":[sayi,...],"resistance":[sayi,...],'
    '"invalidation":sayi_veya_null},'
    '"scenarios":[{"name":"kisa ad","probability":0.0-1.0,"note":"1 cumle"}],'
    '"trade":{"venue":"hyperliquid","side":"LONG|SHORT|YOK",'
    '"entry":sayi_veya_null,"stop":sayi_veya_null,"target":sayi_veya_null,'
    '"leverage":tamsayi,"leverage_note":"kaldirac secim gerekcesi 1 cumle",'
    '"size_hint_pct":0-100,"rationale":"1 cumle"},'
    '"conflicts":["katmanlar arasi celiskiler"],'
    '"risks":["kisa risk maddeleri"],'
    '"summary":"karar gerekcesi 2-3 cumle"}\n\n'
    "KALDIRAC SECIMI SENIN KARARIN. Sabit bir sayi verme; su kurallarla SEC:\n"
    "  · Stop mesafesi belirleyicidir. Stop girise %X uzaksa kaldirac 1/X'ten "
    "KUCUK olmali ki stop likidasyondan ONCE calissin. Ornek: stop %8 uzaksa "
    "azami 5x degil, guvenli taraf 3x'tir.\n"
    "  · Yuksek gerceklesmis oynaklik / genis ATR / dusuk likidite -> DUSUR.\n"
    "  · Katmanlar (zemin+akis+yapi) ayni yonu gosteriyor ve guven yuksekse "
    "ARTIR; celiski varsa 1-2x'te kal ya da YOK de.\n"
    "  · Funding senin yonune karsi agir ise (LONG'ken pozitif ve yuksek) "
    "tasima maliyeti artar -> DUSUR.\n"
    "  · Bant: 1-10x. 1x = kaldiracsiz spot benzeri; sadece kurulum zayifken "
    "ya da oynaklik asiriyken sec. Emin oldugun kurulumda 3-5x makuldur.\n"
    "  · Likidasyona her zaman en az %12 mesafe kalsin.\n"
    "leverage_note alaninda hangi kurali uyguladigini TEK cumleyle yaz.\n"
    "trade.side 'YOK' ise diger trade alanlari null olabilir.\n"
    "Bu yatirim tavsiyesi DEGILDIR; veri yorumudur."
)


def _technical_lines(feed: dict) -> list[str]:
    sig = feed.get("signal") or {}
    markers = feed.get("markers") or []
    out = ["== GRAFIK / TEKNIK (1s) =="]
    if sig:
        out.append(
            f"Kural sinyali: {sig.get('action', '?')} "
            f"(guven %{round(sig.get('confidence', 0) * 100)})")
        if sig.get("rationale"):
            out.append(f"Gostergeler: {sig['rationale']}")
        if sig.get("price"):
            out.append(f"Son fiyat: {sig['price']}")
    if markers:
        last = markers[-3:]
        seq = ", ".join(m.get("action", "?") for m in last)
        out.append(f"Son donus isaretleri: {seq}")
    if len(out) == 1:
        out.append("(grafik verisi yok)")
    return out


def _whale_lines(whale: dict) -> list[str]:
    if not whale:
        return []
    wp = whale.get("pressure") or {}
    out = ["", "== BALINA AKISI (buyuk emirler) =="]
    out.append(
        f"Baski: {whale.get('label', '?')} (skor {wp.get('score', 0):+.2f}) | "
        f"alim {wp.get('buy_usd', 0):,.0f}$ ({wp.get('buy_count', 0)} islem) vs "
        f"satim {wp.get('sell_usd', 0):,.0f}$ ({wp.get('sell_count', 0)} islem)")
    walls = whale.get("walls") or {}
    if walls.get("bids"):
        b = walls["bids"][0]
        out.append(f"En buyuk ALIS duvari: {b['price']:.4f} @ {b['usd']:,.0f}$ (destek)")
    if walls.get("asks"):
        a = walls["asks"][0]
        out.append(f"En buyuk SATIS duvari: {a['price']:.4f} @ {a['usd']:,.0f}$ (direnc)")
    return out


def _deriv_lines(deriv: dict) -> list[str]:
    if not deriv or not deriv.get("ok"):
        return []
    sq = deriv.get("squeeze") or {}
    out = ["", "== TUREV / LIKIDASYON (vadeli) =="]
    out.append(
        f"Funding {deriv.get('funding_pct', 0):+.4f}% | OI degisim "
        f"{deriv.get('oi_change_pct', 0):+.2f}% | L/S oran {deriv.get('ls_ratio', 0)}")
    out.append(f"Squeeze yonu: {sq.get('direction', 'notr')} (skor {sq.get('score', 0):+.2f})"
               + (" | LIKIDASYON KASKADI" if sq.get("cascade") else ""))
    for n in (sq.get("notes") or [])[:3]:
        out.append(f"  - {n}")
    return out


def _intel_lines() -> list[str]:
    """Piyasa istihbarati katmani — analiste ZEMIN bilgisi verir.

    Cache'ten okunur (ag cagrisi yok). Veri yoksa satirlar atlanir; analist
    o zaman yalnizca teknik/haber katmanlariyla calisir.
    """
    try:
        from engine.marketdata.intel import bias as intel_bias
        from engine.marketdata.intel.cache import peek
    except Exception:  # noqa: BLE001
        return []

    out: list[str] = []
    b = intel_bias.market_bias()
    if b.get("ok"):
        out += ["", "== PIYASA ISTIHBARATI (yapisal zemin) =="]
        out.append(f"Birlesik yapi skoru: {b['score']:+.2f} ({b['label']}) "
                   f"- {b['available']} bilesen")
        for c in b.get("components", []):
            out.append(f"  - {c['name']}: {c['score']:+.2f} | {c['detail']}")

    def fresh(key: str) -> dict | None:
        hit = peek(key)
        if not hit or not isinstance(hit[0], dict) or hit[1] > 7200:
            return None
        return hit[0]

    roo = fresh("macro:riskonoff")
    if roo and roo.get("ok"):
        out.append(f"Risk modu: {roo['mode']} ({roo['score']}/100, "
                   f"{roo.get('positive')} olumlu / {roo.get('negative')} olumsuz)")
    idx = fresh("macro:indices")
    if idx and idx.get("ok"):
        parts = [f"{r['symbol']} {r['value']} ({r['change_pct']:+.2f}%)"
                 for r in idx["rows"][:6]
                 if r.get("ok") and r.get("change_pct") is not None]
        if parts:
            out.append("Makro zemin: " + " | ".join(parts))
    st = fresh("llama:stables")
    if st and st.get("ok"):
        out.append(f"Stablecoin arzi 30g: {st.get('change_30d_pct')}% "
                   f"({st.get('note')})")
    et = fresh("etf:bitcoin")
    if et and et.get("ok"):
        out.append(f"ETF akisi ({et.get('source')}): {et.get('note')}")
    ux = fresh("utxo:realized")
    if ux and ux.get("ok"):
        out.append(f"BTC MVRV {ux.get('mvrv')} - {ux.get('zone')}; "
                   f"gerceklesmis fiyat {ux.get('realized_price')}")
    sec = fresh("rotation:sectors")
    if sec and sec.get("ok"):
        inn = ", ".join(r["sector"] for r in (sec.get("inflow") or [])[:3])
        outt = ", ".join(r["sector"] for r in (sec.get("outflow") or [])[:3])
        if inn or outt:
            out.append(f"Sektor rotasyonu: GIRIS [{inn}] / CIKIS [{outt}]")
    sm = fresh("flows:smartmoney")
    if sm and sm.get("ok"):
        out.append(f"Smart money ({sm.get('source')}) genel skor "
                   f"{sm.get('score'):+.2f}")
    hls = fresh("hl:sentiment")
    if hls and hls.get("ok"):
        out.append(f"Hyperliquid geneli: {hls.get('label')} | agirlikli funding "
                   f"{hls.get('weighted_funding_pct')}%/sa | genislik "
                   f"%{hls.get('breadth_pct')}")
    return out


def _hl_lines(symbol: str) -> list[str]:
    """Hyperliquid perp baglami — kaldiracli islem onerisi icin sart."""
    try:
        from engine.trading.hl_broker import normalize_symbol, universe
        u = universe().get(normalize_symbol(symbol))
    except Exception:  # noqa: BLE001
        return []
    if not u:
        return []
    return ["", "== HYPERLIQUID PERP ==",
            f"Mark {u['mark']:.4f} | saatlik funding {u['funding_hourly'] * 100:+.5f}% "
            f"| azami kaldirac {u['max_leverage']}x",
            f"Acik pozisyon {u['open_interest_usd']:,.0f}$ | 24s hacim "
            f"{u['day_volume_usd']:,.0f}$"]


def _build_prompt(symbol: str, snap: dict, feed: dict, headlines: list[dict],
                  whale: dict | None = None, deriv: dict | None = None) -> str:
    lines = [f"VARLIK: {symbol.upper()}", ""]
    lines += _technical_lines(feed)
    lines += _whale_lines(whale or {})
    lines += _deriv_lines(deriv or {})

    lines += ["", "== PIYASA VERISI =="]
    if snap.get("cex"):
        c = snap["cex"]
        ob = c.get("order_book") or {}
        lines.append(
            f"Binance: {c['price']:.4f} USD | 24s {c['change_pct_24h']:+.2f}% | "
            f"hacim {c['volume_quote_24h']:,.0f} USD | "
            f"defter dengesizligi {ob.get('imbalance', 0):+.2f}")
    if snap.get("dex"):
        d = snap["dex"]
        lines.append(
            f"DEX ({d['dex']}@{d['chain']}): {d['price_usd']:.4f} USD | "
            f"likidite {d['liquidity_usd']:,.0f} USD")
    if snap.get("comparison"):
        lines.append(f"CEX/DEX spread: {snap['comparison']['spread_bps']:+.1f} bps")

    lines += ["", "== GUNCEL HABERLER (internetin son gundemi) =="]
    if headlines:
        for h in headlines[:12]:
            lines.append(f"- [{h['source']}] {h['title']}")
    else:
        lines.append("(haber akisina ulasilamadi)")

    lines += _intel_lines()
    lines += _hl_lines(symbol)

    lines += ["", "Katmanlari yukaridaki sirayla (zemin -> akis -> yapi -> "
              "kalabalik) degerlendir ve SADECE JSON ver."]
    return "\n".join(lines)


def _parse(text: str) -> dict | None:
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except Exception:
        return None


def _heuristic(feed: dict, sent: dict, whale: dict | None = None,
               deriv: dict | None = None) -> dict:
    """LLM yokken: teknik sinyal + haber sentiment + balina baskisindan bias uret."""
    sig = feed.get("signal") or {}
    action = sig.get("action", "HOLD")
    bias = {"BUY": "AL", "SELL": "SAT", "HOLD": "BEKLE"}.get(action, "BEKLE")
    label = sent.get("label", "notr")
    score = float(sent.get("score", 0.0))
    wp = (whale or {}).get("pressure") or {}
    wscore = float(wp.get("score", 0.0))
    whale_txt = ((whale or {}).get("label", "balina verisi yok")
                 + f" (skor {wscore:+.2f})") if whale else "balina verisi yok"
    sq = (deriv or {}).get("squeeze") or {}
    deriv_txt = (f" Vadeli: {sq.get('direction', 'notr')} (funding "
                 f"{(deriv or {}).get('funding_pct', 0):+.3f}%)." if deriv and deriv.get("ok") else "")
    crowd = (f"Haber tonu '{label}' ({score:+.2f}); balina: {whale_txt}. "
             + ("Buyuk emirler ALIM tarafinda." if wscore > 0.15
                else "Buyuk emirler SATIM tarafinda." if wscore < -0.15
                else "Balinada net yon yok.") + deriv_txt)
    intel_txt = ""
    try:
        from engine.marketdata.intel import bias as _ib
        b = _ib.market_bias()
        if b.get("ok"):
            intel_txt = (f" Yapisal zemin: {b['label']} ({b['score']:+.2f}, "
                         f"{b['available']} bilesen).")
    except Exception:  # noqa: BLE001
        pass
    return {
        "bias": bias,
        "confidence": round(float(sig.get("confidence", 0.5)), 2),
        "sentiment": "BULLISH" if action == "BUY" else "BEARISH" if action == "SELL" else "NEUTRAL",
        "chart_view": sig.get("rationale", "grafik verisi sinirli"),
        "crowd_view": crowd,
        "macro_view": intel_txt.strip() or "istihbarat verisi yok",
        "flow_view": whale_txt,
        "trade": {"venue": "hyperliquid", "side": "YOK", "leverage": 1,
                  "leverage_note": "LLM kapali - kaldirac karari uretilmedi",
                  "rationale": "LLM kapali - otomatik islem plani uretilmedi"},
        "summary": (f"Teknik {action}, haber tonu {label} -> egilim: {bias}."
                    + intel_txt),
        "risks": ["Sezgisel ozet (LLM kapali); dogrulama icin grafigi inceleyin."],
        "heuristic": True,
    }


def analyze(symbol: str, news_query: str | None = None,
            depth: str | None = None) -> dict:
    """Tam analiz: grafik + CEX/DEX + haberler + (LLM veya sezgisel) al/sat egilimi."""
    snap = aggregator.snapshot(symbol)
    try:
        feed = chart.chart_feed(symbol, "1h", 200)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst chart hatasi %s: %s", symbol, e)
        feed = {"signal": None, "markers": []}
    headlines = news.fetch_headlines(limit=15, query=news_query or symbol)
    try:
        whale = whales.summary(symbol)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst whale hatasi %s: %s", symbol, e)
        whale = {}
    try:
        deriv = derivatives.summary(symbol)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst deriv hatasi %s: %s", symbol, e)
        deriv = {}
    try:
        flow = onchain.netflow_signal(symbol)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst onchain hatasi %s: %s", symbol, e)
        flow = {"enabled": False}

    report = {
        "symbol": symbol.upper(),
        "ts": now_ms(),
        "market": snap,
        "technical": feed.get("signal"),
        "whales": whale,
        "derivatives": deriv,
        "onchain": flow,
        "headlines": headlines[:10],
        "llm": None,
        "llm_used": False,
    }

    max_tokens = depth_tokens(depth)
    report["depth"] = depth or DEFAULT_DEPTH
    report["max_tokens"] = max_tokens
    text = llm.complete(
        SYSTEM_PROMPT,
        _build_prompt(symbol, snap, feed, headlines, whale, deriv),
        max_tokens=max_tokens)
    if text:
        parsed = _parse(text)
        if parsed:
            report["llm"] = parsed
            report["llm_used"] = True
        else:
            report["llm"] = {"raw": text}
    else:
        # LLM yok -> sezgisel bias (teknik + haber sentiment)
        try:
            sent = news.sentiment(symbol)
        except Exception:
            sent = {"label": "notr", "score": 0.0}
        report["llm"] = _heuristic(feed, sent, whale, deriv)
    return report
