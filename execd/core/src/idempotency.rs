//! Idempotency cache — Python retry'lerinin çift işlem üretmesini engeller.
//!
//! Aynı `idempotency_key` ile gelen istek, ilk sonucu (yan etki üretmeden) döndürür.
//! Zaman enjekte edilebilir (`*_at`) — TTL testleri deterministik.

use dashmap::DashMap;
use std::time::{Duration, Instant};

struct Entry {
    at: Instant,
    value: serde_json::Value,
}

pub struct IdempotencyCache {
    map: DashMap<String, Entry>,
    ttl: Duration,
}

impl IdempotencyCache {
    pub fn new(ttl: Duration) -> Self {
        IdempotencyCache { map: DashMap::new(), ttl }
    }

    pub fn put_at(&self, key: impl Into<String>, value: serde_json::Value, now: Instant) {
        self.map.insert(key.into(), Entry { at: now, value });
    }

    pub fn get_at(&self, key: &str, now: Instant) -> Option<serde_json::Value> {
        if let Some(e) = self.map.get(key) {
            if now.duration_since(e.at) <= self.ttl {
                return Some(e.value.clone());
            }
        }
        // süresi geçmiş -> temizle
        self.map.remove(key);
        None
    }

    pub fn put(&self, key: impl Into<String>, value: serde_json::Value) {
        self.put_at(key, value, Instant::now());
    }

    pub fn get(&self, key: &str) -> Option<serde_json::Value> {
        self.get_at(key, Instant::now())
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }

    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn returns_cached_value() {
        let c = IdempotencyCache::new(Duration::from_secs(600));
        let t0 = Instant::now();
        assert!(c.get_at("k", t0).is_none());
        c.put_at("k", json!({"tx_hash": "0xabc"}), t0);
        let got = c.get_at("k", t0).unwrap();
        assert_eq!(got["tx_hash"], "0xabc");
    }

    #[test]
    fn expires_after_ttl() {
        let c = IdempotencyCache::new(Duration::from_secs(10));
        let t0 = Instant::now();
        c.put_at("k", json!(1), t0);
        // ttl içinde
        assert!(c.get_at("k", t0 + Duration::from_secs(5)).is_some());
        // ttl sonrası
        assert!(c.get_at("k", t0 + Duration::from_secs(11)).is_none());
        assert!(c.is_empty()); // temizlendi
    }
}
